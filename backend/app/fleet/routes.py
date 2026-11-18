"""Fleet 多设备控制节点管理、加密分块传输及双向 WebSocket 中继路由。"""

import asyncio
from contextlib import contextmanager
import hashlib
import secrets
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentNode, User, utcnow
from ..security import authenticate_node_token, authenticate_user_jwt, bearer, current_user
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace
from . import blobs
from .hub import ALLOWED_NODE_EVENTS, ConnectedNode, fleet_hub
from .schemas import (
    AdapterInfo,
    BlobCommitInput,
    BlobEndpointsOut,
    BlobInitInput,
    BlobOut,
    MAX_CHUNK_BYTES,
    NodeCreateInput,
    NodeHelloPayload,
    NodeOut,
    NodePatchInput,
    NodeTokenOut,
    TransferEndpoint,
    valid_uuid,
)

router = APIRouter(prefix="/api/v1/fleet", tags=["fleet"])
ws_router = APIRouter(tags=["fleet-ws"])


def _node_to_out(item: AgentNode, *, live_online: bool | None = None) -> NodeOut:
    status = "online" if live_online else ("revoked" if item.revoked_at is not None else item.runtime_status)
    return NodeOut(
        id=item.id,
        workspaceId=item.workspace_id,
        name=item.name,
        platform=item.platform,
        hostname=item.hostname,
        status=status,
        tokenLast4=item.token_last4,
        tokenCreatedAt=iso_utc(item.token_created_at) if item.token_created_at else None,
        revokedAt=iso_utc(item.revoked_at) if item.revoked_at else None,
        allowedRoots=list(item.allowed_roots_json or []),
        adapters=[AdapterInfo.model_validate(a) for a in (item.adapters_json or [])],
        transferEndpoints=[TransferEndpoint.model_validate(e) for e in (item.transfer_endpoints_json or [])],
        lastSeenAt=iso_utc(item.last_seen_at) if item.last_seen_at else None,
        createdAt=iso_utc(item.created_at),
        updatedAt=iso_utc(item.updated_at),
    )


def _owned_node(db: Session, workspace_id: str, node_id: str) -> AgentNode:
    try:
        valid_id = valid_uuid(node_id)
    except ValueError as exc:
        raise HTTPException(404, "Node not found") from exc
    node = db.scalar(select(AgentNode).where(AgentNode.id == valid_id, AgentNode.workspace_id == workspace_id))
    if node is None:
        raise HTTPException(404, "Node not found")
    return node


def _fleet_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> tuple[str, str, int, str]:
    """统一鉴权依赖：允许工作区内的用户 JWT 或有效 sn_live_ 节点凭证存取分块文件。"""
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    secret = credentials.credentials
    if secret.startswith("sn_live_"):
        node = authenticate_node_token(secret, db)
        if node is None:
            raise HTTPException(401, "Invalid node credential")
        return ("node", node.id, node.user_id, node.workspace_id)
    user = authenticate_user_jwt(secret, db)
    if user is None:
        raise HTTPException(401, "Invalid or expired token")
    workspace = get_personal_workspace(db, user)
    return ("user", str(user.id), user.id, workspace.id)


@router.get("/nodes", response_model=list[NodeOut])
async def list_nodes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    rows = db.scalars(
        select(AgentNode).where(AgentNode.workspace_id == workspace.id).order_by(AgentNode.created_at.desc())
    ).all()
    out: list[NodeOut] = []
    for item in rows:
        online = await fleet_hub.get_online_node(workspace.id, item.id)
        out.append(_node_to_out(item, live_online=online is not None))
    return out


