from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings


@dataclass
class LLMResponse:
    content: str | None = None
    thinking: str | None = None
    tool_calls: list[dict] = field(default_factory=list)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model
        self.timeout = timeout or settings.llm_timeout_seconds

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        last_error = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return self._parse_response(data)
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < 2:
                    await _sleep(2**attempt)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500 and attempt < 2:
                    await _sleep(2**attempt)
                else:
                    raise LLMError(f"LLM API error: {e.response.status_code} {e.response.text[:200]}") from e
            except Exception as e:
                last_error = e
                if attempt < 2:
                    await _sleep(2**attempt)

        raise LLMError(f"LLM call failed after 3 attempts: {last_error}")

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        message = choice["message"]

        content = message.get("content")
        reasoning = message.get("reasoning_content")

        tool_calls = []
        raw_tool_calls = message.get("tool_calls") or []
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "arguments": args,
            })

        return LLMResponse(
            content=content,
            thinking=reasoning,
            tool_calls=tool_calls,
        )


async def _sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
