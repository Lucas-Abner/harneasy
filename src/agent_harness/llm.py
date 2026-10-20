"""OpenAI-compatible model client, configured for local-first use."""
from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .tools import TOOLS_SCHEMAS

load_dotenv()

# Ollama-compatible endpoint is the default because the default model is local.
# Set OPENAI_API_BASE / OPENAI_BASE_URL to use another OpenAI-compatible server.
BASE_URL = (
    os.getenv("OPENAI_API_BASE")
    or os.getenv("OPENAI_BASE_URL")
    or "http://localhost:11434/v1"
)
API_KEY = os.getenv("OPENAI_API_KEY") or "ollama"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def call_llm(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[Any, dict[str, int | None], Any, Any]:
    """Call an OpenAI-compatible chat endpoint with optional tool schemas."""
    kwargs: dict[str, Any] = {
        "model": os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        "messages": messages,
    }
    selected_tools = TOOLS_SCHEMAS if tools is None else tools
    if selected_tools:
        kwargs["tools"] = selected_tools
        kwargs["tool_choice"] = "auto"

    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT")
    if reasoning_effort:
        # Not every local OpenAI-compatible server supports this extension.
        kwargs["reasoning_effort"] = reasoning_effort

    response = client.chat.completions.create(**kwargs)
    output = response.choices[0].message
    usage_object = getattr(response, "usage", None)
    completion_details = getattr(usage_object, "completion_tokens_details", None)
    prompt_details = getattr(usage_object, "prompt_tokens_details", None)

    prompt_tokens = getattr(usage_object, "prompt_tokens", None)
    completion_tokens = getattr(usage_object, "completion_tokens", None)
    if prompt_tokens is None:
        # Some local OpenAI-compatible servers omit usage. Estimate token load
        # from serialized messages so context compaction still has a trigger.
        prompt_tokens = max(1, sum(
            len(json.dumps(item, ensure_ascii=False, default=str)) for item in messages
        ) // 3)
    if completion_tokens is None:
        content = getattr(output, "content", None) or ""
        completion_tokens = max(1, len(content) // 3)

    usage: dict[str, int | None] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None),
        "cached_tokens": getattr(prompt_details, "cached_tokens", None),
    }
    return output, usage, prompt_details, completion_details
