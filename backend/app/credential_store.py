"""Replaceable storage boundary for Local Nexa Client bearer credentials."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fastapi import HTTPException


def connection_directory(user_id: int) -> Path:
    data_dir = os.environ.get("NEXA_DATA_DIR")
    if not data_dir:
        raise HTTPException(409, "Local data directory is not configured")
    return Path(data_dir) / "core-connections" / str(user_id)


@dataclass
class StagedFile:
    destination: Path
    temporary: Path

    def commit(self) -> None:
        os.replace(self.temporary, self.destination)

    def discard(self) -> None:
        self.temporary.unlink(missing_ok=True)


class StagedCredential(Protocol):
    def commit(self) -> None: ...

    def discard(self) -> None: ...


def stage_file(destination: Path, content: bytes) -> StagedFile:
    """Write and fsync a private temporary file without replacing live data."""
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".nexa-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                if os.name != "nt":
                    raise
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        return StagedFile(destination=destination, temporary=temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class CredentialStore(Protocol):
    def stage(self, user_id: int, credential: str) -> StagedCredential: ...

    def save(self, user_id: int, credential: str) -> None: ...

    def load(self, user_id: int) -> str | None: ...

    def delete(self, user_id: int) -> None: ...


class FileCredentialStore:
    """AppData file implementation; a future OS keychain can replace this class."""

    def _path(self, user_id: int) -> Path:
        return connection_directory(user_id) / "credential"

    def stage(self, user_id: int, credential: str) -> StagedFile:
        return stage_file(self._path(user_id), credential.encode("ascii"))

    def save(self, user_id: int, credential: str) -> None:
        staged = self.stage(user_id, credential)
        try:
            staged.commit()
        finally:
            staged.discard()

    def load(self, user_id: int) -> str | None:
        try:
            return self._path(user_id).read_text(encoding="ascii")
        except (FileNotFoundError, UnicodeError):
            return None

    def delete(self, user_id: int) -> None:
        self._path(user_id).unlink(missing_ok=True)
