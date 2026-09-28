import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db, runtime_config
from .models import Agent, ApiKey, Device, User, utcnow


JWT_SECRET = runtime_config.jwt_secret
JWT_ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def agent_from_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Agent:
    if credentials is None or not credentials.credentials.startswith("na_live_"):
        raise HTTPException(401, "Invalid agent token")
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    agent = db.scalar(select(Agent).where(Agent.token_hash == token_hash))
    if agent is None:
        raise HTTPException(401, "Invalid agent token")
    return agent


def device_from_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Device:
    if credentials is None or not credentials.credentials.startswith("nd_live_"):
        raise HTTPException(401, "Invalid device token")
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    device = db.scalar(select(Device).where(Device.token_hash == token_hash))
    if device is None:
        raise HTTPException(401, "Invalid device token")
    return device


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode({"sub": str(user_id), "exp": expires}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def read_user_for(scope: str):
    def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        db: Session = Depends(get_db),
    ) -> User:
        if credentials is None:
            raise HTTPException(401, "Authentication required")
        secret = credentials.credentials
        if not secret.startswith("sk_live_"):
            return current_user(credentials, db)
        token_hash = hashlib.sha256(secret.encode()).hexdigest()
        item = db.scalar(select(ApiKey).where(ApiKey.token_hash == token_hash))
        if item is None or not item.is_active or (item.expires_at and
                (item.expires_at.replace(tzinfo=timezone.utc) if item.expires_at.tzinfo is None else item.expires_at) <= utcnow()):
            raise HTTPException(401, "Invalid or expired API Key")
        user = db.get(User, item.user_id)
        if user is None:
            raise HTTPException(401, "API Key owner not found")
        item.last_used_at = utcnow()
        db.commit()
        if scope not in item.scopes and "Read" not in item.scopes:
            raise HTTPException(403, "Insufficient API Key scope")
        return user

    return dependency
