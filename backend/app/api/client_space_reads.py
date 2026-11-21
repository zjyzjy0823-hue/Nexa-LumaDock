"""Read-only Core access to standard Shared Spaces for enrolled clients."""

import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Receive, Scope, Send

from ..database import get_db
from ..models import Client, SharedSpace, SpaceDeviceGrant, Workspace
from ..security import client_from_token
from ..space import service
from ..space.schemas import SpaceEntryDetailOut, SpaceEntrySummaryOut, SpaceOut, valid_uuid


logger = logging.getLogger(__name__)


def _require_device_reads() -> None:
    if os.getenv("STUDIOLO_SPACE_DEVICE_READS", "0").strip().lower() not in ("1", "true", "yes"):
        raise HTTPException(404, "Not found")


router = APIRouter(
    prefix="/api/v1/client/space-reads",
    tags=["client-space-reads"],
    dependencies=[Depends(_require_device_reads)],
)


def _get_workspace(db: Session, client: Client) -> Workspace:
    workspace = db.get(Workspace, client.workspace_id)
    if workspace is None:
        logger.warning("Device space read rejected because the client workspace was not found")
        raise HTTPException(404, "Workspace not found")
    return workspace


def _granted_space_ids(db: Session, client: Client, workspace: Workspace) -> set[str]:
    explicit = select(SpaceDeviceGrant.space_id).where(
        SpaceDeviceGrant.workspace_id == workspace.id,
        SpaceDeviceGrant.client_id == client.id,
    )
    allowed = explicit.where(
        SpaceDeviceGrant.revoked_at.is_(None),
        SpaceDeviceGrant.can_read.is_(True),
    )
    granted = SharedSpace.id.in_(allowed)
    if service.device_default_grant_enabled():
        granted = or_(granted, and_(SharedSpace.user_id == workspace.owner_user_id, SharedSpace.id.not_in(explicit)))
    return set(db.scalars(select(SharedSpace.id).where(
        SharedSpace.workspace_id == workspace.id,
        SharedSpace.tier == "standard",
        SharedSpace.archived_at.is_(None),
        granted,
    )))


def _device_actor(client: Client, workspace: Workspace) -> service.SpaceActor:
    return service.SpaceActor(
        kind="device",
        workspace_id=client.workspace_id,
        user_id=workspace.owner_user_id,
        actor_id=f"client:{client.id}",
    )


def _space_read_actor(
    space_id: str, client: Client = Depends(client_from_token), db: Session = Depends(get_db),
) -> service.SpaceActor:
    workspace = _get_workspace(db, client)
    try:
        space_id = valid_uuid(space_id)
    except ValueError as exc:
        logger.info("Device space read rejected because the space ID was invalid")
        raise HTTPException(404, "Space not found") from exc
    found = db.scalar(select(SharedSpace.id).where(
        SharedSpace.workspace_id == workspace.id,
        SharedSpace.id == space_id,
    ))
    if found is None:
        logger.info("Device space read rejected because the space was not found in the client workspace")
        raise HTTPException(404, "Space not found")

    actor = _device_actor(client, workspace)
    granted = space_id in _granted_space_ids(db, client, workspace)
    service._record_audit(
        db,
        workspace_id=workspace.id,
        space_id=space_id,
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        action="device.read",
        outcome="allowed" if granted else "denied",
    )
    db.commit()
    if not granted:
        raise HTTPException(404, "Space not found")
    return actor


class _StatusOut(BaseModel):
    status: Literal["ready", "no_grant"]
    workspaceId: str
    spaceCount: int


class _StatusRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def probe(request: Request) -> Response:
            try:
                return await handler(request)
            except Exception as exc:
                if isinstance(exc, StarletteHTTPException) and exc.status_code != 500:
                    raise
                logger.error("Device space status probe failed")
                raise HTTPException(503, "Device space status unavailable") from None

        return probe


def get_status(client: Client = Depends(client_from_token), db: Session = Depends(get_db)) -> _StatusOut:
    service._require_enabled()
    workspace = _get_workspace(db, client)
    count = len(_granted_space_ids(db, client, workspace))
    if not count:
        logger.info("Device space status found no grants")
    return _StatusOut(status="ready" if count else "no_grant", workspaceId=workspace.id, spaceCount=count)


router.add_api_route("/status", get_status, methods=["GET"], route_class_override=_StatusRoute)


@router.get("/spaces", response_model=list[SpaceOut])
def list_spaces(client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    workspace = _get_workspace(db, client)
    return service.list_spaces(db, _device_actor(client, workspace), space_ids=_granted_space_ids(db, client, workspace))


@router.get("/spaces/{space_id}", response_model=SpaceOut)
def get_space(space_id: str, actor: service.SpaceActor = Depends(_space_read_actor), db: Session = Depends(get_db)):
    return service.get_space(db, actor, space_id)


@router.get("/spaces/{space_id}/entries", response_model=list[SpaceEntrySummaryOut])
def list_entries(
    space_id: str,
    search: str | None = Query(default=None, max_length=120),
    entry_type: str | None = Query(default=None, alias="entryType"),
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    actor: service.SpaceActor = Depends(_space_read_actor),
    db: Session = Depends(get_db),
):
    return service.list_entries(db, actor, space_id, search=search, entry_type=entry_type, limit=limit, offset=offset)


@router.get("/spaces/{space_id}/entries/{entry_id}", response_model=SpaceEntryDetailOut)
def get_entry(
    space_id: str, entry_id: str, actor: service.SpaceActor = Depends(_space_read_actor), db: Session = Depends(get_db),
):
    return service.get_entry(db, actor, space_id, entry_id)


class _EntryDownload(FileResponse):
    def __init__(self, data: bytes, mime: str, file_name: str):
        self._directory = TemporaryDirectory(prefix="studiolo-space-download-")
        path = Path(self._directory.name) / "entry"
        try:
            path.write_bytes(data)
            super().__init__(path, media_type=mime, headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}",
                "Cache-Control": "no-store",
            })
        except BaseException:
            self._directory.cleanup()
            raise

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._directory.cleanup()


@router.get("/spaces/{space_id}/entries/{entry_id}/download", response_class=FileResponse)
def download_entry(
    space_id: str, entry_id: str, actor: service.SpaceActor = Depends(_space_read_actor), db: Session = Depends(get_db),
) -> FileResponse:
    data, mime, file_name = service.download_entry_bytes(db, actor, space_id, entry_id)
    return _EntryDownload(data, mime, file_name)


@router.get("/spaces/{space_id}/blobs/{blob_id}/chunks/{chunk_index}")
def get_blob_chunk(
    space_id: str,
    blob_id: str,
    chunk_index: int,
    actor: service.SpaceActor = Depends(_space_read_actor),
    db: Session = Depends(get_db),
):
    data, digest = service.download_blob_chunk(db, actor, space_id, blob_id, chunk_index)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-Chunk-Sha256": digest, "Cache-Control": "no-store"},
    )
