import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv

load_dotenv()


class AIClient:
    def __init__(self):
        self.base_url = os.getenv("DIFY_API_BASE")
        self.api_key = os.getenv("DIFY_API_KEY")

    async def query(
        self,
        question: str,
        version: str | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> Dict[str, Any]:

        url = f"{self.base_url}/chat-messages"

        payload = {
            "inputs": {},
            "query": question,
            "response_mode": "blocking",
            "conversation_id": "",
            "user": user_id or "test-user",
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()

        return {
            "answer": data["answer"],
            "status": "answered",
            "sources": [],
        }