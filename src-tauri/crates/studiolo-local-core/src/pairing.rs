use crate::{new_id, now, Error, LocalCore, Result};
use reqwest::{Client, RequestBuilder, Response, StatusCode, Url};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use sqlx::FromRow;
use std::{
    collections::HashMap,
    future::Future,
    sync::Mutex,
    time::{Duration, Instant},
};
use studiolo_contracts::Uuid;
use zeroize::Zeroizing;

pub type Secret = Zeroizing<String>;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CredentialKind {
    Client,
    Device,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CredentialKey {
    pub core_url: String,
    pub workspace_id: String,
    pub kind: CredentialKind,
    pub identity_id: String,
}

impl CredentialKey {
    pub fn accepts(&self, secret: &str) -> bool {
        let prefix = match self.kind {
            CredentialKind::Client => "nc_live_",
            CredentialKind::Device => "nd_live_",
        };
        secret.strip_prefix(prefix).is_some_and(|token| {
            token.len() >= 40
                && token
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        })
    }
}

pub trait CredentialVault: Send + Sync {
    fn read(&self, key: &CredentialKey) -> impl Future<Output = Result<Option<Secret>>> + Send;
    fn write(&self, key: &CredentialKey, secret: &str) -> impl Future<Output = Result<()>> + Send;
    fn remove(&self, key: &CredentialKey) -> impl Future<Output = Result<()>> + Send;
}

#[derive(Default)]
pub struct InMemoryVault(Mutex<HashMap<CredentialKey, Secret>>);

impl CredentialVault for InMemoryVault {
    async fn read(&self, key: &CredentialKey) -> Result<Option<Secret>> {
        Ok(self.0.lock().map_err(|_| Error::Vault)?.get(key).cloned())
    }

    async fn write(&self, key: &CredentialKey, secret: &str) -> Result<()> {
        if !key.accepts(secret) {
            return Err(Error::Vault);
        }
        self.0
            .lock()
            .map_err(|_| Error::Vault)?
            .insert(key.clone(), Secret::new(secret.to_string()));
        Ok(())
    }

    async fn remove(&self, key: &CredentialKey) -> Result<()> {
        self.0.lock().map_err(|_| Error::Vault)?.remove(key);
        Ok(())
    }
}

#[derive(Debug, FromRow, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Binding {
    pub installation_id: String,
    pub core_url: Option<String>,
    pub workspace_id: Option<String>,
    pub workspace_name: Option<String>,
    pub client_id: Option<String>,
    pub client_name: Option<String>,
    pub app_version: Option<String>,
    pub connected_at: Option<String>,
    pub status: String,
}

impl Binding {
    pub fn connected(&self) -> bool {
        self.status == "connected"
    }

