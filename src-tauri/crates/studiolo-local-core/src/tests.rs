use super::*;
use crate::repository::entity_mutations;
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex},
    thread,
};
use studiolo_contracts::EntityType;

const WORKSPACE: &str = "673af91c-ac87-4331-9e2d-e5a3f073b212";
const CLIENT: &str = "06c4df17-b239-412e-8763-361324640ae4";
const CATEGORY: &str = "001d8999-4a87-4b24-9998-aa6ceca300b2";
const WEBSITE: &str = "daa3228c-04a1-4658-9d77-49ae23410b51";
const UNCHANGED: &str = "1cb211ca-a335-4593-aead-9474e9634074";
const TOKEN: &str = "nc_live_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const ROTATED: &str = "nc_live_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const STAMP: &str = "2026-11-19T00:00:00+00:00";

fn website_patch(name: &str) -> WebsitePatch {
    WebsitePatch {
        name: Some(name.into()),
        url: Some("https://example.org/".into()),
        ..Default::default()
    }
}

fn category_patch(name: &str) -> CategoryPatch {
    CategoryPatch {
        name: Some(name.into()),
        ..Default::default()
    }
}

async fn database() -> (tempfile::TempDir, LocalCore) {
    let dir = tempfile::tempdir().unwrap();
    let db = LocalCore::open(dir.path().join("websites.sqlite"))
        .await
        .unwrap();
    (dir, db)
}

#[tokio::test]
async fn writes_and_outbox_roll_back_together() {
    let (_dir, db) = database().await;
    for url in [
        "file:///x",
        "http:///invalid",
        "https://example.org/white space",
        "http://example.org:invalid",
    ] {
        let patch = WebsitePatch {
            url: Some(url.into()),
            ..website_patch("Invalid")
        };
        assert!(
            matches!(db.save_website(None, patch).await, Err(Error::InvalidData)),
            "{url}"
        );
    }
    let patch = WebsitePatch {
        category_id: Some(Some(CATEGORY.into())),
        ..website_patch("Missing parent")
    };
    assert!(matches!(
        db.save_website(None, patch).await,
        Err(Error::CategoryNotFound)
    ));
    sqlx::query(
        "CREATE TRIGGER reject_local_mutations BEFORE INSERT ON local_mutations
        BEGIN SELECT RAISE(ABORT, 'forced outbox failure'); END",
    )
    .execute(&db.db)
    .await
    .unwrap();
    assert!(matches!(
        db.save_website(None, website_patch("Rollback")).await,
        Err(Error::Database(_))
    ));
    assert!(db.websites(Default::default()).await.unwrap().is_empty());
    assert_eq!(db.sync_status().await.unwrap().pending, 0);
}

#[tokio::test]
async fn reopening_preserves_ids_dependencies_visits_and_tombstones() {
    let (dir, db) = database().await;
    let installation = db.binding().await.unwrap().installation_id;
    let group = db
        .save_category(None, category_patch("Work"))
        .await
        .unwrap();
    let item = db
        .save_website(
            None,
            WebsitePatch {
                category_id: Some(Some(group.id.clone())),
                ..website_patch("Draft")
            },
        )
        .await
        .unwrap();
    let deleted = db
        .save_website(None, website_patch("Delete"))
        .await
        .unwrap();
    let mut conn = db.db.acquire().await.unwrap();
    let parent = entity_mutations(&mut conn, EntityType::WebsiteCategory, &group.id)
        .await
        .unwrap()
        .pop()
        .unwrap();
    let child = entity_mutations(&mut conn, EntityType::Website, &item.id)
        .await
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(
        child.depends_on_mutation_id.as_deref(),
        Some(parent.mutation_id.as_str())
    );
    drop(conn);
    db.visit_website(&item.id).await.unwrap();
    db.save_website(
        Some(&item.id),
        WebsitePatch {
            name: Some("Edited".into()),
            ..Default::default()
        },
    )
    .await
    .unwrap();
    db.delete_website(&deleted.id).await.unwrap();
    db.close().await;

    let db = LocalCore::open(dir.path().join("websites.sqlite"))
        .await
        .unwrap();
    assert_eq!(db.binding().await.unwrap().installation_id, installation);
    let items = db.websites(Default::default()).await.unwrap();
    assert_eq!(items.len(), 1);
    assert_eq!(
        (&items[0].id, items[0].name.as_str(), items[0].visit_count),
        (&item.id, "Edited", 1)
    );
    let mut conn = db.db.acquire().await.unwrap();
    let entries = entity_mutations(&mut conn, EntityType::Website, &item.id)
        .await
        .unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].mutation_id, child.mutation_id);
    assert_eq!(entries[0].base_revision, 0);
    assert!(entries[0].previous_mutation_id.is_none());
    let tombstone = entity_mutations(&mut conn, EntityType::Website, &deleted.id)
        .await
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(tombstone.operation, "delete");
    assert!(tombstone.payload_json.is_none());
    assert_eq!(
        sqlx::query_scalar::<_, String>("PRAGMA journal_mode")
            .fetch_one(&mut *conn)
            .await
            .unwrap(),
        "wal"
    );
    assert_eq!(
        sqlx::query_scalar::<_, i32>("PRAGMA foreign_keys")
            .fetch_one(&mut *conn)
            .await
            .unwrap(),
        1
    );
}

