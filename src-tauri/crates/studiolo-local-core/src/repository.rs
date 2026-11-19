use crate::{new_id, now, Error, LocalCore, Result};
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::{FromRow, SqliteConnection};
use studiolo_contracts::{parse_entity_data, EntityType};

#[derive(Clone, Debug, FromRow, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Website {
    pub id: String,
    pub category_id: Option<String>,
    pub name: String,
    pub url: String,
    pub description: Option<String>,
    pub icon: Option<String>,
    pub favorite: bool,
    #[sqlx(rename = "sort_order")]
    pub order: i64,
    pub last_visited_at: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    #[serde(skip)]
    pub(crate) visit_count: i64,
    #[serde(skip)]
    pub(crate) sync_revision: i64,
    #[serde(skip)]
    pub(crate) deleted_at: Option<String>,
}

#[derive(Clone, Debug, FromRow, Serialize)]
pub struct Category {
    pub id: String,
    pub name: String,
    #[sqlx(rename = "sort_order")]
    pub order: i64,
    #[serde(skip)]
    pub(crate) sync_revision: i64,
    #[serde(skip)]
    pub(crate) deleted_at: Option<String>,
    #[serde(skip)]
    pub(crate) created_at: String,
    #[serde(skip)]
    pub(crate) updated_at: String,
}

fn patch_optional<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> std::result::Result<Option<Option<T>>, D::Error> {
    Option::<T>::deserialize(deserializer).map(Some)
}

fn patch_required<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> std::result::Result<Option<T>, D::Error> {
    T::deserialize(deserializer).map(Some)
}

#[derive(Default, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct WebsitePatch {
    #[serde(deserialize_with = "patch_optional")]
    pub category_id: Option<Option<String>>,
    #[serde(deserialize_with = "patch_required")]
    pub name: Option<String>,
    #[serde(deserialize_with = "patch_required")]
    pub url: Option<String>,
    #[serde(deserialize_with = "patch_optional")]
    pub description: Option<Option<String>>,
    #[serde(deserialize_with = "patch_optional")]
    pub icon: Option<Option<String>>,
    #[serde(deserialize_with = "patch_required")]
    pub favorite: Option<bool>,
    #[serde(deserialize_with = "patch_required")]
    pub order: Option<i64>,
}

#[derive(Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CategoryPatch {
    #[serde(deserialize_with = "patch_required")]
    pub name: Option<String>,
    #[serde(deserialize_with = "patch_required")]
    pub order: Option<i64>,
}

#[derive(Default, Deserialize)]
#[serde(default, rename_all = "camelCase", deny_unknown_fields)]
pub struct WebsiteFilters {
    pub category_id: Option<String>,
    pub search: Option<String>,
    pub favorite: Option<bool>,
    pub sort: WebsiteSort,
}

#[derive(Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum WebsiteSort {
    #[default]
    Order,
    Name,
    CreatedAt,
    UpdatedAt,
    Recent,
}

#[derive(Debug, FromRow)]
pub(crate) struct MutationRow {
    pub mutation_id: String,
    pub entity_type: String,
    pub entity_id: String,
    pub operation: String,
    pub base_revision: i64,
    pub payload_json: Option<String>,
    #[cfg(test)]
    pub depends_on_mutation_id: Option<String>,
    #[cfg(test)]
    pub previous_mutation_id: Option<String>,
    pub status: String,
    pub attempt_count: i64,
    pub last_error: Option<String>,
    pub conflict_json: Option<String>,
}

impl Website {
    fn new() -> Self {
        let timestamp = now();
        Self {
            id: new_id(),
            category_id: None,
            name: String::new(),
            url: String::new(),
            description: None,
            icon: None,
            favorite: false,
            order: 0,
            last_visited_at: None,
            created_at: timestamp.clone(),
            updated_at: timestamp,
            visit_count: 0,
            sync_revision: 0,
            deleted_at: None,
        }
    }

    fn patch(&mut self, patch: WebsitePatch) {
        if let Some(value) = patch.category_id {
            self.category_id = value;
        }
        if let Some(value) = patch.name {
            self.name = value.trim().into();
        }
        if let Some(value) = patch.url {
            self.url = value;
        }
        if let Some(value) = patch.description {
            self.description = value;
        }
        if let Some(value) = patch.icon {
            self.icon = value;
        }
        if let Some(value) = patch.favorite {
            self.favorite = value;
        }
        if let Some(value) = patch.order {
            self.order = value;
        }
    }

