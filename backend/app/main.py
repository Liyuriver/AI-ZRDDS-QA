"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.config import API_V1_PREFIX, PROJECT_NAME, PROJECT_VERSION


app = FastAPI(title=PROJECT_NAME, version=PROJECT_VERSION)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(chat_router, prefix=API_V1_PREFIX)
