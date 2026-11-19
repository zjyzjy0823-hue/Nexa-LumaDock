"""Shared Space 三档分级（standard / protected / e2ee）端到端集成与安全隔离矩阵测试。"""

from __future__ import annotations

import base64
from pathlib import Path
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect

from app.space import crypto


MASTER_KEY = "studiolo-test-vault-master-key-32-bytes-minimum!!"


@pytest.fixture(autouse=True)
def _space_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIOLO_SHARED_SPACE_ENABLED", "true")
    monkeypatch.setenv("STUDIOLO_SPACE_BLOB_DIR", str(tmp_path / "space-blobs"))
    monkeypatch.setenv("STUDIOLO_VAULT_MASTER_KEY", MASTER_KEY)
    yield


def _create_agent_with_scopes(client, headers, scopes: list[str]) -> dict[str, str]:
    res = client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "space-test-agent", "provider": "openclaw", "enabled": True, "dataScopes": scopes},
    )
    assert res.status_code == 201, res.text
    agent_id = res.json()["id"]
    tk_res = client.post(f"/api/v1/agents/{agent_id}/token", headers=headers)
    assert tk_res.status_code == 201, tk_res.text
    return {"Authorization": f"Bearer {tk_res.json()['token']}"}


def test_alembic_0021_shared_space_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.database.DATABASE_URL", db_url)
    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
        for expected in (
            "shared_spaces",
            "space_device_grants",
            "space_key_envelopes",
            "space_entries",
            "space_blobs",
            "space_entry_revisions",
            "space_tokens",
            "space_access_audit_logs",
            "space_changes",
            "space_mutation_receipts",
        ):
            assert expected in tables

        command.downgrade(cfg, "0020_fleet_nodes_and_blobs")
        tables_after = set(inspect(engine).get_table_names())
        assert "shared_spaces" not in tables_after
        assert "agent_nodes" in tables_after
    finally:
        engine.dispose()


def test_standard_tier_direct_read_token_scopes_and_agent_whitelist(client, users):
    owner_a, owner_b = users

    # 1. 创建普通共享空间与文本/文件条目
    sp_res = client.post(
        "/api/v1/spaces",
        headers=owner_a,
        json={"name": "团队笔记", "description": "日常普通文档", "tier": "standard"},
    )
    assert sp_res.status_code == 201, sp_res.text
    space = sp_res.json()
    space_id = space["id"]

    note_res = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={
            "entryType": "text",
            "title": "部署备忘",
            "tags": ["ops", "mac"],
            "contentText": "Mac Core 地址：https://core.example",
        },
    )
    assert note_res.status_code == 201, note_res.text
    note = note_res.json()
    assert note["locked"] is False
    assert note["contentText"] == "Mac Core 地址：https://core.example"

    raw_file = b"\x89PNG\r\n\x1a\nfake-image-payload"
    file_res = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={
            "entryType": "file",
            "title": "架构草图",
            "fileName": "arch.png",
            "mime": "image/png",
            "contentBase64": base64.b64encode(raw_file).decode("ascii"),
        },
    )
    assert file_res.status_code == 201
    file_entry_id = file_res.json()["id"]

    # UI / JWT 随时查看与下载
    dl = client.get(f"/api/v1/spaces/{space_id}/entries/{file_entry_id}/download", headers=owner_a)
    assert dl.status_code == 200
    assert dl.content == raw_file

    # 2. 签发普通只读 Space API Token（ss_live_）
    tk_res = client.post(
        f"/api/v1/spaces/{space_id}/tokens",
        headers=owner_a,
        json={"name": "readonly-script", "scopes": ["read"]},
    )
    assert tk_res.status_code == 201
    raw_ss_token = tk_res.json()["token"]
    assert raw_ss_token.startswith("ss_live_")
    ss_headers = {"Authorization": f"Bearer {raw_ss_token}"}

    # 只读 Token 可直接读取与下载，不可写入
    got = client.get(f"/api/v1/spaces/{space_id}/entries/{note['id']}", headers=ss_headers)
    assert got.status_code == 200
    assert got.json()["contentText"] == "Mac Core 地址：https://core.example"

    denied_write = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=ss_headers,
        json={"entryType": "text", "title": "越权写", "contentText": "nope"},
    )
    assert denied_write.status_code == 403

    # 3. 跨工作区隔离（owner_b 404）
    assert client.get(f"/api/v1/spaces/{space_id}", headers=owner_b).status_code == 404

    # 4. Agent Data Actions 白名单：无 space:read 拒绝；开启 space:read 可只读 standard
    agent_no_scope = _create_agent_with_scopes(client, owner_a, ["ledger:read"])
    r_denied = client.post(
        "/api/agent/actions/execute",
        headers=agent_no_scope,
        json={"action": "space.list", "arguments": {}},
    )
    assert r_denied.status_code == 403

    agent_with_scope = _create_agent_with_scopes(client, owner_a, ["space:read"])
    r_list = client.post(
        "/api/agent/actions/execute",
        headers=agent_with_scope,
        json={"action": "space.list", "arguments": {}},
    )
    assert r_list.status_code == 200, r_list.text
    assert [sp["id"] for sp in r_list.json()["data"]] == [space_id]

    r_get = client.post(
        "/api/agent/actions/execute",
        headers=agent_with_scope,
        json={"action": "space.entry.get", "arguments": {"spaceId": space_id, "id": note["id"]}},
    )
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["data"]["contentText"] == "Mac Core 地址：https://core.example"

    # 5. 吊销 ss_live_ 后立即失效
    assert client.delete(f"/api/v1/spaces/{space_id}/tokens/{tk_res.json()['id']}", headers=owner_a).status_code == 204
    assert client.get(f"/api/v1/spaces/{space_id}/entries/{note['id']}", headers=ss_headers).status_code == 401


