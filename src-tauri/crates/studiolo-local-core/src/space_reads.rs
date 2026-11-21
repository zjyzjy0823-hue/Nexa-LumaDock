use crate::pairing::http_client;
use crate::{CredentialVault, Error, LocalCore, Result};
use serde::Deserialize;
use studiolo_contracts::Uuid;

#[derive(Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum DeviceSpaceRead {
    Spaces,
    Space {
        space_id: Uuid,
    },
    Entries {
        space_id: Uuid,
        search: Option<String>,
        entry_type: Option<String>,
    },
    Entry {
        space_id: Uuid,
        entry_id: Uuid,
        revision: Option<u32>,
    },
    Download {
        space_id: Uuid,
        entry_id: Uuid,
        revision: Option<u32>,
    },
}

impl LocalCore {
    pub async fn read_device_space(
        &self,
        vault: &impl CredentialVault,
        read: DeviceSpaceRead,
    ) -> Result<Vec<u8>> {
        let binding = self.binding().await?;
        if !binding.connected() {
            return Err(Error::Disconnected);
        }
        let key = binding.credential_key().ok_or(Error::Unauthorized)?;
        let credential = vault
            .read(&key)
            .await?
            .filter(|secret| key.accepts(secret.as_str()))
            .ok_or(Error::Unauthorized)?;
        let mut query = Vec::new();
        let limit = if matches!(&read, DeviceSpaceRead::Download { .. }) {
            64 * 1024 * 1024
        } else {
            8 * 1024 * 1024
        };
        let path = match read {
            DeviceSpaceRead::Spaces => String::new(),
            DeviceSpaceRead::Space { space_id } => format!("/{space_id}"),
            DeviceSpaceRead::Entries {
                space_id,
                search,
                entry_type,
            } => {
                if let Some(value) = search {
                    query.push(("search", value));
                }
                if let Some(value) = entry_type {
                    query.push(("entryType", value));
                }
                format!("/{space_id}/entries")
            }
            DeviceSpaceRead::Entry {
                space_id,
                entry_id,
                revision,
            } => {
                if let Some(value) = revision {
                    query.push(("revision", value.to_string()));
                }
                format!("/{space_id}/entries/{entry_id}")
            }
            DeviceSpaceRead::Download {
                space_id,
                entry_id,
                revision,
            } => {
                if let Some(value) = revision {
                    query.push(("revision", value.to_string()));
                }
                format!("/{space_id}/entries/{entry_id}/download")
            }
        };
        let mut response = http_client()?
            .get(format!(
                "{}/api/v1/client/space-reads/spaces{path}",
                key.core_url
            ))
            .bearer_auth(credential.as_str())
            .header("Cache-Control", "no-store")
            .query(&query)
            .send()
            .await
            .map_err(|_| Error::Network)?;
        match response.status().as_u16() {
            200..=299 => {}
            401 | 403 => return Err(Error::Unauthorized),
            404 => return Err(Error::NotFound),
            409 => return Err(Error::BindingMismatch),
            _ => return Err(Error::InvalidResponse),
        }
        if response
            .content_length()
            .is_some_and(|length| length > limit as u64)
        {
            return Err(Error::InvalidResponse);
        }
        let mut body = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Network)? {
            if body.len() + chunk.len() > limit {
                return Err(Error::InvalidResponse);
            }
            body.extend_from_slice(&chunk);
        }
        let current = self.binding().await?;
        if !current.connected()
            || current.credential_key().as_ref() != Some(&key)
            || current.connected_at != binding.connected_at
        {
            return Err(Error::BindingMismatch);
        }
        Ok(body)
    }
}