struct Request {
    line: String,
    authorization: Option<String>,
    body: Value,
}

fn read_request(stream: &TcpStream) -> Request {
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    let mut length = 0;
    let mut authorization = None;
    loop {
        let mut header = String::new();
        if reader.read_line(&mut header).unwrap() == 0 || header == "\r\n" {
            break;
        }
        let (name, value) = header.split_once(':').unwrap();
        if name.eq_ignore_ascii_case("content-length") {
            length = value.trim().parse().unwrap();
        }
        if name.eq_ignore_ascii_case("authorization") {
            authorization = Some(value.trim().to_string());
        }
    }
    let mut body = vec![0; length];
    reader.read_exact(&mut body).unwrap();
    Request {
        line,
        authorization,
        body: serde_json::from_slice(&body).unwrap_or(Value::Null),
    }
}

fn mock_core(
    handler: impl Fn(&Request) -> Option<(u16, Value)> + Send + 'static,
) -> (String, Arc<Mutex<Vec<Request>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let requests = Arc::new(Mutex::new(Vec::new()));
    let seen = Arc::clone(&requests);
    thread::spawn(move || {
        for mut stream in listener.incoming().map_while(std::result::Result::ok) {
            let request = read_request(&stream);
            let reply = handler(&request);
            seen.lock().unwrap().push(request);
            if let Some((status, body)) = reply {
                let body = body.to_string();
                write!(stream, "HTTP/1.1 {status} Mock\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}", body.len()).unwrap();
            }
        }
    });
    (origin, requests)
}

fn pairing_reply(
    request: &Request,
    installation: &str,
    token: &str,
    revoked: bool,
) -> Option<(u16, Value)> {
    let path = request.line.split_whitespace().nth(1).unwrap();
    let client = json!({ "id": CLIENT, "installationId": installation, "workspaceId": WORKSPACE,
        "name": "Test Android", "platform": "android", "appVersion": "0.8.0" });
    let value = match path {
        "/api/health" => json!({ "status": "ok", "service": "studiolo", "version": "0.7.2" }),
        "/api/v1/auth/login" => {
            assert_eq!(
                request.body,
                json!({"username": "test-user", "password": "test-password"})
            );
            json!({ "access_token": "temporary-account-token", "token_type": "bearer" })
        }
        "/api/v1/workspace" => {
            json!({ "id": WORKSPACE, "name": "Test Workspace", "kind": "personal", "createdAt": STAMP, "updatedAt": STAMP })
        }
        "/api/v1/clients" => {
            json!([{ "id": CLIENT, "installationId": installation, "name": "Test Android",
            "platform": "android", "appVersion": "0.8.0", "createdAt": STAMP, "updatedAt": STAMP, "lastSeenAt": null,
            "revokedAt": if revoked { Some(STAMP) } else { None } }])
        }
        "/api/v1/clients/enroll" => {
            assert_eq!(
                request.body,
                json!({ "installationId": installation, "name": "Test Android", "platform": "android", "appVersion": "0.8.0" })
            );
            json!({ "client": client, "credential": token, "tokenLast4": &token[token.len()-4..], "tokenCreatedAt": STAMP })
        }
        p if p == format!("/api/v1/clients/{CLIENT}/credential") => {
            json!({ "client": client, "credential": token, "tokenLast4": &token[token.len()-4..], "tokenCreatedAt": STAMP })
        }
        "/api/v1/client/me" => {
            assert_eq!(
                request.authorization.as_deref(),
                Some(format!("Bearer {token}").as_str())
            );
            json!({ "clientId": CLIENT, "installationId": installation, "workspaceId": WORKSPACE,
                "name": "Test Android", "platform": "android", "appVersion": "0.8.0", "revoked": false })
        }
        _ => return None,
    };
    Some((200, value))
}