    pub(crate) fn credential_key(&self) -> Option<CredentialKey> {
        Some(CredentialKey {
            core_url: self.core_url.clone()?,
            workspace_id: self.workspace_id.clone()?,
            kind: CredentialKind::Client,
            identity_id: self.client_id.clone()?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PairingRequest {
    pub core_url: String,
    pub username: String,
    pub password: String,
    pub client_name: String,
    pub app_version: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingPreview {
    pub confirmation_id: String,
    pub core_url: String,
    pub workspace_id: String,
    pub workspace_name: String,
}

pub struct PendingPairing {
    preview: PairingPreview,
    jwt: Secret,
    client_name: String,
    app_version: String,
    installation_id: String,
    expires: Instant,
}

impl PendingPairing {
    pub fn preview(&self) -> PairingPreview {
        self.preview.clone()
    }
    pub fn matches(&self, id: &str) -> bool {
        self.preview.confirmation_id == id && Instant::now() < self.expires
    }
}

pub fn core_origin(input: &str) -> Result<String> {
    let input = input.trim();
    let (_, authority) = input.split_once("://").ok_or(Error::InvalidOrigin)?;
    if authority
        .trim_end_matches('/')
        .contains(['/', '\\', '@', '?', '#'])
        || authority.ends_with("//")
        || input.chars().any(char::is_whitespace)
    {
        return Err(Error::InvalidOrigin);
    }
    let url = Url::parse(input).map_err(|_| Error::InvalidOrigin)?;
    let host = url.host_str().ok_or(Error::InvalidOrigin)?;
    let supplied_host = authority
        .trim_end_matches('/')
        .strip_prefix("[::1]")
        .filter(|suffix| suffix.is_empty() || suffix.starts_with(':'))
        .map_or_else(
            || {
                authority
                    .trim_end_matches('/')
                    .split(':')
                    .next()
                    .unwrap_or_default()
            },
            |_| "[::1]",
        );
    let loopback = matches!(host, "localhost" | "127.0.0.1" | "[::1]")
        && host.eq_ignore_ascii_case(supplied_host);
    if url.path() != "/" || (url.scheme() != "https" && !(url.scheme() == "http" && loopback)) {
        return Err(Error::InvalidOrigin);
    }
    Ok(url.origin().ascii_serialization())
}

pub(crate) fn http_client() -> Result<Client> {
    Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(8))
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| Error::Network)
}

pub(crate) async fn send(request: RequestBuilder) -> Result<Response> {
    let response = request.send().await.map_err(|_| Error::Network)?;
    if response.status().is_redirection() {
        return Err(Error::InvalidResponse);
    }
    Ok(response)
}

pub(crate) async fn read_json<T: DeserializeOwned>(response: Response) -> Result<T> {
    let mut response = response;
    let mut bytes = Zeroizing::new(Vec::new());
    const LIMIT: usize = 16 * 1024 * 1024;
    while let Some(chunk) = response.chunk().await.map_err(|_| Error::Network)? {
        if chunk.len() > LIMIT.saturating_sub(bytes.len()) {
            return Err(Error::InvalidResponse);
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| Error::InvalidResponse)
}

async fn successful<T: DeserializeOwned>(response: Response) -> Result<T> {
    match response.status() {
        StatusCode::UNAUTHORIZED => Err(Error::Unauthorized),
        status if status.is_server_error() => Err(Error::Network),
        status if status.is_success() => read_json(response).await,
        _ => Err(Error::InvalidResponse),
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Health {
    status: String,
    service: String,
    version: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Login {
    access_token: String,
    token_type: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Workspace {
    id: Uuid,
    name: String,
    kind: String,
    created_at: String,
    updated_at: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EnrollmentRequest<'a> {
    installation_id: &'a str,
    name: &'a str,
    platform: &'static str,
    app_version: &'a str,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EnrollmentClient {
    id: Uuid,
    installation_id: Uuid,
    workspace_id: Uuid,
    name: String,
    platform: String,
    app_version: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Enrollment {
    client: EnrollmentClient,
    credential: String,
    token_last4: String,
    token_created_at: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ListedClient {
    id: Uuid,
    installation_id: Uuid,
    revoked_at: Option<String>,
    #[serde(rename = "name")]
    _name: String,
    #[serde(rename = "platform")]
    _platform: String,
    #[serde(rename = "appVersion")]
    _app_version: String,
    #[serde(rename = "createdAt")]
    _created_at: String,
    #[serde(rename = "updatedAt")]
    _updated_at: String,
    #[serde(rename = "lastSeenAt")]
    _last_seen_at: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ClientIdentity {
    client_id: Uuid,
    installation_id: Uuid,
    workspace_id: Uuid,
    revoked: bool,
    platform: String,
    #[serde(rename = "name")]
    _name: String,
    #[serde(rename = "appVersion")]
    _app_version: String,
}

impl LocalCore {
    pub async fn binding(&self) -> Result<Binding> {
        Ok(
            sqlx::query_as("SELECT * FROM local_binding WHERE singleton = 1")
                .fetch_one(&self.db)
                .await?,
        )
    }

    pub async fn prepare_pairing(&self, request: PairingRequest) -> Result<PendingPairing> {
        let password = Secret::new(request.password);
        let origin = core_origin(&request.core_url)?;
        let username = request.username.trim();
        let client_name = request.client_name.trim();
        let app_version = request.app_version.trim();
        if username.is_empty()
            || password.is_empty()
            || !(1..=120).contains(&client_name.chars().count())
            || !(1..=40).contains(&app_version.chars().count())
        {
            return Err(Error::InvalidData);
        }
        let binding = self.binding().await?;
        if binding.core_url.as_deref().is_some_and(|url| url != origin) {
            return Err(Error::BindingMismatch);
        }
        let http = http_client()?;
        let health: Health =
            successful(send(http.get(format!("{origin}/api/health"))).await?).await?;
        if health.status != "ok" || health.service != "studiolo" || health.version.is_empty() {
            return Err(Error::InvalidResponse);
        }
        let login_response = send(
            http.post(format!("{origin}/api/v1/auth/login"))
                .json(&serde_json::json!({ "username": username, "password": password.as_str() })),
        )
        .await;
        drop(password);
        let response = login_response?;
        if response.status() == StatusCode::UNAUTHORIZED {
            return Err(Error::InvalidCredentials);
        }
        let login: Login = successful(response).await?;
        let jwt = Secret::new(login.access_token);
        if jwt.is_empty() || login.token_type != "bearer" {
            return Err(Error::InvalidResponse);
        }
        let workspace: Workspace = successful(
            send(
                http.get(format!("{origin}/api/v1/workspace"))
                    .bearer_auth(jwt.as_str()),
            )
            .await?,
        )
        .await?;
        if workspace.kind != "personal"
            || workspace.name.is_empty()
            || workspace.created_at.is_empty()
            || workspace.updated_at.is_empty()
        {
            return Err(Error::InvalidResponse);
        }
        if binding
            .workspace_id
            .as_deref()
            .is_some_and(|id| id != workspace.id.as_str())
        {
            return Err(Error::BindingMismatch);
        }
        Ok(PendingPairing {
            preview: PairingPreview {
                confirmation_id: new_id(),
                core_url: origin,
                workspace_id: workspace.id.into_inner(),
                workspace_name: workspace.name,
            },
            jwt,
            client_name: client_name.to_string(),
            app_version: app_version.to_string(),
            installation_id: binding.installation_id,
            expires: Instant::now() + Duration::from_secs(120),
        })
    }

    pub async fn confirm_pairing(
        &self,
        vault: &impl CredentialVault,
        pending: PendingPairing,
        id: &str,
    ) -> Result<Binding> {
        if !pending.matches(id) {
            return Err(Error::ConfirmationExpired);
        }
        let _guard = self.sync_lock.lock().await;
        let binding = self.binding().await?;
        let origin = &pending.preview.core_url;
        let workspace_id = &pending.preview.workspace_id;
        if binding.installation_id != pending.installation_id
            || binding.core_url.as_ref().is_some_and(|url| url != origin)
            || binding
                .workspace_id
                .as_ref()
                .is_some_and(|id| id != workspace_id)
        {
            return Err(Error::BindingMismatch);
        }
        let http = http_client()?;
        let enrollment = self.enroll(&http, &binding, &pending).await?;
        let credential = Secret::new(enrollment.credential);
        let key = CredentialKey {
            core_url: origin.clone(),
            workspace_id: workspace_id.clone(),
            kind: CredentialKind::Client,
            identity_id: enrollment.client.id.into_inner(),
        };
        if !key.accepts(credential.as_str())
            || enrollment.client.installation_id.as_str() != binding.installation_id
            || enrollment.client.workspace_id.as_str() != workspace_id
            || enrollment.client.platform != "android"
            || enrollment.client.name.is_empty()
            || enrollment.client.app_version.is_empty()
            || enrollment.token_last4 != credential[credential.len() - 4..]
            || enrollment.token_created_at.is_empty()
            || binding
                .client_id
                .as_ref()
                .is_some_and(|id| id != &key.identity_id)
        {
            return Err(Error::InvalidResponse);
        }
        let client: ClientIdentity = successful(
            send(
                http.get(format!("{origin}/api/v1/client/me"))
                    .bearer_auth(credential.as_str()),
            )
            .await?,
        )
        .await?;
        if client.revoked
            || client.client_id.as_str() != key.identity_id
            || client.workspace_id.as_str() != workspace_id
            || client.installation_id.as_str() != binding.installation_id
            || client.platform != "android"
        {
            return Err(Error::InvalidResponse);
        }
        // The vault write is atomic. An interruption before SQLite commits is
        // recoverable by rotating the same installation identity on the next pairing.
        let mut tx = self.db.begin().await?;
        sqlx::query(
            "UPDATE local_binding SET core_url=?, workspace_id=?, workspace_name=?, client_id=?,
            client_name=?, app_version=?, connected_at=?, status='connected' WHERE singleton=1",
        )
        .bind(origin)
        .bind(workspace_id)
        .bind(&pending.preview.workspace_name)
        .bind(&key.identity_id)
        .bind(&enrollment.client.name)
        .bind(&pending.app_version)
        .bind(now())
        .execute(&mut *tx)
        .await?;
        sqlx::query("UPDATE local_sync_state SET blocked=0, last_error=NULL, failure_count=0, next_retry_at=NULL WHERE singleton=1")
            .execute(&mut *tx).await?;
        vault.write(&key, credential.as_str()).await?;
        tx.commit().await?;
        self.binding().await
    }

    async fn enroll(
        &self,
        http: &Client,
        binding: &Binding,
        pending: &PendingPairing,
    ) -> Result<Enrollment> {
        let origin = &pending.preview.core_url;
        let jwt = pending.jwt.as_str();
        let enrollment = EnrollmentRequest {
            installation_id: &binding.installation_id,
            name: &pending.client_name,
            platform: "android",
            app_version: &pending.app_version,
        };
        if binding.client_id.is_none() {
            let response = send(
                http.post(format!("{origin}/api/v1/clients/enroll"))
                    .bearer_auth(jwt)
                    .json(&enrollment),
            )
            .await?;
            if response.status() != StatusCode::CONFLICT {
                return successful(response).await;
            }
        }
        let clients: Vec<ListedClient> = successful(
            send(
                http.get(format!("{origin}/api/v1/clients"))
                    .bearer_auth(jwt),
            )
            .await?,
        )
        .await?;
        let client = clients
            .into_iter()
            .find(|client| client.installation_id.as_str() == binding.installation_id)
            .ok_or(Error::BindingMismatch)?;
        if binding
            .client_id
            .as_deref()
            .is_some_and(|id| id != client.id.as_str())
        {
            return Err(Error::BindingMismatch);
        }
        if client.revoked_at.is_some() {
            self.mark_revoked().await?;
            return Err(Error::Revoked);
        }
        let response = send(
            http.post(format!("{origin}/api/v1/clients/{}/credential", client.id))
                .bearer_auth(jwt),
        )
        .await?;
        if response.status() == StatusCode::CONFLICT {
            self.mark_revoked().await?;
            return Err(Error::Revoked);
        }
        successful(response).await
    }

    async fn mark_revoked(&self) -> Result<()> {
        let mut tx = self.db.begin().await?;
        sqlx::query("UPDATE local_binding SET status='revoked' WHERE singleton=1")
            .execute(&mut *tx)
            .await?;
        sqlx::query("UPDATE local_sync_state SET blocked=1, last_error='client_revoked', next_retry_at=NULL WHERE singleton=1")
            .execute(&mut *tx).await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn disconnect(&self, vault: &impl CredentialVault) -> Result<Binding> {
        let _guard = self.sync_lock.lock().await;
        let binding = self.binding().await?;
        let mut tx = self.db.begin().await?;
        sqlx::query("UPDATE local_binding SET status='disconnected' WHERE singleton=1")
            .execute(&mut *tx)
            .await?;
        sqlx::query("UPDATE local_sync_state SET blocked=0, last_error=NULL, next_retry_at=NULL WHERE singleton=1")
            .execute(&mut *tx).await?;
        tx.commit().await?;
        if let Some(key) = binding.credential_key() {
            vault.remove(&key).await?;
        }
        self.binding().await
    }
}