def test_protected_tier_password_gate_fine_grained_vault_token_and_sentinel(client, users, tmp_path, monkeypatch):
    owner_a, _owner_b = users
    sentinel_a = "SENTINEL_PROTECTED_OPENAI_SK_987654321"
    sentinel_b = "SENTINEL_PROTECTED_DB_PASS_123456789"
    space_pwd = "Vault-Passphrase#2026"

    # 未配置 Master Key 时明确拒绝创建 protected 空间
    monkeypatch.setenv("STUDIOLO_VAULT_MASTER_KEY", "")
    r_unavail = client.post(
        "/api/v1/spaces",
        headers=owner_a,
        json={"name": "机密密钥库", "tier": "protected", "password": space_pwd},
    )
    assert r_unavail.status_code == 503
    monkeypatch.setenv("STUDIOLO_VAULT_MASTER_KEY", MASTER_KEY)

    sp_res = client.post(
        "/api/v1/spaces",
        headers=owner_a,
        json={"name": "机密密钥库", "tier": "protected", "password": space_pwd},
    )
    assert sp_res.status_code == 201, sp_res.text
    space_id = sp_res.json()["id"]

    # 创建两条受控机密条目（必须提交当次空间密码）
    bad_create = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={"entryType": "key", "title": "OpenAI Key", "contentText": sentinel_a, "password": "wrong-password"},
    )
    assert bad_create.status_code == 403

    e1 = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={"entryType": "key", "title": "OpenAI Key", "contentText": sentinel_a, "password": space_pwd},
    ).json()
    e2 = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={"entryType": "key", "title": "DB Password", "contentText": sentinel_b, "password": space_pwd},
    ).json()

    # 普通 JWT GET 绝不返回明文
    locked_get = client.get(f"/api/v1/spaces/{space_id}/entries/{e1['id']}", headers=owner_a)
    assert locked_get.status_code == 200
    assert locked_get.json()["locked"] is True
    assert locked_get.json()["contentText"] is None

    # UI 端 POST /unlock 错密拒绝、正密返回明文
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/entries/{e1['id']}/unlock",
            headers=owner_a,
            json={"password": "wrong-password"},
        ).status_code
        == 403
    )
    unlocked = client.post(
        f"/api/v1/spaces/{space_id}/entries/{e1['id']}/unlock",
        headers=owner_a,
        json={"password": space_pwd},
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["locked"] is False
    assert unlocked.json()["contentText"] == sentinel_a

    # 磁盘分块文件绝不落明文哨兵
    for fpath in (tmp_path / "space-blobs").rglob("*.bin"):
        raw_disk = fpath.read_bytes()
        assert sentinel_a.encode() not in raw_disk
        assert sentinel_b.encode() not in raw_disk

    # 签发仅绑定 e1 的细粒度 sv_live_ Vault Token
    sv_res = client.post(
        f"/api/v1/spaces/{space_id}/tokens",
        headers=owner_a,
        json={
            "name": "ci-openai-reader",
            "scopes": ["read"],
            "entryIds": [e1["id"]],
            "password": space_pwd,
        },
    )
    assert sv_res.status_code == 201, sv_res.text
    sv_token = sv_res.json()["token"]
    assert sv_token.startswith("sv_live_")
    sv_headers = {"Authorization": f"Bearer {sv_token}"}

    # sv_live_ 可直读 e1，但禁止读 e2（条目白名单隔离）
    sv_e1 = client.get(f"/api/v1/spaces/{space_id}/entries/{e1['id']}", headers=sv_headers)
    assert sv_e1.status_code == 200
    assert sv_e1.json()["contentText"] == sentinel_a
    assert client.get(f"/api/v1/spaces/{space_id}/entries/{e2['id']}", headers=sv_headers).status_code == 403

    # sv_live_ 不可访问普通空间；普通 ss_live_ 不可访问 protected 空间
    std_sp = client.post("/api/v1/spaces", headers=owner_a, json={"name": "普通", "tier": "standard"}).json()
    std_tk = client.post(
        f"/api/v1/spaces/{std_sp['id']}/tokens",
        headers=owner_a,
        json={"name": "std-tk", "scopes": ["read"]},
    ).json()["token"]
    assert client.get(f"/api/v1/spaces/{std_sp['id']}/entries", headers=sv_headers).status_code == 403
    assert client.get(f"/api/v1/spaces/{space_id}/entries", headers={"Authorization": f"Bearer {std_tk}"}).status_code == 403

    # Agent 即便开启 space:read 也严禁看到或读取 protected 空间
    agent_headers = _create_agent_with_scopes(client, owner_a, ["space:read"])
    ag_list = client.post("/api/agent/actions/execute", headers=agent_headers, json={"action": "space.list", "arguments": {}})
    assert ag_list.status_code == 200
    assert all(sp["id"] != space_id for sp in ag_list.json()["data"])
    ag_read = client.post(
        "/api/agent/actions/execute",
        headers=agent_headers,
        json={"action": "space.entry.get", "arguments": {"spaceId": space_id, "id": e1["id"]}},
    )
    assert ag_read.status_code == 403

    # 修改空间密码后旧密失效、新密生效
    new_pwd = "New-Vault-Passphrase#2026"
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/change-password",
            headers=owner_a,
            json={"oldPassword": space_pwd, "newPassword": new_pwd},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/entries/{e1['id']}/unlock",
            headers=owner_a,
            json={"password": space_pwd},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/entries/{e1['id']}/unlock",
            headers=owner_a,
            json={"password": new_pwd},
        ).status_code
        == 200
    )

    # 审计日志完整且绝不泄露密码或明文哨兵
    logs = client.get(f"/api/v1/spaces/{space_id}/audit-logs", headers=owner_a).json()
    actions = {(l["action"], l["outcome"]) for l in logs}
    assert ("entry.vault_read", "allowed") in actions
    assert ("entry.unlock", "denied") in actions
    assert ("entry.unlock", "allowed") in actions
    serialized_logs = str(logs)
    assert sentinel_a not in serialized_logs
    assert space_pwd not in serialized_logs
    assert new_pwd not in serialized_logs


