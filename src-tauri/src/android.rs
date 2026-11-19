use serde::Deserialize;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::time::Duration;
use studiolo_local_core::{
    Binding, Category, CategoryPatch, ConflictStrategy, CredentialKey, CredentialVault, Error,
    LocalCore, PairingPreview, PairingRequest, PendingPairing, Result, Secret, SyncReport,
    SyncStatus, Website, WebsiteFilters, WebsitePatch,
};
use tauri::plugin::{Builder, PluginHandle, TauriPlugin};
use tauri::{AppHandle, Manager, State, Wry};
use tokio::sync::{Mutex, OnceCell, RwLock, RwLockReadGuard, RwLockWriteGuard};
use uuid::Uuid;

struct AndroidVault(PluginHandle<Wry>);

impl CredentialVault for AndroidVault {
    async fn read(&self, key: &CredentialKey) -> Result<Option<Secret>> {
        #[derive(Deserialize)]
        struct Response {
            secret: Option<String>,
        }
        let result: Response = self
            .0
            .run_mobile_plugin_async("readCredential", json!({ "key": key }))
            .await
            .map_err(|_| Error::Vault)?;
        Ok(result.secret.map(Secret::new))
    }

    async fn write(&self, key: &CredentialKey, secret: &str) -> Result<()> {
        let _: Value = self
            .0
            .run_mobile_plugin_async("writeCredential", json!({ "key": key, "secret": secret }))
            .await
            .map_err(|_| Error::Vault)?;
        Ok(())
    }

    async fn remove(&self, key: &CredentialKey) -> Result<()> {
        let _: Value = self
            .0
            .run_mobile_plugin_async("removeCredential", json!({ "key": key }))
            .await
            .map_err(|_| Error::Vault)?;
        Ok(())
    }
}

pub(crate) struct AndroidLocal {
    vault: AndroidVault,
    root: OnceCell<PathBuf>,
    core: RwLock<Option<LocalCore>>,
    pairing: Mutex<Option<PendingPairing>>,
}

impl AndroidLocal {
    async fn root(&self) -> Result<&PathBuf> {
        self.root
            .get_or_try_init(|| async {
                #[derive(Deserialize)]
                struct Storage {
                    path: PathBuf,
                }
                let value: Storage = self
                    .vault
                    .0
                    .run_mobile_plugin_async("storage", json!({}))
                    .await
                    .map_err(|_| Error::Vault)?;
                Ok(value.path)
            })
            .await
    }

    async fn database(&self) -> Result<RwLockReadGuard<'_, LocalCore>> {
        let read = self.core.read().await;
        if read.is_some() {
            return Ok(RwLockReadGuard::map(read, |core| core.as_ref().unwrap()));
        }
        drop(read);
        let mut write = self.core.write().await;
        if write.is_none() {
            let root = self.root().await?;
            let path = match std::fs::read_to_string(root.join("studiolo-active-replica")) {
                Ok(value) => {
                    let id = Uuid::parse_str(&value).map_err(|_| Error::InvalidData)?;
                    root.join(format!("studiolo-local-{id}.sqlite"))
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    root.join("studiolo-local.sqlite")
                }
                Err(_) => return Err(Error::Vault),
            };
            *write = Some(LocalCore::open(path).await?);
        }
        Ok(RwLockReadGuard::map(
            RwLockWriteGuard::downgrade(write),
            |core| core.as_ref().unwrap(),
        ))
    }
}

pub(crate) fn plugin() -> TauriPlugin<Wry> {
    Builder::new("studiolo-local-vault")
        .setup(|app, api| {
            let handle = api.register_android_plugin("com.isidel.studiolo", "LocalCorePlugin")?;
            app.manage(AndroidLocal {
                vault: AndroidVault(handle),
                root: OnceCell::new(),
                core: RwLock::new(None),
                pairing: Mutex::new(None),
            });
            Ok(())
        })
        .build()
}

pub(crate) struct AndroidNotifications(PluginHandle<Wry>);

pub(crate) fn notifications_plugin() -> TauriPlugin<Wry> {
    Builder::new("studiolo-android-notifications")
        .setup(|app, api| {
            let handle = api.register_android_plugin("com.isidel.studiolo", "AndroidNotifications")?;
            app.manage(AndroidNotifications(handle));
            Ok(())
        })
        .build()
}

type CommandResult<T> = std::result::Result<T, String>;

impl AndroidNotifications {
    async fn invoke(&self, command: &str, payload: Value) -> CommandResult<bool> {
        #[derive(Deserialize)]
        struct Response {
            value: bool,
        }
        self.0
            .run_mobile_plugin_async::<Response>(command, payload)
            .await
            .map(|response| response.value)
            .map_err(|_| "notification_unavailable".into())
    }
}

#[tauri::command]
pub(crate) async fn android_notifications_enabled(
    state: State<'_, AndroidNotifications>,
) -> CommandResult<bool> {
    state.invoke("enabled", json!({})).await
}

#[tauri::command]
pub(crate) async fn android_set_notifications_enabled(
    state: State<'_, AndroidNotifications>,
    enabled: bool,
) -> CommandResult<bool> {
    state.invoke("setEnabled", json!({ "enabled": enabled })).await
}

#[tauri::command]
pub(crate) async fn android_show_fleet_notification(
    state: State<'_, AndroidNotifications>,
    title: String,
    body: String,
) -> CommandResult<bool> {
    state.invoke("show", json!({ "title": title, "body": body })).await
}

fn command_error(error: Error) -> String {
    error.to_string()
}

