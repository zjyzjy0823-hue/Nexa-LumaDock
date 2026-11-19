use crate::pairing::{http_client, read_json, send};
use crate::repository::{
    category, enqueue, entity_mutations, entity_table, website, Category, MutationRow, Website,
};
use crate::{now, CredentialVault, Error, LocalCore, Result};
use chrono::{SecondsFormat, Utc};
use reqwest::{Client, RequestBuilder, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sqlx::{FromRow, SqliteConnection};
use studiolo_contracts::{
    BaseRevision, ChangesResponse, CursorError, EntityType, Mutation, MutationBatch,
    MutationResult, MutationsResponse, Operation, ProtocolVersion, SnapshotEntity, SnapshotPage,
    Uuid, WebsiteCategoryData, WebsiteData,
};

const CHANGE_LIMIT: u16 = 100;
const SNAPSHOT_LIMIT: u16 = 200;
const BATCH_LIMIT: usize = 100;
const SNAPSHOT_ATTEMPTS: usize = 3;

#[derive(FromRow, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncStatus {
    pub connected: bool,
    pub enabled: bool,
    pub running: bool,
    pub cursor: i64,
    pub blocked: bool,
    pub queue_seeded: bool,
    pub last_error: Option<String>,
    pub last_attempt_at: Option<String>,
    pub last_success_at: Option<String>,
    pub next_retry_at: Option<String>,
    pub pending: i64,
    pub in_flight: i64,
    pub conflicts: i64,
    pub rejected: i64,
}

#[derive(Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SyncReport {
    pub pushed: usize,
    pub pulled: usize,
    pub workspace_revision: i64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct RemoteValue {
    current_revision: i64,
    current: Option<Map<String, Value>>,
    deleted: bool,
    detected_at: String,
}

fn tracked(kind: EntityType) -> bool {
    matches!(kind, EntityType::Website | EntityType::WebsiteCategory)
}

fn revision(value: u64) -> Result<i64> {
    i64::try_from(value).map_err(|_| Error::InvalidResponse)
}

fn stored_payload(value: &Option<String>) -> Result<Option<Map<String, Value>>> {
    value
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .map_err(|_| Error::InvalidData)
}

fn parse_remote(kind: EntityType, data: &RemoteValue) -> Result<()> {
    if data.deleted != data.current.is_none() || data.current_revision < 0 {
        return Err(Error::InvalidResponse);
    }
    if let Some(value) = &data.current {
        studiolo_contracts::parse_entity_data(kind, &Value::Object(value.clone()))
            .map_err(|_| Error::InvalidResponse)?;
    }
    Ok(())
}

fn kind_of(entry: &MutationRow) -> Result<EntityType> {
    entry.entity_type.parse().map_err(|_| Error::InvalidData)
}

impl MutationRow {
    fn as_mutation(&self) -> Result<Mutation> {
        Ok(Mutation {
            mutation_id: Uuid::try_new(&self.mutation_id).map_err(|_| Error::InvalidData)?,
            entity_id: Uuid::try_new(&self.entity_id).map_err(|_| Error::InvalidData)?,
            entity_type: kind_of(self)?,
            operation: self.operation.parse().map_err(|_| Error::InvalidData)?,
            base_revision: BaseRevision::try_new(self.base_revision as u64)
                .map_err(|_| Error::InvalidData)?,
            data: stored_payload(&self.payload_json)?,
        })
    }

    fn remote(&self) -> Result<RemoteValue> {
        serde_json::from_str(self.conflict_json.as_deref().ok_or(Error::InvalidData)?)
            .map_err(|_| Error::InvalidData)
    }
}

struct SyncV3Client<'a> {
    http: Client,
    origin: &'a str,
    credential: &'a str,
}

impl<'a> SyncV3Client<'a> {
    async fn request<T: serde::de::DeserializeOwned>(&self, request: RequestBuilder) -> Result<T> {
        let response = send(request.bearer_auth(self.credential)).await?;
        match response.status() {
            StatusCode::UNAUTHORIZED => Err(Error::Unauthorized),
            StatusCode::CONFLICT => {
                #[derive(Deserialize)]
                struct Detail {
                    detail: String,
                }
                let failure: Detail = read_json(response).await?;
                match failure.detail.as_str() {
                    "sync_protocol_mismatch" => Err(Error::ProtocolMismatch),
                    "sync_in_progress" => Err(Error::SyncInProgress),
                    "snapshot_expired" => Err(Error::SnapshotExpired),
                    _ => Err(Error::InvalidResponse),
                }
            }
            StatusCode::BAD_REQUEST => {
                let _: CursorError = read_json(response).await?;
                Err(Error::ResyncRequired)
            }
            status if status.is_success() => read_json(response).await,
            status if status.is_server_error() || status == StatusCode::TOO_MANY_REQUESTS => {
                Err(Error::Network)
            }
            _ => Err(Error::InvalidResponse),
        }
    }

