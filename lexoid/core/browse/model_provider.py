"""Provider-neutral structured response adapter for browse agents."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from agent_framework import (
        BaseChatClient,
        ChatResponse,
        Message,
        SupportsChatGetResponse,
    )
except ImportError:  # pragma: no cover - exercised by a clean core install
    BaseChatClient = object  # type: ignore[misc,assignment]
    ChatResponse = Any  # type: ignore[misc,assignment]
    Message = Any  # type: ignore[misc,assignment]
    SupportsChatGetResponse = Any  # type: ignore[misc,assignment]

try:
    from agent_framework.openai import OpenAIChatClient
except ImportError:  # pragma: no cover - exercised by a clean core install
    OpenAIChatClient = None  # type: ignore[misc,assignment]

from lexoid.core.browse.schemas import BrowseUsage
from lexoid.core.parse_type.llm_parser import create_response
from lexoid.core.utils import get_api_provider_for_model

ChatClient = SupportsChatGetResponse[Any]


def create_chat_client(model: str) -> ChatClient:
    """Create the native OpenAI client or the Lexoid provider fallback."""
    try:
        provider = get_api_provider_for_model(model)
    except ValueError as error:
        raise ValueError(f"model_unsupported: {model}") from error
    if provider == "openai":
        if OpenAIChatClient is None:
            raise ImportError(
                "Browse OpenAI support requires: pip install 'lexoid[browse]'"
            )
        return OpenAIChatClient(model=model)
    return LexoidChatClient(model)


def browse_usage_from_response(response: Any) -> BrowseUsage:
    """Normalize Agent Framework and legacy provider token usage."""
    usage = getattr(response, "usage_details", None) or {}
    if usage:
        return BrowseUsage(
            input=usage.get("input_token_count", 0) or 0,
            output=usage.get("output_token_count", 0) or 0,
            total=usage.get("total_token_count", 0) or 0,
        )
    raw_response = getattr(response, "raw_representation", None) or {}
    raw_usage = raw_response.get("usage", {})
    return BrowseUsage(
        input=raw_usage.get("input", raw_usage.get("input_tokens", 0)),
        output=raw_usage.get("output", raw_usage.get("output_tokens", 0)),
        total=raw_usage.get("total", raw_usage.get("total_tokens", 0)),
    )


class LexoidChatClient(BaseChatClient):
    """Agent Framework client backed by Lexoid's synchronous provider bridge."""

    def __init__(self, model: str) -> None:
        if BaseChatClient is object:
            raise ImportError(
                "Browse requires optional dependencies. Install with: pip install 'lexoid[browse]'"
            )
        super().__init__()
        self.model = model
        try:
            self.provider = get_api_provider_for_model(model)
        except ValueError as error:
            raise ValueError(f"model_unsupported: {model}") from error

    async def _inner_get_response(
        self,
        *,
        messages: list[Message],
        stream: bool,
        options: dict[str, Any],
        **kwargs: Any,
    ) -> ChatResponse:
        """Adapt Agent Framework messages to Lexoid's provider abstraction."""
        if stream:
            raise NotImplementedError("Lexoid browse does not support streaming models")
        system_parts: list[str] = []
        user_parts: list[str] = []
        for message in messages:
            text = message.text or ""
            if message.role == "system":
                system_parts.append(text)
            else:
                user_parts.append(text)
        response: dict[str, Any] = await asyncio.to_thread(
            create_response,
            api=self.provider,
            model=self.model,
            system_prompt="\n\n".join(system_parts),
            user_prompt="\n\n".join(user_parts),
            temperature=0.0,
            max_tokens=1_024,
        )
        return ChatResponse(
            messages=[Message("assistant", [response.get("response", "")])],
            model=self.model,
            raw_representation=response,
        )

    async def complete_json(
        self, system_prompt: str, user_prompt: str
    ) -> tuple[str, BrowseUsage]:
        """Request constrained JSON and normalize provider usage."""
        response = await self.get_response(
            messages=[
                Message("system", [system_prompt]),
                Message("user", [user_prompt]),
            ]
        )
        return response.text or "", browse_usage_from_response(response)
