"""Run `python -m app.create_admin` to create the first local account."""
from getpass import getpass
from alembic import command
from alembic.config import Config
from pathlib import Path
from uuid import uuid4
from sqlalchemy import func, select

from .database import SessionLocal
from .models import User
from .security import hash_password


def main():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(config, "head")
    username = input("Username: ").strip()
    password = getpass("Password (8+ characters): ")
    if len(username) < 3 or len(password) < 8:
        raise SystemExit("Invalid username or password")
    with SessionLocal() as db:
        if db.scalar(select(User).where(func.lower(User.username) == username.lower())):
            raise SystemExit("Username already exists")
        db.add(User(username=username, email=f"{uuid4().hex}@nexa.local", password_hash=hash_password(password)))
        db.commit()
    print("Account created.")


if __name__ == "__main__":
    main()