    fn get(&self, path: &str, limit: u16) -> RequestBuilder {
        self.http
            .get(format!("{}/api/v1/sync/{path}", self.origin))
            .query(&[
                ("protocolVersion", u16::from(ProtocolVersion::V3.get())),
                ("limit", limit),
            ])
    }

    async fn push(&self, mutations: Vec<Mutation>) -> Result<MutationsResponse> {
        self.request(
            self.http
                .post(format!("{}/api/v1/sync/mutations", self.origin))
                .json(&MutationBatch {
                    protocol_version: ProtocolVersion::V3,
                    mutations,
                }),
        )
        .await
    }

    async fn snapshot(&self) -> Result<(i64, Vec<SnapshotEntity>)> {
        for _ in 0..SNAPSHOT_ATTEMPTS {
            match self.snapshot_attempt().await {
                Err(Error::SnapshotExpired) => continue,
                outcome => return outcome,
            }
        }
        Err(Error::SnapshotExpired)
    }

    async fn snapshot_attempt(&self) -> Result<(i64, Vec<SnapshotEntity>)> {
        let mut entities = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut current: Option<(String, i64)> = None;
        let mut cursor: Option<String> = None;
        loop {
            let mut request = self.get("snapshot", SNAPSHOT_LIMIT);
            if let (Some((id, _)), Some(cursor)) = (&current, &cursor) {
                request = request.query(&[("snapshotId", id), ("cursor", cursor)]);
            }
            let page: SnapshotPage = self.request(request).await?;
            page.validate().map_err(|_| Error::InvalidResponse)?;
            let pin = (
                page.snapshot_id.into_inner(),
                revision(page.workspace_revision)?,
            );
            if current.as_ref().is_some_and(|previous| previous != &pin) {
                return Err(Error::InvalidResponse);
            }
            for entity in page
                .entities
                .into_iter()
                .filter(|entity| tracked(entity.entity_type))
            {
                if !seen.insert((entity.entity_type, entity.entity_id.clone())) {
                    return Err(Error::InvalidResponse);
                }
                entities.push(entity);
            }
            let next = page.cursor.map(|value| value.into_inner());
            if next.is_none() {
                return Ok((pin.1, entities));
            }
            if next == cursor {
                return Err(Error::InvalidResponse);
            }
            current = Some(pin);
            cursor = next;
        }
    }
}

