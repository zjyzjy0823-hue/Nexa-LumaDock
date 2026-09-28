from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import load_runtime_config


runtime_config = load_runtime_config()
DATABASE_URL = runtime_config.database_url
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if runtime_config.mode == "local" else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        yield db
