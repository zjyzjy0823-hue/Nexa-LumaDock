"""测试公用小工具。"""
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_head() -> str:
    """当前迁移链的 head，用 alembic 自己的 ScriptDirectory 算出来。

    测试以前把 ``0020_fleet_nodes_and_blobs`` 写死在这些断言里，于是每加一个迁移
    （0023 space_sync_candidates）就有 11 个升级测试一起变红——迁移其实没问题，
    只是断言没跟上。现在统一从这里取 head，加迁移不用再改测试。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()
