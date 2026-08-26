"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.api.chat import router as chat_router
from app.config import API_V1_PREFIX, PROJECT_NAME, PROJECT_VERSION
from app.database.database import init_db


app = FastAPI(title=PROJECT_NAME, version=PROJECT_VERSION)
logger = logging.getLogger(__name__)


@app.on_event("startup")
def initialize_database() -> None:
    """Create missing tables while allowing the app to start during DB outages."""
    try:
        init_db()
    except SQLAlchemyError:
        logger.exception("数据库初始化失败；聊天接口将在数据库恢复后重试")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(chat_router, prefix=API_V1_PREFIX)