async fn start_pairing(db: &LocalCore, origin: &str) -> PendingPairing {
    db.prepare_pairing(PairingRequest {
        core_url: origin.into(),
        username: "test-user".into(),
        password: "test-password".into(),
        client_name: "Test Android".into(),
        app_version: "0.8.0".into(),
    })
    .await
    .unwrap()
}

async fn pair(db: &LocalCore, vault: &InMemoryVault, origin: &str) -> Result<Binding> {
    let pending = start_pairing(db, origin).await;
    let id = pending.preview().confirmation_id;
    db.confirm_pairing(vault, pending, &id).await
}

fn page(cursor: u64, revision: u64, has_more: bool, changes: Vec<Value>) -> Value {
    json!({ "protocolVersion": 3, "cursor": cursor, "workspaceRevision": revision, "hasMore": has_more, "changes": changes })
}

fn change(revision: u64, kind: &str, id: &str, data: Value) -> Value {
    json!({ "revision": revision, "entityType": kind, "entityId": id,
        "operation": if data.is_null() { "delete" } else { "upsert" }, "data": data })
}

fn remote_site(name: &str) -> Value {
    json!({ "name": name, "url": "https://example.org/", "createdAt": STAMP, "updatedAt": STAMP })
}

fn outcome(mutation: &Value, fields: Value) -> Value {
    let mut result = json!({ "mutationId": mutation["mutationId"], "entityType": mutation["entityType"],
        "entityId": mutation["entityId"], "baseRevision": mutation["baseRevision"] });
    result
        .as_object_mut()
        .unwrap()
        .extend(fields.as_object().unwrap().clone());
    result
}

#[tokio::test]
async fn confirms_before_enrolling_rotates_same_client_and_blocks_revoked_queue() {
    let (_dir, db) = database().await;
    let installation = db.binding().await.unwrap().installation_id;
    let revoked = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let remote_revoked = Arc::clone(&revoked);
    let (origin, requests) = mock_core(move |request| {
        let revoked = remote_revoked.load(std::sync::atomic::Ordering::SeqCst);
        if request.line.contains("/sync/") {
            return Some((401, json!({ "detail": "Invalid Client" })));
        }
        let token = if request.line.contains("/credential")
            || request.authorization.as_deref() == Some(&format!("Bearer {ROTATED}"))
        {
            ROTATED
        } else {
            TOKEN
        };
        pairing_reply(request, &installation, token, revoked)
    });
    let vault = InMemoryVault::default();
    let pending = start_pairing(&db, &origin).await;
    let preview = pending.preview();
    assert_eq!(preview.workspace_id, WORKSPACE);
    assert_eq!(requests.lock().unwrap().len(), 3);
    let binding = db
        .confirm_pairing(&vault, pending, &preview.confirmation_id)
        .await
        .unwrap();
    let key = binding.credential_key().unwrap();
    assert_eq!(vault.read(&key).await.unwrap().unwrap().as_str(), TOKEN);
    let device = CredentialKey {
        kind: CredentialKind::Device,
        ..key.clone()
    };
    assert!(vault.write(&device, TOKEN).await.is_err());
    assert!(vault.read(&device).await.unwrap().is_none());

    db.disconnect(&vault).await.unwrap();
    assert!(vault.read(&key).await.unwrap().is_none());
    assert_eq!(
        pair(&db, &vault, &origin)
            .await
            .unwrap()
            .client_id
            .as_deref(),
        Some(CLIENT)
    );
    assert_eq!(vault.read(&key).await.unwrap().unwrap().as_str(), ROTATED);
    db.save_website(None, website_patch("Queued"))
        .await
        .unwrap();
    assert!(matches!(
        db.sync(&vault, false).await,
        Err(Error::Unauthorized)
    ));
    let attempts = requests.lock().unwrap().len();
    assert!(matches!(
        db.sync(&vault, false).await,
        Err(Error::Unauthorized)
    ));
    assert_eq!(requests.lock().unwrap().len(), attempts);
    assert!(db.sync_status().await.unwrap().blocked);
    revoked.store(true, std::sync::atomic::Ordering::SeqCst);
    assert!(matches!(
        pair(&db, &vault, &origin).await,
        Err(Error::Revoked)
    ));
    assert_eq!(db.binding().await.unwrap().status, "revoked");
    assert_eq!(db.sync_status().await.unwrap().in_flight, 1);
}

