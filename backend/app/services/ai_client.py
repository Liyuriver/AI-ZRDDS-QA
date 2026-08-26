"""AI provider abstraction.

The mock implementation keeps the API independent from the future AI Service.
Its query shape can later be backed by POST /internal/ai/v1/query.
"""

from typing import Any, Dict


class AIClient:
    """Client facade for the AI Service, currently backed by a mock response."""

    async def query(
        self,
        question: str,
        version: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> Dict[str, Any]:
        """Return a fixed answer until the real AI Service is available."""
        return {
            "answer": "这是当前阶段的模拟 ZRDDS 回答。",
            "status": "answered",
            "sources": [],
        }