@router.post("/nodes", status_code=201, response_model=NodeTokenOut)
def create_node(payload: NodeCreateInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    now = utcnow()
    plaintext = "sn_live_" + secrets.token_urlsafe(32)
    node = AgentNode(
        id=str(uuid4()),
        user_id=user.id,
        workspace_id=workspace.id,
        name=payload.name,
        platform=payload.platform,
        hostname=payload.hostname,
        token_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        token_last4=plaintext[-4:],
        token_created_at=now,
        runtime_status="offline",
        created_at=now,
        updated_at=now,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return NodeTokenOut(node=_node_to_out(node, live_online=False), nodeToken=plaintext)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: str,
    payload: NodePatchInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    workspace = get_personal_workspace(db, user)
    node = _owned_node(db, workspace.id, node_id)
    if payload.name is not None:
        node.name = payload.name
    if payload.platform is not None:
        node.platform = payload.platform
    if payload.hostname is not None:
        node.hostname = payload.hostname
    node.updated_at = utcnow()
    db.commit()
    db.refresh(node)
    online = await fleet_hub.get_online_node(workspace.id, node.id)
    return _node_to_out(node, live_online=online is not None)


@router.post("/nodes/{node_id}/token", response_model=NodeTokenOut)
async def rotate_node_token(node_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    node = _owned_node(db, workspace.id, node_id)
    await fleet_hub.kick_node(workspace.id, node.id, reason="token_rotated")
    plaintext = "sn_live_" + secrets.token_urlsafe(32)
    now = utcnow()
    node.token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    node.token_last4 = plaintext[-4:]
    node.token_created_at = now
    node.revoked_at = None
    node.runtime_status = "offline"
    node.updated_at = now
    db.commit()
    db.refresh(node)
    return NodeTokenOut(node=_node_to_out(node, live_online=False), nodeToken=plaintext)


@router.post("/nodes/{node_id}/revoke", response_model=NodeOut)
async def revoke_node_token(node_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    node = _owned_node(db, workspace.id, node_id)
    await fleet_hub.kick_node(workspace.id, node.id, reason="token_revoked")
    now = utcnow()
    node.token_hash = None
    node.token_last4 = None
    node.revoked_at = now
    node.runtime_status = "offline"
    node.updated_at = now
    db.commit()
    db.refresh(node)
    return _node_to_out(node, live_online=False)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    node = _owned_node(db, workspace.id, node_id)
    await fleet_hub.kick_node(workspace.id, node.id, reason="node_deleted")
    db.delete(node)
    db.commit()
    return Response(status_code=204)


# ---------------- 加密分块文件总线（/chat 附件与后续 Shared Space 共用） ----------------


@router.post("/artifacts/init", status_code=201, response_model=BlobEndpointsOut)
async def init_artifact(
    payload: BlobInitInput,
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    actor_kind, actor_id, user_id, workspace_id = actor
    blob = blobs.init_blob(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        uploader_kind=actor_kind,
        uploader_id=actor_id,
        payload=payload,
    )
    return BlobEndpointsOut(
        blob=blobs.blob_to_out(blob),
        endpoints=blobs.build_resolved_endpoints(blob, actor_id=actor_id),
    )


@router.put("/artifacts/{artifact_id}/chunks/{index}")
async def upload_artifact_chunk(
    artifact_id: str,
    index: int,
    request: Request,
    x_chunk_sha256: str | None = Header(default=None),
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, _, _, workspace_id = actor
    blob = blobs.get_workspace_blob(db, workspace_id, artifact_id)
    raw = await request.body()
    if len(raw) > MAX_CHUNK_BYTES:
        raise HTTPException(413, "Chunk exceeds maximum limit")
    written = blobs.store_chunk(blob, index, raw, expected_sha256=x_chunk_sha256)
    return {"artifactId": blob.id, "chunkIndex": index, "bytesWritten": written}


@router.post("/artifacts/{artifact_id}/commit", response_model=BlobOut)
def commit_artifact(
    artifact_id: str,
    payload: BlobCommitInput | None = None,
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, _, _, workspace_id = actor
    blob = blobs.get_workspace_blob(db, workspace_id, artifact_id)
    committed = blobs.commit_blob(db, blob, payload)
    return blobs.blob_to_out(committed)


@router.get("/artifacts/{artifact_id}", response_model=BlobOut)
def get_artifact(
    artifact_id: str,
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, _, _, workspace_id = actor
    return blobs.blob_to_out(blobs.get_workspace_blob(db, workspace_id, artifact_id))


@router.get("/artifacts/{artifact_id}/endpoints", response_model=BlobEndpointsOut)
async def get_artifact_endpoints(
    artifact_id: str,
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, actor_id, _, workspace_id = actor
    blob = blobs.get_workspace_blob(db, workspace_id, artifact_id)
    peer_eps: list[TransferEndpoint] = []
    if blob.uploader_kind == "node":
        online = await fleet_hub.get_online_node(workspace_id, blob.uploader_id)
        if online is not None:
            peer_eps = [TransferEndpoint.model_validate(ep) for ep in online.transfer_endpoints]
    return BlobEndpointsOut(
        blob=blobs.blob_to_out(blob),
        endpoints=blobs.build_resolved_endpoints(blob, actor_id=actor_id, peer_endpoints=peer_eps),
    )


@router.get("/artifacts/{artifact_id}/chunks/{index}")
def download_artifact_chunk(
    artifact_id: str,
    index: int,
    range_header: str | None = Header(default=None, alias="Range"),
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, _, _, workspace_id = actor
    blob = blobs.get_workspace_blob(db, workspace_id, artifact_id)
    return blobs.stream_chunk_response(blob, index, range_header=range_header)


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(
    artifact_id: str,
    actor: tuple[str, str, int, str] = Depends(_fleet_actor),
    db: Session = Depends(get_db),
):
    _, _, _, workspace_id = actor
    blob = blobs.get_workspace_blob(db, workspace_id, artifact_id)
    blobs.delete_blob(db, blob)
    return Response(status_code=204)


# ---------------- WebSocket 实时控制面中继（零聊天正文持久化） ----------------


@contextmanager
def _open_ws_db(websocket: WebSocket):
    """按请求获取短生命周期数据库会话，兼容 dependency_overrides[get_db] 并避免阻塞连接池。"""
    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    try:
        yield db
    finally:
        gen.close()


async def _recv_first_auth_frame(websocket: WebSocket) -> dict[str, Any] | None:
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
    except Exception:
        return None
    if not isinstance(frame, dict) or frame.get("type") != "auth":
        return None
    return frame


@ws_router.websocket("/ws/fleet/node")
async def fleet_node_ws(websocket: WebSocket):
    """AgentNode 反向认证长连入口（禁止在 Query 参数中传 Token）。"""
    if websocket.query_params.get("token"):
        await websocket.close(code=4401, reason="Token must not be passed in URL query")
        return

    await websocket.accept()
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    hello_raw: dict[str, Any] = {}
    if not token:
        frame = await _recv_first_auth_frame(websocket)
        if frame is None:
            await websocket.close(code=4401, reason="Missing auth frame")
            return
        token = str(frame.get("token") or "")
        if isinstance(frame.get("hello"), dict):
            hello_raw = frame["hello"]

    try:
        hello = NodeHelloPayload.model_validate(hello_raw)
    except ValidationError:
        await websocket.close(code=4400, reason="Invalid node hello metadata")
        return

    with _open_ws_db(websocket) as db:
        node = authenticate_node_token(token, db)
        if node is None:
            await websocket.close(code=4401, reason="Invalid node credential")
            return
        now = utcnow()
        if hello.hostname is not None:
            node.hostname = hello.hostname
        if hello.platform is not None:
            node.platform = hello.platform
        if hello.allowedRoots:
            node.allowed_roots_json = hello.allowedRoots
        if hello.adapters:
            node.adapters_json = [item.model_dump(mode="json") for item in hello.adapters]
        if hello.transferEndpoints:
            node.transfer_endpoints_json = [item.model_dump(mode="json") for item in hello.transferEndpoints]
        node.runtime_status = "online"
        node.last_seen_at = now
        node.updated_at = now
        db.commit()
        node_id = node.id
        workspace_id = node.workspace_id
        user_id = node.user_id
        node_name = node.name
        node_platform = node.platform
        adapters = list(node.adapters_json or [])
        roots = list(node.allowed_roots_json or [])
        endpoints = list(node.transfer_endpoints_json or [])

    conn = ConnectedNode(
        node_id=node_id,
        workspace_id=workspace_id,
        user_id=user_id,
        name=node_name,
        platform=node_platform,
        websocket=websocket,
        adapters=adapters,
        allowed_roots=roots,
        transfer_endpoints=endpoints,
    )
    await fleet_hub.register_node(conn)
    await websocket.send_json({"type": "NodeReady", "nodeId": node_id, "workspaceId": workspace_id})

    try:
        while True:
            frame = await websocket.receive_json()
            if not isinstance(frame, dict):
                continue
            evt_type = str(frame.get("type") or "")
            if evt_type not in ALLOWED_NODE_EVENTS:
                continue
            if evt_type == "NodeHeartbeat":
                with _open_ws_db(websocket) as db:
                    item = db.get(AgentNode, node_id)
                    if item is None or item.revoked_at is not None:
                        await websocket.close(code=4401, reason="Credential revoked")
                        break
                    item.last_seen_at = utcnow()
                    if isinstance(frame.get("adapters"), list):
                        validated = [AdapterInfo.model_validate(a).model_dump(mode="json") for a in frame["adapters"]]
                        item.adapters_json = validated
                        conn.adapters = validated
                    if isinstance(frame.get("transferEndpoints"), list):
                        validated_ep = [TransferEndpoint.model_validate(e).model_dump(mode="json") for e in frame["transferEndpoints"]]
                        item.transfer_endpoints_json = validated_ep
                        conn.transfer_endpoints = validated_ep
                    db.commit()
                continue

            target_client_id = frame.pop("_clientConnId", None)
            outbound = {**frame, "nodeId": node_id}
            await fleet_hub.broadcast_workspace(
                workspace_id,
                outbound,
                target_client_id=target_client_id if evt_type in ("SessionsSnapshot", "SessionHistory", "ModelsSnapshot") else None,
            )
    except WebSocketDisconnect:
        pass
    finally:
        await fleet_hub.unregister_node(workspace_id, node_id, websocket)
        with _open_ws_db(websocket) as db:
            item = db.get(AgentNode, node_id)
            if item is not None:
                item.runtime_status = "offline"
                item.updated_at = utcnow()
                db.commit()


@ws_router.websocket("/ws/fleet/client")
async def fleet_client_ws(websocket: WebSocket):
    """桌面端/移动端浏览器 Fleet 控制台双向 WS（首帧 JWT 鉴权）。"""
    if websocket.query_params.get("token"):
        await websocket.close(code=4401, reason="Token must not be passed in URL query")
        return

    await websocket.accept()
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        frame = await _recv_first_auth_frame(websocket)
        if frame is None:
            await websocket.close(code=4401, reason="Missing auth frame")
            return
        token = str(frame.get("token") or "")

    with _open_ws_db(websocket) as db:
        user = authenticate_user_jwt(token, db)
        if user is None:
            await websocket.close(code=4401, reason="Invalid or expired token")
            return
        workspace_id = get_personal_workspace(db, user).id

    conn_id = await fleet_hub.register_client(workspace_id, websocket)
    try:
        while True:
            frame = await websocket.receive_json()
            if not isinstance(frame, dict):
                continue
            error_reply = await fleet_hub.forward_client_command(workspace_id, conn_id, frame)
            if error_reply is not None:
                await websocket.send_json(error_reply)
    except WebSocketDisconnect:
        pass
    finally:
        await fleet_hub.unregister_client(workspace_id, conn_id)