#[tokio::test]
async fn replays_frozen_id_before_successor_and_pushes_category_before_child() {
    let (dir, db) = database().await;
    let installation = db.binding().await.unwrap().installation_id;
    let (origin, _) = mock_core({
        let mut_count = Mutex::new(0);
        let frozen = Mutex::new(None::<Value>);
        move |request| {
            if let Some(reply) = pairing_reply(request, &installation, TOKEN, false) {
                return Some(reply);
            }
            assert_eq!(
                request.authorization.as_deref(),
                Some(format!("Bearer {TOKEN}").as_str())
            );
            if request.line.starts_with("POST ") {
                let mut count = mut_count.lock().unwrap();
                *count += 1;
                let entry = &request.body["mutations"][0];
                assert_eq!(request.body["protocolVersion"], 3);
                assert_eq!(request.body["mutations"].as_array().unwrap().len(), 1);
                match *count {
                    1 => {
                        assert_eq!(entry["entityType"], "website.category");
                    }
                    2 => {
                        assert_eq!(entry["entityType"], "website");
                        *frozen.lock().unwrap() = Some(entry.clone());
                        return None;
                    }
                    3 => {
                        assert_eq!(Some(entry), frozen.lock().unwrap().as_ref());
                    }
                    4 => {
                        assert_ne!(
                            entry["mutationId"],
                            frozen.lock().unwrap().as_ref().unwrap()["mutationId"]
                        );
                        assert_eq!(entry["baseRevision"], 2);
                        assert_eq!(entry["data"]["name"], "Successor");
                    }
                    _ => panic!("unexpected push"),
                }
                let revision = if *count == 1 { 1 } else { *count - 1 };
                return Some((
                    200,
                    json!({ "protocolVersion": 3, "results": [outcome(entry, json!({"status":"applied", "revision": revision}))] }),
                ));
            }
            Some((200, page(0, 0, false, vec![])))
        }
    });
    let vault = InMemoryVault::default();
    pair(&db, &vault, &origin).await.unwrap();
    let group = db
        .save_category(None, category_patch("Work"))
        .await
        .unwrap();
    let site = db
        .save_website(
            None,
            WebsitePatch {
                category_id: Some(Some(group.id)),
                ..website_patch("Before timeout")
            },
        )
        .await
        .unwrap();
    assert!(matches!(db.sync(&vault, false).await, Err(Error::Network)));
    assert!(db.sync_status().await.unwrap().next_retry_at.is_some());
    db.save_website(
        Some(&site.id),
        WebsitePatch {
            name: Some("Successor".into()),
            ..Default::default()
        },
    )
    .await
    .unwrap();
    db.close().await;
    let db = LocalCore::open(dir.path().join("websites.sqlite"))
        .await
        .unwrap();
    assert_eq!(db.sync(&vault, false).await.unwrap().pushed, 2);
    assert_eq!(db.sync_status().await.unwrap().pending, 0);
    assert_eq!(
        db.websites(Default::default()).await.unwrap()[0].name,
        "Successor"
    );
}