macro_rules! local_command {
    ($name:ident($($arg:ident: $arg_type:ty),*) -> $output:ty, |$state:ident, $core:ident| $action:expr) => {
        #[tauri::command]
        pub(crate) async fn $name($state: State<'_, AndroidLocal>, $($arg: $arg_type),*) -> CommandResult<$output> {
            let $core = $state.database().await.map_err(command_error)?;
            $action.await.map_err(command_error)
        }
    };
}

#[tauri::command]
pub(crate) fn android_validate_core_url(url: String) -> CommandResult<String> {
    studiolo_local_core::core_origin(&url).map_err(command_error)
}

#[tauri::command]
pub(crate) async fn android_core_prepare(
    app: AppHandle,
    state: State<'_, AndroidLocal>,
    mut request: PairingRequest,
) -> CommandResult<PairingPreview> {
    request.app_version = app.package_info().version.to_string();
    let db = state.database().await.map_err(command_error)?;
    let mut current = state.pairing.lock().await;
    let pending = db.prepare_pairing(request).await.map_err(command_error)?;
    let preview = pending.preview();
    let id = preview.confirmation_id.clone();
    *current = Some(pending);
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_secs(120)).await;
        let state = app.state::<AndroidLocal>();
        let mut current = state.pairing.lock().await;
        if current
            .as_ref()
            .is_some_and(|pending| pending.preview().confirmation_id == id)
        {
            *current = None;
        }
    });
    Ok(preview)
}

#[tauri::command]
pub(crate) async fn android_core_cancel_pending(
    state: State<'_, AndroidLocal>,
    confirmation_id: String,
) -> CommandResult<()> {
    let mut pending = state.pairing.lock().await;
    if pending
        .as_ref()
        .is_some_and(|pending| pending.preview().confirmation_id == confirmation_id)
    {
        *pending = None;
    }
    Ok(())
}

#[tauri::command]
pub(crate) async fn android_core_connect(
    state: State<'_, AndroidLocal>,
    confirmation_id: String,
) -> CommandResult<Binding> {
    let db = state.database().await.map_err(command_error)?;
    let pending = {
        let mut current = state.pairing.lock().await;
        if !current
            .as_ref()
            .is_some_and(|pending| pending.matches(&confirmation_id))
        {
            return Err(command_error(Error::ConfirmationExpired));
        }
        current.take().unwrap()
    };
    db.confirm_pairing(&state.vault, pending, &confirmation_id)
        .await
        .map_err(command_error)
}

#[tauri::command]
pub(crate) async fn android_core_new_replica(
    state: State<'_, AndroidLocal>,
) -> CommandResult<Binding> {
    let mut active = state.core.write().await;
    let root = state.root().await.map_err(command_error)?;
    let id = Uuid::new_v4();
    let db = LocalCore::open(root.join(format!("studiolo-local-{id}.sqlite")))
        .await
        .map_err(command_error)?;
    let binding = db.binding().await.map_err(command_error)?;
    let tmp = root.join("studiolo-active-replica.new");
    {
        use std::io::Write;
        let mut pointer = std::fs::File::create(&tmp).map_err(|_| command_error(Error::Vault))?;
        pointer
            .write_all(id.to_string().as_bytes())
            .and_then(|_| pointer.sync_all())
            .map_err(|_| command_error(Error::Vault))?;
    }
    std::fs::rename(tmp, root.join("studiolo-active-replica"))
        .map_err(|_| command_error(Error::Vault))?;
    *state.pairing.lock().await = None;
    *active = Some(db);
    Ok(binding)
}

local_command!(android_core_status() -> Binding, |_state, db| db.binding());
local_command!(android_core_disconnect() -> Binding, |state, db| db.disconnect(&state.vault));
local_command!(android_websites_list(filters: WebsiteFilters) -> Vec<Website>, |_state, db| db.websites(filters));
local_command!(android_website_create(data: WebsitePatch) -> Website, |_state, db| db.save_website(None, data));
local_command!(android_website_update(id: String, data: WebsitePatch) -> Website, |_state, db| db.save_website(Some(&id), data));
local_command!(android_website_visit(id: String) -> Website, |_state, db| db.visit_website(&id));
local_command!(android_website_delete(id: String) -> (), |_state, db| db.delete_website(&id));
local_command!(android_website_categories_list() -> Vec<Category>, |_state, db| db.categories());
local_command!(android_website_categories_create(data: CategoryPatch) -> Category, |_state, db| db.save_category(None, data));
local_command!(android_website_categories_update(id: String, data: CategoryPatch) -> Category, |_state, db| db.save_category(Some(&id), data));
local_command!(android_website_categories_delete(id: String) -> (), |_state, db| db.delete_category(&id));
local_command!(android_sync_status() -> SyncStatus, |_state, db| db.sync_status());
local_command!(android_sync_run() -> SyncReport, |state, db| db.sync(&state.vault, false));
local_command!(android_sync_resync() -> SyncReport, |state, db| db.sync(&state.vault, true));
local_command!(android_sync_conflicts_list() -> Vec<Value>, |_state, db| db.conflicts());
local_command!(android_sync_conflict_resolve(id: String, strategy: ConflictStrategy, expected_remote_revision: i64) -> Value,
    |_state, db| db.resolve_conflict(&id, strategy, expected_remote_revision));
local_command!(android_sync_rejected_list() -> Vec<Value>, |_state, db| db.rejected());
local_command!(android_sync_rejected_dismiss(id: String) -> Value, |_state, db| db.decide_rejected(&id, false));
local_command!(android_sync_rejected_retry(id: String) -> Value, |_state, db| db.decide_rejected(&id, true));