def test_e2ee_tier_zero_knowledge_cas_epoch_rotation_and_changes(client, users, tmp_path):
    owner_a, owner_b = users
    ws_id = client.get("/api/v1/workspace", headers=owner_a).json()["id"]
    sentinel = "SENTINEL_E2EE_ROOT_SEED_PHRASE_XYZ"

    # 客户端预生成真实 space_id，直接以最终 AAD 绑定生成初始 epoch=1 KeyEnvelope
    client_space_id = str(uuid4())
    space_key_v1 = secrets.token_bytes(32)
    env_v1 = crypto.wrap_space_key(
        password="E2EE-Strong-Password!1",
        space_key=space_key_v1,
        workspace_id=ws_id,
        space_id=client_space_id,
        epoch=1,
    )
    sp_res = client.post(
        "/api/v1/spaces",
        headers=owner_a,
        json={"id": client_space_id, "name": "极密私钥库", "tier": "e2ee", "envelope": env_v1},
    )
    assert sp_res.status_code == 201, sp_res.text
    space_id = sp_res.json()["id"]
    assert space_id == client_space_id

    # e2ee 禁止签发 API Token
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/tokens",
            headers=owner_a,
            json={"name": "forbidden", "scopes": ["read"]},
        ).status_code
        == 400
    )

    # 客户端用实际 space_id 常规改密 CAS 重包封套
    env_v1_bound = crypto.wrap_space_key(
        password="E2EE-Strong-Password!1",
        space_key=space_key_v1,
        workspace_id=ws_id,
        space_id=space_id,
        epoch=1,
    )
    rewrap_ok = client.put(
        f"/api/v1/spaces/{space_id}/envelope",
        headers=owner_a,
        json={"expectedEnvelopeVersion": 1, "envelope": env_v1_bound},
    )
    assert rewrap_ok.status_code == 200
    assert rewrap_ok.json()["envelopeVersion"] == 2

    # 陈旧 envelopeVersion CAS 冲突返回 409
    assert (
        client.put(
            f"/api/v1/spaces/{space_id}/envelope",
            headers=owner_a,
            json={"expectedEnvelopeVersion": 1, "envelope": env_v1_bound},
        ).status_code
        == 409
    )

    # 分块上传客户端预加密密文（客户端预生成真实 entry_id 绑定 AAD；验证 SHA-256 错校验返回 400）
    client_entry_id = str(uuid4())
    dek = secrets.token_bytes(32)
    ct_chunk0 = crypto.encrypt_chunk(
        dek=dek,
        plaintext=sentinel.encode("utf-8"),
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=client_entry_id,
        revision=1,
        chunk_index=0,
        epoch=1,
    )
    blob = client.post(
        f"/api/v1/spaces/{space_id}/blobs/init",
        headers=owner_a,
        json={"chunkSize": 2 * 1024 * 1024, "chunkCount": 1, "totalSize": len(ct_chunk0)},
    ).json()
    bad_put = client.put(
        f"/api/v1/spaces/{space_id}/blobs/{blob['id']}/chunks/0",
        headers={**owner_a, "X-Chunk-Sha256": "0" * 64},
        content=ct_chunk0,
    )
    assert bad_put.status_code == 400

    good_put = client.put(
        f"/api/v1/spaces/{space_id}/blobs/{blob['id']}/chunks/0",
        headers={**owner_a, "X-Chunk-Sha256": crypto.sha256_hex(ct_chunk0)},
        content=ct_chunk0,
    )
    assert good_put.status_code == 200

    wrapped_dek = crypto.wrap_dek(
        wrapping_key=space_key_v1,
        dek=dek,
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=client_entry_id,
        revision=1,
        epoch=1,
    )
    enc_manifest = crypto.encrypt_manifest(
        dek=dek,
        manifest={
            "version": 1,
            "entryType": "key",
            "title": "Cold Wallet Seed",
            "mime": "text/plain",
            "sizeBytes": len(sentinel),
            "chunkCount": 1,
            "chunkSize": 2 * 1024 * 1024,
            "plaintextSha256": crypto.sha256_hex(sentinel.encode("utf-8")),
        },
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=client_entry_id,
        revision=1,
        epoch=1,
    )

    # 拒绝向 e2ee 传入明文 title/contentText
    assert (
        client.post(
            f"/api/v1/spaces/{space_id}/entries",
            headers=owner_a,
            json={
                "id": client_entry_id,
                "entryType": "key",
                "title": "leaked-title",
                "epoch": 1,
                "wrappedDek": wrapped_dek,
                "encryptedManifestB64": enc_manifest,
                "blobId": blob["id"],
            },
        ).status_code
        == 422
    )

    # 正常创建（带 mutationId 幂等回执）
    create_payload = {
        "id": client_entry_id,
        "entryType": "key",
        "mutationId": "mut-e2ee-001",
        "epoch": 1,
        "wrappedDek": wrapped_dek,
        "encryptedManifestB64": enc_manifest,
        "blobId": blob["id"],
        "plaintextSize": len(sentinel),
        "contentSha256": crypto.sha256_hex(ct_chunk0),
    }
    e_res1 = client.post(f"/api/v1/spaces/{space_id}/entries", headers=owner_a, json=create_payload)
    assert e_res1.status_code == 201, e_res1.text
    e_res2 = client.post(f"/api/v1/spaces/{space_id}/entries", headers=owner_a, json=create_payload)
    assert e_res2.status_code == 201
    assert e_res2.json()["id"] == client_entry_id
    entry_id = e_res1.json()["id"]

    # 客户端完整拉回密文块 + 封套，用当次输入密码本地解密还原明文
    fetched_env = client.get(f"/api/v1/spaces/{space_id}/envelope", headers=owner_a).json()["envelope"]
    fetched_entry = client.get(f"/api/v1/spaces/{space_id}/entries/{entry_id}", headers=owner_a).json()
    fetched_chunk = client.get(f"/api/v1/spaces/{space_id}/blobs/{fetched_entry['blobId']}/chunks/0", headers=owner_a).content
    recovered_space_key = crypto.unwrap_space_key(
        password="E2EE-Strong-Password!1", envelope=fetched_env, workspace_id=ws_id, space_id=space_id
    )
    recovered_dek = crypto.unwrap_dek(
        wrapping_key=recovered_space_key,
        wrapped_dek=fetched_entry["wrappedDek"],
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=1,
    )
    recovered_manifest = crypto.decrypt_manifest(
        dek=recovered_dek,
        encrypted_manifest_b64=fetched_entry["encryptedManifestB64"],
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=1,
    )
    assert recovered_manifest["title"] == "Cold Wallet Seed"
    recovered_pt = crypto.decrypt_chunk(
        dek=recovered_dek,
        ciphertext_chunk=fetched_chunk,
        workspace_id=ws_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=1,
        chunk_index=0,
    )
    assert recovered_pt.decode("utf-8") == sentinel

    # 磁盘零明文哨兵
    for fpath in (tmp_path / "space-blobs").rglob("*.bin"):
        assert sentinel.encode() not in fpath.read_bytes()

    # CAS 冲突：baseRevision=99 默认 409，allowConflictFork=True 保留冲突修订
    assert (
        client.put(
            f"/api/v1/spaces/{space_id}/entries/{entry_id}",
            headers=owner_a,
            json={
                "baseRevision": 99,
                "epoch": 1,
                "wrappedDek": wrapped_dek,
                "encryptedManifestB64": enc_manifest,
            },
        ).status_code
        == 409
    )
    fork_res = client.put(
        f"/api/v1/spaces/{space_id}/entries/{entry_id}",
        headers=owner_a,
        json={
            "baseRevision": 99,
            "allowConflictFork": True,
            "epoch": 1,
            "wrappedDek": wrapped_dek,
            "encryptedManifestB64": enc_manifest,
        },
    )
    assert fork_res.status_code == 200
    assert 2 in fork_res.json()["conflictRevisions"]

    # 泄露轮换 epoch 1 -> 2，随后旧 epoch=1 写入必须被 409 拒绝
    space_key_v2 = secrets.token_bytes(32)
    env_v2 = crypto.wrap_space_key(
        password="E2EE-Rotated-Password!2",
        space_key=space_key_v2,
        workspace_id=ws_id,
        space_id=space_id,
        epoch=2,
    )
    rot_res = client.post(
        f"/api/v1/spaces/{space_id}/rotate-epoch",
        headers=owner_a,
        json={"expectedActiveEpoch": 1, "envelope": env_v2},
    )
    assert rot_res.status_code == 200
    assert rot_res.json()["epoch"] == 2

    stale_write = client.post(
        f"/api/v1/spaces/{space_id}/entries",
        headers=owner_a,
        json={
            "entryType": "text",
            "epoch": 1,
            "wrappedDek": wrapped_dek,
            "encryptedManifestB64": enc_manifest,
        },
    )
    assert stale_write.status_code == 409

    # 隔离增量游标拉取
    changes = client.get(f"/api/v1/spaces/{space_id}/changes?sinceSeq=0&limit=10", headers=owner_a)
    assert changes.status_code == 200
    body = changes.json()
    assert body["activeEpoch"] == 2
    assert any(c["changeType"] == "epoch_rotated" for c in body["changes"])

    # 跨工作区访问 404
    assert client.get(f"/api/v1/spaces/{space_id}/envelope", headers=owner_b).status_code == 404