#[tokio::test]
async fn pulls_multiple_pages_resolves_conflict_and_recovers_expired_snapshot() {
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    let (_dir, db) = database().await;
    let installation = db.binding().await.unwrap().installation_id;
    let recovering = Arc::new(AtomicBool::new(false));
    let recovering_core = recovering.clone();
    let snapshot_count = AtomicUsize::new(0);
    let (origin, _) = mock_core(move |request| {
        if let Some(reply) = pairing_reply(request, &installation, TOKEN, false) {
            return Some(reply);
        }
        if request.line.starts_with("POST ") {
            let mutation = &request.body["mutations"][0];
            return Some((
                200,
                json!({ "protocolVersion": 3, "results": [outcome(mutation,
                json!({ "status": "conflict", "currentRevision": 4, "current": remote_site("Core edit"), "deleted": false }))] }),
            ));
        }
        if request.line.contains("/snapshot") {
            assert!(request.line.contains("limit=200"));
            return Some(match snapshot_count.fetch_add(1, Ordering::SeqCst) {
                0 => (
                    200,
                    json!({ "protocolVersion":3, "snapshotId":"expired", "workspaceRevision": 4, "entities":[],
                    "cursor":"next", "hasMore":true }),
                ),
                1 => {
                    assert!(
                        request.line.contains("snapshotId=expired")
                            && request.line.contains("cursor=next")
                    );
                    (409, json!({ "detail":"snapshot_expired" }))
                }
                2 => {
                    assert!(!request.line.contains("snapshotId="));
                    (
                        200,
                        json!({ "protocolVersion":3, "snapshotId":"fresh", "workspaceRevision": 4,
                        "entities":[{"entityType":"website","entityId":WEBSITE,"syncRevision":4,"deleted":true,"data":null}],
                        "cursor":null, "hasMore":false }),
                    )
                }
                _ => panic!("unexpected snapshot call"),
            });
        }
        assert!(request.line.contains("limit=100"));
        let cursor = request
            .line
            .split("cursor=")
            .nth(1)
            .unwrap()
            .split([' ', '&'])
            .next()
            .unwrap();
        Some(if recovering_core.load(Ordering::SeqCst) {
            match cursor {
                "3" => (
                    400,
                    json!({ "detail": "Invalid sync cursor", "resyncRequired": true, "workspaceRevision": 4 }),
                ),
                "4" => (200, page(4, 4, false, vec![])),
                _ => panic!("wrong recovery cursor"),
            }
        } else {
            match cursor {
                "0" => (
                    200,
                    page(
                        1,
                        3,
                        true,
                        vec![change(
                            1,
                            "website.category",
                            CATEGORY,
                            json!({"name":"Work","order":0}),
                        )],
                    ),
                ),
                "1" => (
                    200,
                    page(
                        3,
                        3,
                        false,
                        vec![
                            change(2, "website", WEBSITE, remote_site("Shared")),
                            change(
                                3,
                                "website",
                                UNCHANGED,
                                remote_site("Missing from snapshot"),
                            ),
                        ],
                    ),
                ),
                "3" => (200, page(3, 3, false, vec![])),
                _ => panic!("unexpected cursor"),
            }
        })
    });
    let vault = InMemoryVault::default();
    pair(&db, &vault, &origin).await.unwrap();
    assert_eq!(db.sync(&vault, false).await.unwrap().pulled, 3);
    db.save_website(
        Some(WEBSITE),
        WebsitePatch {
            name: Some("Local draft".into()),
            ..Default::default()
        },
    )
    .await
    .unwrap();
    db.sync(&vault, false).await.unwrap();
    let conflict = db.conflicts().await.unwrap().pop().unwrap();
    assert_eq!(conflict["local"]["name"], "Local draft");
    assert_eq!(conflict["remote"]["name"], "Core edit");
    db.resolve_conflict(
        conflict["id"].as_str().unwrap(),
        ConflictStrategy::Remote,
        4,
    )
    .await
    .unwrap();
    assert!(db.conflicts().await.unwrap().is_empty());
    recovering.store(true, Ordering::SeqCst);
    assert_eq!(db.sync(&vault, false).await.unwrap().workspace_revision, 4);
    let sites = db.websites(Default::default()).await.unwrap();
    assert_eq!(sites.len(), 1);
    assert_eq!(sites[0].id, UNCHANGED);
}

