#![forbid(unsafe_code)]

mod pairing;
mod repository;
mod sync;
#[cfg(test)]
mod tests;

pub use pairing::*;
pub use repository::*;
pub use sync::*;

use chrono::{SecondsFormat, Utc};
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous};
use sqlx::SqlitePool;
use std::{path::Path, sync::Arc, time::Duration};
use tokio::sync::Mutex;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("local_database")]
    Database(#[from] sqlx::Error),
    #[error("local_database_migration")]
    Migration(#[from] sqlx::migrate::MigrateError),
    #[error("invalid_data")]
    InvalidData,
    #[error("not_found")]
    NotFound,
    #[error("category_not_found")]
    CategoryNotFound,
    #[error("invalid_core_url")]
    InvalidOrigin,
    #[error("connection_binding_mismatch")]
    BindingMismatch,
    #[error("client_revoked")]
    Revoked,
    #[error("workspace_confirmation_expired")]
    ConfirmationExpired,
    #[error("invalid_credentials")]
    InvalidCredentials,
    #[error("unauthorized")]
    Unauthorized,
    #[error("disconnected")]
    Disconnected,
    #[error("network_error")]
    Network,
    #[error("invalid_response")]
    InvalidResponse,
    #[error("sync_protocol_mismatch")]
    ProtocolMismatch,
    #[error("sync_in_progress")]
    SyncInProgress,
    #[error("snapshot_expired")]
    SnapshotExpired,
    #[error("resync_required")]
    ResyncRequired,
    #[error("credential_storage")]
    Vault,
}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone)]
pub struct LocalCore {
    db: SqlitePool,
    sync_lock: Arc<Mutex<()>>,
}

impl LocalCore {
    pub async fn open(path: impl AsRef<Path>) -> Result<Self> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .foreign_keys(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .busy_timeout(Duration::from_secs(5));
        let db = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_with(options)
            .await?;
        sqlx::migrate!().run(&db).await?;
        sqlx::query("INSERT OR IGNORE INTO local_binding (singleton, installation_id, status) VALUES (1, ?, 'disconnected')")
            .bind(new_id()).execute(&db).await?;
        Ok(Self {
            db,
            sync_lock: Arc::new(Mutex::new(())),
        })
    }

    pub async fn close(&self) {
        self.db.close().await;
    }
}

fn now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

fn new_id() -> String {
    uuid::Uuid::new_v4().to_string()
}