impl LocalCore {
    pub async fn sync_status(&self) -> Result<SyncStatus> {
        let running = self.sync_lock.try_lock().is_err();
        Ok(sqlx::query_as("SELECT s.*, b.status='connected' AS connected, b.status='connected' AS enabled, ? AS running,
            (SELECT count(*) FROM local_mutations WHERE status='pending' AND attempt_count=0) AS pending,
            (SELECT count(*) FROM local_mutations WHERE status='pending' AND attempt_count>0) AS in_flight,
            (SELECT count(*) FROM local_mutations WHERE status='conflict') AS conflicts,
            (SELECT count(*) FROM local_mutations WHERE status='rejected') AS rejected
            FROM local_sync_state s JOIN local_binding b USING (singleton)")
            .bind(running).fetch_one(&self.db).await?)
    }

    pub async fn sync(&self, vault: &impl CredentialVault, snapshot: bool) -> Result<SyncReport> {
        let _guard = self
            .sync_lock
            .try_lock()
            .map_err(|_| Error::SyncInProgress)?;
        let binding = self.binding().await?;
        if !binding.connected() {
            return Err(if binding.status == "revoked" {
                Error::Revoked
            } else {
                Error::Disconnected
            });
        }
        let status = self.sync_status().await?;
        if status.blocked {
            return Err(match status.last_error.as_deref() {
                Some("sync_protocol_mismatch") => Error::ProtocolMismatch,
                _ => Error::Unauthorized,
            });
        }
        sqlx::query("UPDATE local_sync_state SET last_attempt_at=? WHERE singleton=1")
            .bind(now())
            .execute(&self.db)
            .await?;
        let outcome = async {
            let key = binding.credential_key().ok_or(Error::Unauthorized)?;
            let credential = vault
                .read(&key)
                .await?
                .filter(|secret| key.accepts(secret.as_str()))
                .ok_or(Error::Unauthorized)?;
            let remote = SyncV3Client {
                http: http_client()?,
                origin: &key.core_url,
                credential: credential.as_str(),
            };
            let mut report = SyncReport::default();
            if snapshot {
                self.resync(&remote, &mut report).await?;
            } else {
                // Replay uncertain commits before pulling, so our own changes cannot
                // turn a frozen mutation into a false conflict following a timeout.
                self.push(&remote, &mut report).await?;
            }
            match self.pull(&remote, &mut report).await {
                Err(Error::ResyncRequired) => {
                    self.resync(&remote, &mut report).await?;
                    self.pull(&remote, &mut report).await?;
                }
                result => result?,
            }
            Ok(report)
        }
        .await;
        self.record_outcome(&outcome).await?;
        outcome
    }

    async fn record_outcome(&self, outcome: &Result<SyncReport>) -> Result<()> {
        if let Err(error) = outcome {
            let blocked = matches!(error, Error::Unauthorized | Error::ProtocolMismatch);
            let transient = matches!(
                error,
                Error::Network | Error::SyncInProgress | Error::SnapshotExpired
            );
            let failures: i64 = sqlx::query_scalar("SELECT failure_count FROM local_sync_state")
                .fetch_one(&self.db)
                .await?;
            let delay = (5_i64 << failures.clamp(0, 6)).min(300);
            let retry = transient.then(|| {
                (Utc::now() + chrono::Duration::seconds(delay))
                    .to_rfc3339_opts(SecondsFormat::Micros, true)
            });
            sqlx::query("UPDATE local_sync_state SET blocked=?, last_error=?, next_retry_at=?, failure_count=? WHERE singleton=1")
                .bind(blocked).bind(error.to_string()).bind(retry).bind((failures + 1).min(7)).execute(&self.db).await?;
        } else {
            sqlx::query("UPDATE local_sync_state SET blocked=0, last_error=NULL, last_success_at=?, next_retry_at=NULL,
                failure_count=0 WHERE singleton=1").bind(now()).execute(&self.db).await?;
        }
        Ok(())
    }

    async fn push(&self, remote: &SyncV3Client<'_>, report: &mut SyncReport) -> Result<()> {
        loop {
            let mut tx = self.db.begin().await?;
            let mut entries: Vec<MutationRow> = sqlx::query_as("SELECT * FROM local_mutations WHERE status='pending'
                AND depends_on_mutation_id IS NULL AND previous_mutation_id IS NULL
                ORDER BY (entity_type='website.category' AND operation='delete'), (attempt_count > 0) DESC, rowid LIMIT ?")
                .bind(BATCH_LIMIT as i64).fetch_all(&mut *tx).await?;
            let Some(first) = entries.first() else {
                return Ok(());
            };
            // Let edited children reach Core before a category's server-side
            // detachment can advance their revisions.
            let category_delete = |entry: &MutationRow| {
                entry.entity_type == "website.category" && entry.operation == "delete"
            };
            if !category_delete(first) {
                entries.retain(|entry| !category_delete(entry));
            }
            let mutations = entries
                .iter()
                .map(MutationRow::as_mutation)
                .collect::<Result<Vec<_>>>()?;
            for entry in &entries {
                sqlx::query("UPDATE local_mutations SET attempt_count=attempt_count+1, updated_at=? WHERE mutation_id=?")
                    .bind(now()).bind(&entry.mutation_id).execute(&mut *tx).await?;
            }
            tx.commit().await?;

            let response = remote.push(mutations).await?;
            response.validate().map_err(|_| Error::InvalidResponse)?;
            if response.results.len() != entries.len() {
                return Err(Error::InvalidResponse);
            }
            let mut tx = self.db.begin().await?;
            let mut pushed = 0;
            for (entry, result) in entries.iter().zip(response.results) {
                if result.mutation_id() != Some(&entry.mutation_id) {
                    return Err(Error::InvalidResponse);
                }
                let kind = kind_of(entry)?;
                match result {
                    MutationResult::Applied(result)
                        if result.entity_type == kind
                            && result.entity_id.as_str() == entry.entity_id
                            && result.base_revision.get() == entry.base_revision as u64 =>
                    {
                        let revision = revision(result.revision.get())?;
                        if revision <= entry.base_revision {
                            return Err(Error::InvalidResponse);
                        }
                        set_revision(&mut tx, kind, &entry.entity_id, revision).await?;
                        remove_acknowledged(&mut tx, &entry.mutation_id, revision).await?;
                        pushed += 1;
                    }
                    MutationResult::Conflict(result)
                        if result.entity_type == kind
                            && result.entity_id.as_str() == entry.entity_id
                            && result.base_revision.get() == entry.base_revision as u64 =>
                    {
                        let absent =
                            result.current_revision == 0 && result.current.as_object().is_none();
                        if absent && entry.operation == "delete" && entry.base_revision == 0 {
                            // A create followed by a delete before its first push
                            // may reach Core as a single tombstone. No row exists there.
                            remove_acknowledged(&mut tx, &entry.mutation_id, 0).await?;
                            continue;
                        }
                        let snapshot = RemoteValue {
                            current_revision: revision(result.current_revision)?,
                            current: result.current.as_object().cloned(),
                            deleted: result.deleted || absent,
                            detected_at: now(),
                        };
                        parse_remote(kind, &snapshot)?;
                        save_conflict(&mut tx, entry, snapshot).await?;
                    }
                    MutationResult::Rejected(result)
                        if result.entity_type == entry.entity_type
                            && result.entity_id == entry.entity_id
                            && result.base_revision == entry.base_revision =>
                    {
                        sqlx::query("UPDATE local_mutations SET status='rejected', last_error=?, updated_at=? WHERE mutation_id=?")
                            .bind(result.reason.as_str()).bind(now()).bind(&entry.mutation_id).execute(&mut *tx).await?;
                    }
                    _ => return Err(Error::InvalidResponse),
                }
            }
            tx.commit().await?;
            report.pushed += pushed;
        }
    }

    async fn pull(&self, remote: &SyncV3Client<'_>, report: &mut SyncReport) -> Result<()> {
        let mut cursor = self.sync_status().await?.cursor;
        loop {
            let page: ChangesResponse = remote
                .request(
                    remote
                        .get("changes", CHANGE_LIMIT)
                        .query(&[("cursor", cursor)]),
                )
                .await?;
            page.validate().map_err(|_| Error::InvalidResponse)?;
            let next = revision(page.cursor)?;
            let first = page.changes.first().map(|change| change.revision.get());
            if next < cursor
                || (page.has_more && first.is_none())
                || first.is_some_and(|value| value <= cursor as u64)
                || (first.is_none() && next != cursor)
            {
                return Err(Error::InvalidResponse);
            }
            let mut tx = self.db.begin().await?;
            let mut pulled = 0;
            for change in page
                .changes
                .into_iter()
                .filter(|change| tracked(change.entity_type))
            {
                let snapshot = RemoteValue {
                    current_revision: revision(change.revision.get())?,
                    current: change.data,
                    deleted: change.operation == Operation::Delete,
                    detected_at: now(),
                };
                pulled += usize::from(
                    apply_remote(
                        &mut tx,
                        change.entity_type,
                        change.entity_id.as_str(),
                        snapshot,
                        false,
                    )
                    .await?,
                );
            }
            save_cursor(&mut tx, next).await?;
            tx.commit().await?;
            report.pulled += pulled;
            cursor = next;
            report.workspace_revision = revision(page.workspace_revision)?;
            if !page.has_more {
                return Ok(());
            }
        }
    }

    async fn resync(&self, remote: &SyncV3Client<'_>, report: &mut SyncReport) -> Result<()> {
        sqlx::query("UPDATE local_sync_state SET last_error='resync_required' WHERE singleton=1")
            .execute(&self.db)
            .await?;
        let (revision, rows) = remote.snapshot().await?;
        let mut tx = self.db.begin().await?;
        let mut pulled = 0;
        for row in rows {
            let snapshot = RemoteValue {
                current_revision: row.sync_revision.get() as i64,
                current: row.data,
                deleted: row.deleted,
                detected_at: now(),
            };
            pulled += usize::from(
                apply_remote(
                    &mut tx,
                    row.entity_type,
                    row.entity_id.as_str(),
                    snapshot,
                    true,
                )
                .await?,
            );
        }
        // An entity updated after the pinned revision may be missing from the
        // snapshot. Only explicit tombstones delete rows; changes complete recovery.
        save_cursor(&mut tx, revision).await?;
        tx.commit().await?;
        report.pulled += pulled;
        report.workspace_revision = revision;
        Ok(())
    }
}

async fn save_cursor(db: &mut SqliteConnection, cursor: i64) -> Result<()> {
    sqlx::query("UPDATE local_sync_state SET cursor=? WHERE singleton=1")
        .bind(cursor)
        .execute(db)
        .await?;
    Ok(())
}

async fn set_revision(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
    revision: i64,
) -> Result<()> {
    let query = format!(
        "UPDATE {} SET sync_revision=? WHERE id=?",
        entity_table(kind)?
    );
    if sqlx::query(&query)
        .bind(revision)
        .bind(id)
        .execute(db)
        .await?
        .rows_affected()
        != 1
    {
        return Err(Error::InvalidData);
    }
    Ok(())
}

async fn remove_acknowledged(db: &mut SqliteConnection, id: &str, revision: i64) -> Result<()> {
    sqlx::query("UPDATE local_mutations SET previous_mutation_id=NULL, base_revision=? WHERE previous_mutation_id=?")
        .bind(revision).bind(id).execute(&mut *db).await?;
    sqlx::query(
        "UPDATE local_mutations SET depends_on_mutation_id=NULL WHERE depends_on_mutation_id=?",
    )
    .bind(id)
    .execute(&mut *db)
    .await?;
    sqlx::query("DELETE FROM local_mutations WHERE mutation_id=?")
        .bind(id)
        .execute(db)
        .await?;
    Ok(())
}

async fn save_conflict(
    db: &mut SqliteConnection,
    entry: &MutationRow,
    mut snapshot: RemoteValue,
) -> Result<()> {
    if entry.status == "conflict" {
        let previous = entry.remote()?;
        if previous.current_revision > snapshot.current_revision {
            return Ok(());
        }
        snapshot.detected_at = previous.detected_at;
    }
    let data = serde_json::to_string(&snapshot).map_err(|_| Error::InvalidData)?;
    sqlx::query("UPDATE local_mutations SET status='conflict', conflict_json=?, updated_at=? WHERE mutation_id=?")
        .bind(data).bind(now()).bind(&entry.mutation_id).execute(db).await?;
    Ok(())
}

async fn apply_remote(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
    remote: RemoteValue,
    snapshot: bool,
) -> Result<bool> {
    parse_remote(kind, &remote)?;
    let query = format!(
        "SELECT sync_revision FROM {} WHERE id=?",
        entity_table(kind)?
    );
    let current: Option<i64> = sqlx::query_scalar(&query)
        .bind(id)
        .fetch_optional(&mut *db)
        .await?;
    if !snapshot && current.is_some_and(|revision| revision >= remote.current_revision) {
        return Ok(false);
    }
    let entries = entity_mutations(db, kind, id).await?;
    if let Some(entry) = entries.first() {
        let diverged = entry.base_revision < remote.current_revision
            || (snapshot && entry.base_revision != remote.current_revision);
        if entry.status == "conflict"
            || (entry.status == "pending" && diverged && entry.attempt_count == 0)
        {
            save_conflict(db, entry, remote).await?;
        }
        return Ok(false);
    }
    apply_business_row(db, kind, id, remote).await?;
    Ok(true)
}

async fn apply_business_row(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
    remote: RemoteValue,
) -> Result<()> {
    let Some(data) = remote.current else {
        let query = format!(
            "UPDATE {} SET sync_revision=?, deleted_at=? WHERE id=?",
            entity_table(kind)?
        );
        sqlx::query(&query)
            .bind(remote.current_revision)
            .bind(now())
            .bind(id)
            .execute(db)
            .await?;
        return Ok(());
    };
    match kind {
        EntityType::Website => {
            let data: WebsiteData =
                serde_json::from_value(Value::Object(data)).map_err(|_| Error::InvalidResponse)?;
            let timestamp = now();
            let category_id = data.category_id.map(Uuid::into_inner);
            if let Some(parent) = category_id.as_deref() {
                // The parent can be absent from a snapshot if it moved beyond
                // the pinned revision. Keep its UUID until changes supplies it.
                sqlx::query("INSERT OR IGNORE INTO website_categories
                    (id, name, sort_order, deleted_at, created_at, updated_at) VALUES (?, '', 0, ?, ?, ?)")
                    .bind(parent).bind(&timestamp).bind(&timestamp).bind(&timestamp).execute(&mut *db).await?;
            }
            let visit_count = website(db, id).await?.map_or(0, |item| item.visit_count);
            Website {
                id: id.to_string(),
                name: data.name.into_inner(),
                url: data.url.into_inner(),
                category_id,
                description: data.description.map(|value| value.into_inner()),
                icon: data.icon.map(|value| value.into_inner()),
                favorite: data.favorite.unwrap_or(false),
                order: revision(data.order.unwrap_or(0))?,
                visit_count,
                last_visited_at: data.last_visited_at.map(|value| value.into_inner()),
                sync_revision: remote.current_revision,
                created_at: data
                    .created_at
                    .map(|value| value.into_inner())
                    .unwrap_or_else(|| timestamp.clone()),
                updated_at: data
                    .updated_at
                    .map(|value| value.into_inner())
                    .unwrap_or(timestamp),
                deleted_at: None,
            }
            .save(db)
            .await?;
        }
        EntityType::WebsiteCategory => {
            let data: WebsiteCategoryData =
                serde_json::from_value(Value::Object(data)).map_err(|_| Error::InvalidResponse)?;
            let mut item = category(db, id).await?.unwrap_or_else(Category::new);
            item.id = id.to_string();
            item.name = data.name.into_inner();
            item.order = revision(data.order.unwrap_or(0))?;
            item.updated_at = now();
            item.sync_revision = remote.current_revision;
            item.deleted_at = None;
            item.save(db).await?;
        }
        _ => return Err(Error::InvalidResponse),
    }
    Ok(())
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ConflictStrategy {
    Local,
    Remote,
}

impl LocalCore {
    pub async fn conflicts(&self) -> Result<Vec<Value>> {
        self.queue_listing("conflict").await
    }

    pub async fn rejected(&self) -> Result<Vec<Value>> {
        self.queue_listing("rejected").await
    }

    async fn queue_listing(&self, status: &str) -> Result<Vec<Value>> {
        let mut tx = self.db.begin().await?;
        let pairs: Vec<(String, String, String)> = sqlx::query_as(
            "SELECT mutation_id, created_at, updated_at FROM local_mutations
            WHERE status=? ORDER BY rowid",
        )
        .bind(status)
        .fetch_all(&mut *tx)
        .await?;
        let mut entries = Vec::new();
        for (id, created_at, updated_at) in pairs {
            let entry = find_entry(&mut tx, &id, status).await?;
            let kind = kind_of(&entry)?;
            let (_, current, _) = live_draft(&mut tx, kind, &entry.entity_id).await?;
            if status == "conflict" {
                let remote = entry.remote()?;
                let has_pending_tail: bool = sqlx::query_scalar(
                    "SELECT EXISTS(SELECT 1 FROM local_mutations WHERE previous_mutation_id=?)",
                )
                .bind(&id)
                .fetch_one(&mut *tx)
                .await?;
                entries.push(json!({ "id": id, "entityType": kind, "entityId": entry.entity_id, "localDeleted": current.is_none(),
                    "local": current, "remote": remote.current, "remoteRevision": remote.current_revision, "remoteDeleted": remote.deleted,
                    "createdAt": created_at, "updatedAt": updated_at, "detectedAt": remote.detected_at, "hasPendingTail": has_pending_tail }));
            } else {
                entries.push(json!({ "id": id, "mutationId": id, "entityType": kind, "entityId": entry.entity_id, "operation": entry.operation,
                    "baseRevision": entry.base_revision, "reason": entry.last_error, "attempts": entry.attempt_count,
                    "payload": stored_payload(&entry.payload_json)?, "updatedAt": updated_at }));
            }
        }
        tx.commit().await?;
        Ok(entries)
    }

    pub async fn resolve_conflict(
        &self,
        id: &str,
        strategy: ConflictStrategy,
        expected_revision: i64,
    ) -> Result<Value> {
        let _guard = self
            .sync_lock
            .try_lock()
            .map_err(|_| Error::SyncInProgress)?;
        let mut tx = self.db.begin().await?;
        let entry = find_entry(&mut tx, id, "conflict").await?;
        let remote = entry.remote()?;
        if remote.current_revision != expected_revision {
            return Err(Error::InvalidData);
        }
        let kind = kind_of(&entry)?;
        let mutation_id = match strategy {
            ConflictStrategy::Local => {
                set_revision(&mut tx, kind, &entry.entity_id, expected_revision).await?;
                Some(rebuild_mutation(&mut tx, &entry).await?)
            }
            ConflictStrategy::Remote => {
                if remote.deleted {
                    discard_dependents(&mut tx, id).await?;
                } else {
                    sqlx::query("DELETE FROM local_mutations WHERE previous_mutation_id=?")
                        .bind(id)
                        .execute(&mut *tx)
                        .await?;
                    remove_acknowledged(&mut tx, id, expected_revision).await?;
                }
                apply_business_row(&mut tx, kind, &entry.entity_id, remote).await?;
                None
            }
        };
        tx.commit().await?;
        Ok(
            json!({ "id": id, "strategy": if matches!(strategy, ConflictStrategy::Local) { "local" } else { "remote" },
            "status": "resolved", "remoteRevision": expected_revision, "mutationId": mutation_id, "resolvedAt": now() }),
        )
    }

    pub async fn decide_rejected(&self, id: &str, retry: bool) -> Result<Value> {
        let _guard = self
            .sync_lock
            .try_lock()
            .map_err(|_| Error::SyncInProgress)?;
        let mut tx = self.db.begin().await?;
        let entry = find_entry(&mut tx, id, "rejected").await?;
        let mutation_id = if retry {
            Some(rebuild_mutation(&mut tx, &entry).await?)
        } else {
            discard_dependents(&mut tx, id).await?;
            None
        };
        tx.commit().await?;
        Ok(
            json!({ "id": id, "decision": if retry { "retry" } else { "dismiss" }, "status": "resolved",
            "mutationId": mutation_id, "resolvedAt": now() }),
        )
    }
}

async fn find_entry(db: &mut SqliteConnection, id: &str, status: &str) -> Result<MutationRow> {
    sqlx::query_as("SELECT * FROM local_mutations WHERE mutation_id=? AND status=?")
        .bind(id)
        .bind(status)
        .fetch_optional(db)
        .await?
        .ok_or(Error::NotFound)
}

async fn live_draft(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
) -> Result<(i64, Option<Value>, Option<String>)> {
    match kind {
        EntityType::Website => {
            let item = website(db, id).await?.ok_or(Error::NotFound)?;
            let payload = item.deleted_at.is_none().then(|| item.payload());
            let parent = payload.as_ref().and(item.category_id);
            Ok((item.sync_revision, payload, parent))
        }
        EntityType::WebsiteCategory => {
            let item = category(db, id).await?.ok_or(Error::NotFound)?;
            Ok((
                item.sync_revision,
                item.deleted_at.is_none().then(|| item.payload()),
                None,
            ))
        }
        _ => Err(Error::InvalidData),
    }
}

async fn discard_dependents(db: &mut SqliteConnection, id: &str) -> Result<()> {
    sqlx::query(
        "WITH RECURSIVE discarded(id) AS (SELECT ? UNION
        SELECT m.mutation_id FROM local_mutations m JOIN discarded d
        ON m.depends_on_mutation_id=d.id OR m.previous_mutation_id=d.id)
        DELETE FROM local_mutations WHERE mutation_id IN (SELECT id FROM discarded)",
    )
    .bind(id)
    .execute(db)
    .await?;
    Ok(())
}

async fn rebuild_mutation(db: &mut SqliteConnection, entry: &MutationRow) -> Result<String> {
    let kind = kind_of(entry)?;
    let (revision, payload, parent) = live_draft(db, kind, &entry.entity_id).await?;
    if let Some(parent) = parent.as_deref() {
        category(db, parent)
            .await?
            .filter(|item| item.deleted_at.is_none())
            .ok_or(Error::CategoryNotFound)?;
    }
    // Replace the rejected predecessor and its editable tail in one transaction.
    sqlx::query("DELETE FROM local_mutations WHERE entity_type=? AND entity_id=?")
        .bind(&entry.entity_type)
        .bind(&entry.entity_id)
        .execute(&mut *db)
        .await?;
    let generated = enqueue(
        db,
        kind,
        &entry.entity_id,
        revision,
        payload,
        parent.as_deref(),
    )
    .await?;
    sqlx::query(
        "UPDATE local_mutations SET depends_on_mutation_id=? WHERE depends_on_mutation_id=?",
    )
    .bind(&generated)
    .bind(&entry.mutation_id)
    .execute(db)
    .await?;
    Ok(generated)
}