#[test]
fn restricts_core_origin_and_disallows_url_credentials() {
    assert_eq!(
        core_origin("https://core.example.test:443/").unwrap(),
        "https://core.example.test"
    );
    for valid in [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://[::1]:8080",
    ] {
        assert_eq!(core_origin(valid).unwrap(), valid);
    }
    for invalid in [
        "http://10.0.0.1:8080",
        "https://@core.example.test",
        "https://core.example.test/a",
        "https://core.example.test/#",
        "https://core.example.test/?",
        "http://[::2]",
        "https://core.example.test//",
    ] {
        assert!(
            matches!(core_origin(invalid), Err(Error::InvalidOrigin)),
            "{invalid}"
        );
    }
}

#[tokio::test]
async fn handles_partial_rejection_and_retries_with_a_new_id() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (_dir, db) = database().await;
    let installation = db.binding().await.unwrap().installation_id;
    let batch = AtomicUsize::new(0);
    let failed_id = Mutex::new(None::<Value>);
    let (origin, _) = mock_core(move |request| {
        if let Some(reply) = pairing_reply(request, &installation, TOKEN, false) {
            return Some(reply);
        }
        if !request.line.starts_with("POST ") {
            return Some((200, page(0, 0, false, vec![])));
        }
        let mutations = request.body["mutations"].as_array().unwrap();
        let results = match batch.fetch_add(1, Ordering::SeqCst) {
            0 => {
                assert_eq!(mutations.len(), 2);
                assert_eq!(mutations[0]["entityType"], "website.category");
                *failed_id.lock().unwrap() = Some(mutations[0]["mutationId"].clone());
                vec![
                    outcome(
                        &mutations[0],
                        json!({"status": "rejected", "reason": "invalid_data"}),
                    ),
                    outcome(&mutations[1], json!({"status": "applied", "revision": 1})),
                ]
            }
            1 => {
                assert_eq!(mutations.len(), 1);
                assert_ne!(
                    Some(&mutations[0]["mutationId"]),
                    failed_id.lock().unwrap().as_ref()
                );
                assert_eq!(mutations[0]["data"]["name"], "Fixed");
                vec![outcome(
                    &mutations[0],
                    json!({"status": "applied", "revision": 2}),
                )]
            }
            2 => {
                assert_eq!(mutations.len(), 1);
                assert_eq!(mutations[0]["data"]["name"], "Dependent");
                vec![outcome(
                    &mutations[0],
                    json!({"status": "applied", "revision": 3}),
                )]
            }
            _ => panic!("unexpected batch"),
        };
        Some((200, json!({"protocolVersion": 3, "results": results})))
    });
    let vault = InMemoryVault::default();
    pair(&db, &vault, &origin).await.unwrap();
    let group = db
        .save_category(None, category_patch("Needs a fix"))
        .await
        .unwrap();
    db.save_website(
        None,
        WebsitePatch {
            category_id: Some(Some(group.id.clone())),
            ..website_patch("Dependent")
        },
    )
    .await
    .unwrap();
    db.save_website(None, website_patch("Independent"))
        .await
        .unwrap();
    assert_eq!(db.sync(&vault, false).await.unwrap().pushed, 1);
    let rejected = db.rejected().await.unwrap().pop().unwrap();
    assert_eq!(rejected["reason"], "invalid_data");
    assert_eq!(db.sync_status().await.unwrap().pending, 1);
    db.save_category(Some(&group.id), category_patch("Fixed"))
        .await
        .unwrap();
    db.decide_rejected(rejected["id"].as_str().unwrap(), true)
        .await
        .unwrap();
    assert_eq!(db.sync(&vault, false).await.unwrap().pushed, 2);
    let status = db.sync_status().await.unwrap();
    assert_eq!((status.pending, status.rejected), (0, 0));
}
