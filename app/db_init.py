from sqlalchemy import inspect, text

from app.config import settings
from app.database import SessionLocal, engine
from app.models import User


def init_db() -> None:
    from app.database import Base

    Base.metadata.create_all(bind=engine)
    _migrate_add_is_admin()
    _migrate_add_rag_indexed()
    _migrate_add_email_verified()
    _migrate_add_chat_folder_id()
    _promote_configured_admin_on_startup()


def _migrate_add_chat_folder_id() -> None:
    inspector = inspect(engine)
    if "chats" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("chats")}
    if "folder_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chats ADD COLUMN folder_id INTEGER"))


def _migrate_add_is_admin() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "is_admin" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))


def _migrate_add_rag_indexed() -> None:
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("messages")}
    if "rag_indexed" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE messages ADD COLUMN rag_indexed BOOLEAN NOT NULL DEFAULT 0"))


def _migrate_add_email_verified() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "email_verified" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"))


def _promote_configured_admin_on_startup() -> None:
    if not settings.admin_email:
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == settings.admin_email).first()
        if user and not user.is_admin:
            user.is_admin = True
            db.commit()
    finally:
        db.close()


def maybe_promote_admin(user: User, db) -> None:
    if settings.admin_email and user.email == settings.admin_email:
        changed = False
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if not user.email_verified:
            user.email_verified = True
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