    pub(crate) fn payload(&self) -> Value {
        json!({
            "categoryId": self.category_id, "name": self.name, "url": self.url, "description": self.description,
            "icon": self.icon, "favorite": self.favorite, "order": self.order, "lastVisitedAt": self.last_visited_at,
            "createdAt": self.created_at, "updatedAt": self.updated_at,
        })
    }

    pub(crate) async fn save(&self, db: &mut SqliteConnection) -> Result<()> {
        sqlx::query("INSERT INTO websites (id, category_id, name, url, description, icon, favorite, sort_order,
            last_visited_at, created_at, updated_at, visit_count, sync_revision, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET category_id=excluded.category_id, name=excluded.name, url=excluded.url,
            description=excluded.description, icon=excluded.icon, favorite=excluded.favorite,
            sort_order=excluded.sort_order, last_visited_at=excluded.last_visited_at, created_at=excluded.created_at,
            updated_at=excluded.updated_at, visit_count=excluded.visit_count, sync_revision=excluded.sync_revision,
            deleted_at=excluded.deleted_at")
            .bind(&self.id).bind(&self.category_id).bind(&self.name).bind(&self.url).bind(&self.description)
            .bind(&self.icon).bind(self.favorite).bind(self.order).bind(&self.last_visited_at).bind(&self.created_at)
            .bind(&self.updated_at).bind(self.visit_count).bind(self.sync_revision).bind(&self.deleted_at)
            .execute(db).await?;
        Ok(())
    }
}

impl Category {
    pub(crate) fn new() -> Self {
        let timestamp = now();
        Self {
            id: new_id(),
            name: String::new(),
            order: 0,
            sync_revision: 0,
            deleted_at: None,
            created_at: timestamp.clone(),
            updated_at: timestamp,
        }
    }

    pub(crate) fn payload(&self) -> Value {
        json!({ "name": self.name, "order": self.order })
    }

