"""Core-issued, revocable Nexa application credentials."""

import hashlib
import secrets

from .models import Client, utcnow


PREFIX = "nc_live_"


def issue_credential(client: Client) -> str:
    credential = PREFIX + secrets.token_urlsafe(32)
    client.token_hash = hashlib.sha256(credential.encode("ascii")).hexdigest()
    client.token_last4 = credential[-4:]
    client.token_created_at = utcnow()
    return credential
