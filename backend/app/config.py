"""Application configuration.

Retrieval knobs live here so the RAG pipeline does not scatter environment
lookups through the request path.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

PROJECT_NAME = "ZRDDS Knowledge Base QA API"
PROJECT_VERSION = "0.1.0"
API_V1_PREFIX = "/api/v1"

def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


RERANK_ENABLED = _bool("RERANK_ENABLED", True)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_WORKSPACE_ID = os.getenv("DASHSCOPE_WORKSPACE_ID", "")
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3.7-text-rerank")
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "5"))
RRF_TOP_N = int(os.getenv("RRF_TOP_N", "15"))
BM25_TOP_K = int(os.getenv("BM25_TOP_K", "10"))
DIFY_TOP_K = int(os.getenv("DIFY_TOP_K", "10"))
RRF_K = int(os.getenv("RRF_K", "60"))

# Evidence-based QA thresholds
CONFIDENCE_HIGH_THRESHOLD = 0.75
CONFIDENCE_LOW_THRESHOLD = 0.50
CONFIDENCE_SCORE_NORMALIZATION = "auto"