    pub(crate) async fn save(&self, db: &mut SqliteConnection) -> Result<()> {
        sqlx::query("INSERT INTO website_categories (id, name, sort_order, sync_revision, deleted_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, sort_order=excluded.sort_order,
            sync_revision=excluded.sync_revision, deleted_at=excluded.deleted_at, updated_at=excluded.updated_at")
            .bind(&self.id).bind(&self.name).bind(self.order).bind(self.sync_revision).bind(&self.deleted_at)
            .bind(&self.created_at).bind(&self.updated_at).execute(db).await?;
        Ok(())
    }
}

pub(crate) fn entity_table(kind: EntityType) -> Result<&'static str> {
    match kind {
        EntityType::Website => Ok("websites"),
        EntityType::WebsiteCategory => Ok("website_categories"),
        _ => Err(Error::InvalidData),
    }
}

pub(crate) async fn website(db: &mut SqliteConnection, id: &str) -> Result<Option<Website>> {
    Ok(sqlx::query_as("SELECT * FROM websites WHERE id = ?")
        .bind(id)
        .fetch_optional(db)
        .await?)
}

pub(crate) async fn category(db: &mut SqliteConnection, id: &str) -> Result<Option<Category>> {
    Ok(
        sqlx::query_as("SELECT * FROM website_categories WHERE id = ?")
            .bind(id)
            .fetch_optional(db)
            .await?,
    )
}

pub(crate) async fn entity_mutations(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
) -> Result<Vec<MutationRow>> {
    Ok(sqlx::query_as(
        "SELECT * FROM local_mutations WHERE entity_type = ? AND entity_id = ? ORDER BY rowid",
    )
    .bind(kind.as_str())
    .bind(id)
    .fetch_all(db)
    .await?)
}

pub(crate) async fn enqueue(
    db: &mut SqliteConnection,
    kind: EntityType,
    id: &str,
    revision: i64,
    payload: Option<Value>,
    category_id: Option<&str>,
) -> Result<String> {
    let dependency: Option<String> = if let Some(category_id) = category_id {
        // Depend on the creation, including a rejected/conflicted creation.
        sqlx::query_scalar(
            "SELECT m.mutation_id FROM local_mutations m JOIN website_categories c
            ON c.id = m.entity_id WHERE m.entity_type = 'website.category' AND m.entity_id = ?
            AND c.sync_revision = 0 AND m.operation = 'upsert' ORDER BY m.rowid LIMIT 1",
        )
        .bind(category_id)
        .fetch_optional(&mut *db)
        .await?
    } else {
        None
    };

    let operation = if payload.is_some() {
        "upsert"
    } else {
        "delete"
    };
    let payload = payload.map(|data| data.to_string());
    let entries = entity_mutations(db, kind, id).await?;
    let previous = entries.last();
    let timestamp = now();
    if let Some(entry) =
        previous.filter(|entry| entry.status == "pending" && entry.attempt_count == 0)
    {
        sqlx::query("UPDATE local_mutations SET operation = ?, payload_json = ?, depends_on_mutation_id = ?, updated_at = ?
            WHERE mutation_id = ?").bind(operation).bind(payload).bind(dependency).bind(timestamp)
            .bind(&entry.mutation_id).execute(db).await?;
        return Ok(entry.mutation_id.clone());
    }

    let mutation_id = new_id();
    sqlx::query("INSERT INTO local_mutations (mutation_id, entity_type, entity_id, operation, base_revision, payload_json,
        depends_on_mutation_id, previous_mutation_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        .bind(&mutation_id).bind(kind.as_str()).bind(id).bind(operation).bind(revision).bind(payload).bind(dependency)
        .bind(previous.map(|entry| &entry.mutation_id)).bind(&timestamp).bind(timestamp.clone()).execute(db).await?;
    Ok(mutation_id)
}

impl LocalCore {
    pub async fn websites(&self, filters: WebsiteFilters) -> Result<Vec<Website>> {
        let sort = match filters.sort {
            WebsiteSort::Order => "sort_order ASC",
            WebsiteSort::Name => "name ASC",
            WebsiteSort::CreatedAt => "julianday(created_at) DESC",
            WebsiteSort::UpdatedAt => "julianday(updated_at) DESC",
            WebsiteSort::Recent => "julianday(last_visited_at) DESC",
        };
        let query = format!("SELECT id, name, url, description, icon, favorite, sort_order, last_visited_at,
            created_at, updated_at, visit_count, sync_revision, deleted_at,
            CASE WHEN EXISTS (SELECT 1 FROM website_categories c WHERE c.id=websites.category_id AND c.deleted_at IS NULL)
                THEN category_id ELSE NULL END AS category_id
            FROM websites WHERE deleted_at IS NULL
            AND (?1 IS NULL OR (category_id = ?1 AND EXISTS
                (SELECT 1 FROM website_categories c WHERE c.id=?1 AND c.deleted_at IS NULL)))
            AND (?2 IS NULL OR favorite = ?2)
            AND (?3 IS NULL OR name LIKE ?3 OR url LIKE ?3 OR description LIKE ?3) ORDER BY {sort}, id");
        Ok(sqlx::query_as(&query)
            .bind(filters.category_id)
            .bind(filters.favorite)
            .bind(filters.search.map(|value| format!("%{}%", value.trim())))
            .fetch_all(&self.db)
            .await?)
    }

    pub async fn categories(&self) -> Result<Vec<Category>> {
        Ok(sqlx::query_as(
            "SELECT * FROM website_categories WHERE deleted_at IS NULL ORDER BY sort_order, id",
        )
        .fetch_all(&self.db)
        .await?)
    }

    pub async fn save_website(&self, id: Option<&str>, patch: WebsitePatch) -> Result<Website> {
        let mut tx = self.db.begin().await?;
        let mut item = match id {
            Some(id) => website(&mut tx, id)
                .await?
                .filter(|item| item.deleted_at.is_none())
                .ok_or(Error::NotFound)?,
            None => Website::new(),
        };
        if patch.category_id.is_none() {
            clear_deleted_parent(&mut tx, &mut item).await?;
        }
        item.patch(patch);
        item.updated_at = now();
        let parsed = Url::parse(&item.url).map_err(|_| Error::InvalidData)?;
        if !matches!(parsed.scheme(), "http" | "https")
            || parsed.host().is_none()
            || !item
                .url
                .split_once("://")
                .is_some_and(|(_, rest)| !rest.starts_with('/'))
            || item.url.chars().any(char::is_whitespace)
        {
            return Err(Error::InvalidData);
        }
        let payload = item.payload();
        parse_entity_data(EntityType::Website, &payload).map_err(|_| Error::InvalidData)?;
        if let Some(id) = item.category_id.as_deref() {
            category(&mut tx, id)
                .await?
                .filter(|item| item.deleted_at.is_none())
                .ok_or(Error::CategoryNotFound)?;
        }
        item.save(&mut tx).await?;
        enqueue(
            &mut tx,
            EntityType::Website,
            &item.id,
            item.sync_revision,
            Some(payload),
            item.category_id.as_deref(),
        )
        .await?;
        tx.commit().await?;
        Ok(item)
    }

    pub async fn visit_website(&self, id: &str) -> Result<Website> {
        let mut tx = self.db.begin().await?;
        let mut item = website(&mut tx, id)
            .await?
            .filter(|item| item.deleted_at.is_none())
            .ok_or(Error::NotFound)?;
        clear_deleted_parent(&mut tx, &mut item).await?;
        item.updated_at = now();
        item.last_visited_at = Some(item.updated_at.clone());
        item.visit_count = item.visit_count.saturating_add(1);
        item.save(&mut tx).await?;
        enqueue(
            &mut tx,
            EntityType::Website,
            id,
            item.sync_revision,
            Some(item.payload()),
            item.category_id.as_deref(),
        )
        .await?;
        tx.commit().await?;
        Ok(item)
    }

    pub async fn delete_website(&self, id: &str) -> Result<()> {
        let mut tx = self.db.begin().await?;
        let mut item = website(&mut tx, id)
            .await?
            .filter(|item| item.deleted_at.is_none())
            .ok_or(Error::NotFound)?;
        item.deleted_at = Some(now());
        item.save(&mut tx).await?;
        enqueue(
            &mut tx,
            EntityType::Website,
            id,
            item.sync_revision,
            None,
            None,
        )
        .await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn save_category(&self, id: Option<&str>, patch: CategoryPatch) -> Result<Category> {
        let mut tx = self.db.begin().await?;
        let mut item = match id {
            Some(id) => category(&mut tx, id)
                .await?
                .filter(|item| item.deleted_at.is_none())
                .ok_or(Error::NotFound)?,
            None => Category::new(),
        };
        if let Some(name) = patch.name {
            item.name = name.trim().into();
        }
        if let Some(order) = patch.order {
            item.order = order;
        }
        item.updated_at = now();
        let payload = item.payload();
        parse_entity_data(EntityType::WebsiteCategory, &payload).map_err(|_| Error::InvalidData)?;
        item.save(&mut tx).await?;
        enqueue(
            &mut tx,
            EntityType::WebsiteCategory,
            &item.id,
            item.sync_revision,
            Some(payload),
            None,
        )
        .await?;
        tx.commit().await?;
        Ok(item)
    }

    pub async fn delete_category(&self, id: &str) -> Result<()> {
        let mut tx = self.db.begin().await?;
        let mut item = category(&mut tx, id)
            .await?
            .filter(|item| item.deleted_at.is_none())
            .ok_or(Error::NotFound)?;
        let timestamp = now();
        item.deleted_at = Some(timestamp.clone());
        item.save(&mut tx).await?;
        // Core publishes the detachment of every clean child as part of deleting its parent.
        let children: Vec<Website> =
            sqlx::query_as("SELECT * FROM websites WHERE category_id = ? AND deleted_at IS NULL")
                .bind(id)
                .fetch_all(&mut *tx)
                .await?;
        for mut child in children {
            if !entity_mutations(&mut tx, EntityType::Website, &child.id)
                .await?
                .is_empty()
            {
                child.category_id = None;
                child.updated_at = timestamp.clone();
                child.save(&mut tx).await?;
                enqueue(
                    &mut tx,
                    EntityType::Website,
                    &child.id,
                    child.sync_revision,
                    Some(child.payload()),
                    None,
                )
                .await?;
            }
        }
        enqueue(
            &mut tx,
            EntityType::WebsiteCategory,
            id,
            item.sync_revision,
            None,
            None,
        )
        .await?;
        tx.commit().await?;
        Ok(())
    }
}

async fn clear_deleted_parent(db: &mut SqliteConnection, item: &mut Website) -> Result<()> {
    if let Some(id) = item.category_id.as_deref() {
        if category(db, id)
            .await?
            .is_some_and(|parent| parent.deleted_at.is_some())
        {
            item.category_id = None;
        }
    }
    Ok(())
}
