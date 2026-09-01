"""SQLAlchemy engine, session factory, and schema initialization."""

import logging
import os
from typing import Generator
from urllib.parse import quote_plus
from uuid import uuid4, uuid5, NAMESPACE_URL

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()


def _database_url() -> str:
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "zrdds")
    user = quote_plus(os.getenv("DB_USER", "root"))
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


DATABASE_URL = _database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()
logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all application tables if they do not already exist."""
    from app.models import Conversation, Message, User  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_legacy_schema()
    _ensure_conversation_user_foreign_key()


def _migrate_legacy_schema() -> None:
    """Add A-line columns missing from databases created by older versions."""
    inspector = inspect(engine)
    with engine.begin() as connection:
        tables = set(inspector.get_table_names())
        if "conversations" in tables:
            columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "title" not in columns:
                logger.warning("旧 conversations 表缺少 title 列，正在执行兼容迁移")
                connection.execute(
                    text("ALTER TABLE conversations ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT '新会话'")
                )
                logger.info("conversations.title 兼容迁移完成")
            if "dify_conversation_id" not in columns:
                logger.warning("旧 conversations 表缺少 dify_conversation_id 列，正在执行兼容迁移")
                connection.execute(
                    text(
                        "ALTER TABLE conversations "
                        "ADD COLUMN dify_conversation_id VARCHAR(128) NULL"
                    )
                )

        if "messages" in tables:
            message_columns = {column["name"] for column in inspector.get_columns("messages")}
            message_column_sql = {
                "sequence_no": "BIGINT NULL",
                "answer_status": "VARCHAR(32) NULL",
                "sources": "JSON NULL",
                "images": "JSON NULL",
            }
            for column_name, column_type in message_column_sql.items():
                if column_name not in message_columns:
                    logger.warning("旧 messages 表缺少 %s 列，正在执行兼容迁移", column_name)
                    connection.execute(
                        text(f"ALTER TABLE messages ADD COLUMN {column_name} {column_type}")
                    )

        if "users" not in tables:
            return
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "user_id" not in user_columns:
            return

        logger.warning("检测到旧 users.user_id，开始迁移至 users.id")
        legacy_users = connection.execute(text("SELECT id, user_id FROM users")).mappings().all()
        mappings = {
            str(row["user_id"]): str(row["id"])
            for row in legacy_users
            if row["user_id"] is not None and str(row["user_id"]) != str(row["id"])
        }
        if "conversations" in tables and mappings:
            for legacy_id, canonical_id in mappings.items():
                connection.execute(
                    text("UPDATE conversations SET user_id = :canonical_id WHERE user_id = :legacy_id"),
                    {"canonical_id": canonical_id, "legacy_id": legacy_id},
                )
        if "conversations" in tables:
            orphan_ids = connection.execute(
                text(
                    "SELECT DISTINCT c.user_id FROM conversations c "
                    "LEFT JOIN users u ON c.user_id = u.id "
                    "WHERE u.id IS NULL"
                )
            ).scalars().all()
            for orphan_id in orphan_ids:
                token = uuid5(NAMESPACE_URL, f"zrdds-legacy-user:{orphan_id}").hex[:24]
                canonical_id = str(uuid4())
                connection.execute(
                    text(
                        "INSERT INTO users (id, username, email, created_at, updated_at) "
                        "VALUES (:id, :username, :email, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": canonical_id,
                        "username": f"legacy_{token}",
                        "email": f"legacy_{token}@invalid.local",
                    },
                )
                connection.execute(
                    text("UPDATE conversations SET user_id = :canonical_id WHERE user_id = :legacy_id"),
                    {"canonical_id": canonical_id, "legacy_id": orphan_id},
                )
                logger.warning("孤儿会话 user_id=%s 已迁移到兼容用户 id=%s", orphan_id, canonical_id)

            invalid = connection.execute(
                text(
                    "SELECT COUNT(*) FROM conversations c "
                    "LEFT JOIN users u ON c.user_id = u.id "
                    "WHERE u.id IS NULL"
                )
            ).scalar_one()
            if invalid:
                raise RuntimeError("无法迁移：仍存在无法匹配 users.id 的会话")

            if engine.dialect.name == "mysql":
                connection.execute(text("ALTER TABLE conversations MODIFY user_id VARCHAR(36) NOT NULL"))
                foreign_keys = inspect(connection).get_foreign_keys("conversations")
                has_user_fk = any(
                    fk.get("referred_table") == "users"
                    and fk.get("constrained_columns") == ["user_id"]
                    for fk in foreign_keys
                )
                if not has_user_fk:
                    connection.execute(
                        text(
                            "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_user_id "
                            "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
                        )
                    )
                    logger.info("conversations.user_id 已统一为 users.id 外键")
        connection.execute(text("ALTER TABLE users DROP COLUMN user_id"))
        logger.info("users.user_id 已安全迁移并删除")


def _ensure_conversation_user_foreign_key() -> None:
    """Ensure legacy conversations reference the canonical users.id column."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"users", "conversations"}.issubset(tables) or engine.dialect.name != "mysql":
        return

    with engine.begin() as connection:
        orphan_ids = connection.execute(
            text(
                "SELECT DISTINCT c.user_id FROM conversations c "
                "LEFT JOIN users u ON c.user_id = u.id "
                "WHERE u.id IS NULL"
            )
        ).scalars().all()
        for orphan_id in orphan_ids:
            token = uuid5(NAMESPACE_URL, f"zrdds-legacy-user:{orphan_id}").hex[:24]
            canonical_id = str(uuid4())
            connection.execute(
                text(
                    "INSERT INTO users (id, username, email, created_at, updated_at) "
                    "VALUES (:id, :username, :email, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": canonical_id,
                    "username": f"legacy_{token}",
                    "email": f"legacy_{token}@invalid.local",
                },
            )
            connection.execute(
                text("UPDATE conversations SET user_id = :canonical_id WHERE user_id = :legacy_id"),
                {"canonical_id": canonical_id, "legacy_id": orphan_id},
            )
            logger.warning("孤儿会话 user_id=%s 已迁移到兼容用户 id=%s", orphan_id, canonical_id)

        invalid = connection.execute(
            text(
                "SELECT COUNT(*) FROM conversations c "
                "LEFT JOIN users u ON c.user_id = u.id "
                "WHERE u.id IS NULL"
            )
        ).scalar_one()
        if invalid:
            raise RuntimeError("无法迁移：仍存在无法匹配 users.id 的会话")

        connection.execute(text("ALTER TABLE conversations MODIFY user_id VARCHAR(36) NOT NULL"))
        foreign_keys = inspect(connection).get_foreign_keys("conversations")
        has_user_fk = any(
            fk.get("referred_table") == "users"
            and fk.get("constrained_columns") == ["user_id"]
            for fk in foreign_keys
        )
        if not has_user_fk:
            connection.execute(
                text(
                    "ALTER TABLE conversations ADD CONSTRAINT fk_conversations_user_id "
                    "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
                )
            )
            logger.info("conversations.user_id 已统一为 users.id 外键")
