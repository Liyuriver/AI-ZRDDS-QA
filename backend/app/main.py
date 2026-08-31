"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.api.chat import conversation_router, router as chat_router
from app.api.user import router as user_router
from app.config import API_V1_PREFIX, PROJECT_NAME, PROJECT_VERSION
from app.database.database import init_db

from pathlib import Path
from fastapi.staticfiles import StaticFiles


app = FastAPI(title=PROJECT_NAME, version=PROJECT_VERSION)
HYBRID_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "hybrid"
HYBRID_DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/hybrid",
    StaticFiles(directory=str(HYBRID_DATA_DIR)),
    name="hybrid-static",
)

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
app.include_router(conversation_router, prefix=API_V1_PREFIX)
app.include_router(user_router, prefix=API_V1_PREFIX)
