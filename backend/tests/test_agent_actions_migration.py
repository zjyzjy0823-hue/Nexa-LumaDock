import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from sqlalchemy import create_engine, text, inspect


def test_0014_upgrade_preserves_data_defaults_and_downgrade(tmp_path):
    database = "sqlite:///" + (tmp_path / "upgrade.db").as_posix()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": database}

    def migrate(direction, revision):
        subprocess.run(
            [sys.executable, "-m", "alembic", direction, revision],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "0014_multi_entity_sync")
    engine = create_engine(database)
    ids = [str(uuid4()) for _ in range(7)]
    workspace, agent, category, transaction, collection, record, website = ids
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, created_at, updated_at) VALUES (1,'upgrade','upgrade@test','hash',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO workspaces (id,owner_user_id,name,kind,created_at,updated_at) VALUES (:id,1,'Personal','personal',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": workspace},
        )
        db.execute(
            text(
                "INSERT INTO agents (id,user_id,workspace_id,name,role,description,model,workspace,avatar,enabled,runtime_status,created_at,updated_at) VALUES (:id,1,:w,'Agent','','','','','spark',1,'idle',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": agent, "w": workspace},
        )
        db.execute(
            text(
                "INSERT INTO ledger_categories (id,user_id,workspace_id,name,type,icon,created_at) VALUES (:id,1,:w,'Food','expense','shopping',CURRENT_TIMESTAMP)"
            ),
            {"id": category, "w": workspace},
        )
        db.execute(
            text(
                "INSERT INTO ledger_transactions (id,user_id,workspace_id,category_id,type,amount,description,occurred_at,merchant,note,created_at,updated_at) VALUES (:id,1,:w,:category,'expense',38,'Coffee',CURRENT_TIMESTAMP,'','',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": transaction, "w": workspace, "category": category},
        )
        db.execute(
            text(
                "INSERT INTO websites (id,user_id,workspace_id,name,url,favorite,\"order\",created_at,updated_at) VALUES (:id,1,:w,'Example','https://example.com',0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": website, "w": workspace},
        )
        db.execute(
            text(
                "INSERT INTO data_collections (id,user_id,workspace_id,name,description,icon,tone,created_at,updated_at) VALUES (:id,1,:w,'Servers','','custom','blue',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": collection, "w": workspace},
        )
        db.execute(
            text(
                "INSERT INTO data_records (id,collection_id,name,status,category,data_json,created_at,updated_at) VALUES (:id,:c,'Mac mini','active','','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": record, "c": collection},
        )
    tables = [
        "agents",
        "ledger_categories",
        "ledger_transactions",
        "websites",
        "data_collections",
        "data_records",
        "local_mutation_queue",
    ]
    with engine.connect() as db:
        before = {
            table: db.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
            for table in tables
        }
    migrate("upgrade", "head")
    with engine.connect() as db:
        assert json.loads(db.scalar(text("SELECT data_scopes FROM agents"))) == []
        assert "agent_action_logs" in inspect(db).get_table_names()
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version"))
            == "0017_automation_engine"
        )
        for table in tables:
            after = db.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
            assert [
                {k: row[k] for k in old} for row, old in zip(after, before[table])
            ] == before[table]
    migrate("downgrade", "0014_multi_entity_sync")
    with engine.connect() as db:
        assert "data_scopes" not in {
            c["name"] for c in inspect(db).get_columns("agents")
        }
        assert "agent_action_logs" not in inspect(db).get_table_names()
        assert db.scalar(text("SELECT amount FROM ledger_transactions")) == 38
    migrate("upgrade", "head")
    engine.dispose()
