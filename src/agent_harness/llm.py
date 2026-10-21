"""OpenAI-compatible model client, configured for local-first use."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageFunctionToolCall

from .repair import extract_text_tool_calls, to_tool_call_objects
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
# The SDK already retries connection errors, 408/429 and 5xx with backoff.
# Local servers can be slow to load a model, so both knobs are configurable.
client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    max_retries=max(0, int(os.getenv("HARNEASY_LLM_MAX_RETRIES", "3"))),
    timeout=max(1.0, float(os.getenv("HARNEASY_LLM_TIMEOUT", "600"))),
)

# Temperature 0 and a fixed seed make answers repeatable: the same history
# produces the same next step, which also makes benchmark runs comparable.
TEMPERATURE = float(os.getenv("HARNEASY_TEMPERATURE", "0"))
SEED = os.getenv("HARNEASY_SEED", "42")
STREAM = os.getenv("HARNEASY_STREAM", "1").lower() not in {"0", "false", "no"}


def _stream_completion(kwargs: dict[str, Any], on_text: Callable[[str], None]) -> tuple[Any, Any, Any]:
    """Stream the answer, sending text to on_text, and rebuild the full message.

    Tool calls arrive in pieces: the id and name first, then the arguments a
    few characters at a time. They are grouped by their index.
    """
    stream = client.chat.completions.create(**kwargs, stream=True, stream_options={"include_usage": True})
    text_parts: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    usage = None
    finish_reason = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        finish_reason = choice.finish_reason or finish_reason
        if choice.delta.content:
            text_parts.append(choice.delta.content)
            on_text(choice.delta.content)
        for part in choice.delta.tool_calls or []:
            index = part.index if part.index is not None else len(calls)
            call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            call["id"] = part.id or call["id"]
            if part.function and part.function.name:
                call["name"] = part.function.name
            if part.function and part.function.arguments:
                call["arguments"] += part.function.arguments

    tool_calls = [
        ChatCompletionMessageFunctionToolCall(
            id=call["id"] or f"call_{index}",
            type="function",
            function={"name": call["name"], "arguments": call["arguments"]},
        )
        for index, call in sorted(calls.items())
    ]
    # content must be a string, never None: Ollama rejects history messages
    # without content ("invalid message content type: <nil>").
    message = ChatCompletionMessage(role="assistant", content="".join(text_parts), tool_calls=tool_calls or None)
    return message, usage, finish_reason


def call_llm(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    on_text: Callable[[str], None] | None = None,
) -> tuple[Any, dict[str, int | None], Any, Any]:
    """Call an OpenAI-compatible chat endpoint with optional tool schemas.

    With on_text, the answer is streamed and each text piece is passed to it.
    """
    list_infos_llm: list[dict[str, Any]] = []

    kwargs: dict[str, Any] = {
        "model": os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        "messages": messages,
        # Low temperature makes small models follow tool formats more reliably.
        "temperature": TEMPERATURE,
    }
    if SEED:
        kwargs["seed"] = int(SEED)
    selected_tools = TOOLS_SCHEMAS if tools is None else tools
    if selected_tools:
        kwargs["tools"] = selected_tools
        kwargs["tool_choice"] = "auto"

    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT")
    if reasoning_effort:
        # Not every local OpenAI-compatible server supports this extension.
        kwargs["reasoning_effort"] = reasoning_effort

    try:
        if on_text is not None and STREAM:
            output, usage_object, finish_reason = _stream_completion(kwargs, on_text)
        else:
            response = client.chat.completions.create(**kwargs)
            output = response.choices[0].message
            usage_object = getattr(response, "usage", None)
            finish_reason = getattr(response.choices[0], "finish_reason", None)
    except APITimeoutError as error:
        raise RuntimeError(
            f"O modelo não respondeu dentro de HARNEASY_LLM_TIMEOUT={client.timeout}s "
            f"após {client.max_retries} novas tentativas."
        ) from error
    except APIConnectionError as error:
        raise RuntimeError(
            f"Não foi possível conectar a {BASE_URL} após {client.max_retries} novas tentativas. "
            "Confirme que o servidor do modelo está em execução."
        ) from error
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
    content = getattr(output, "content", None) or ""
    if completion_tokens is None:
        completion_tokens = max(1, len(content) // 3)

    tool_call = getattr(output, 'tool_calls', None)

    def _save_jsonl(list_of_dicts: list[dict[str, Any]], filename: str) -> None:
        with open(filename, 'a', encoding='utf-8') as f:
            for item in list_of_dicts:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    list_infos_llm.append({
        "content": content,
        "tool_call": tool_call,
        "finish_reason": finish_reason,
    })
    # Set HARNEASY_DEBUG_LOG=llm_output.jsonl to record raw model answers.
    debug_log = os.getenv("HARNEASY_DEBUG_LOG")
    if debug_log:
        _save_jsonl(list_infos_llm, debug_log)

    # Some models write the tool call as text instead of using the API field.
    if selected_tools and not output.tool_calls and content:
        tool_names = {schema["function"]["name"] for schema in selected_tools}
        text_calls, remaining = extract_text_tool_calls(content, tool_names)
        if text_calls:
            output.tool_calls = to_tool_call_objects(text_calls)
            output.content = remaining  # "" rather than None, see _stream_completion

    usage: dict[str, int | None] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": getattr(completion_details, "reasoning_tokens", None),
        "cached_tokens": getattr(prompt_details, "cached_tokens", None),
    }
    return output, usage, prompt_details, completion_details


def _ollama_get(url: str, payload: dict[str, Any] | None = None, *, timeout: float) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"null")


def _loaded_context_length(root: str, model: str, *, timeout: float) -> int | None:
    names = {model, f"{model}:latest"}
    for loaded in (_ollama_get(f"{root}/api/ps", timeout=timeout) or {}).get("models", []):
        if loaded.get("name") in names or loaded.get("model") in names:
            length = loaded.get("context_length")
            return int(length) if isinstance(length, int) and length > 0 else None
    return None


def ollama_context_length(model: str, *, load_timeout: float = 180) -> int | None:
    """Return the context Ollama actually allocated for ``model``, or None.

    The OpenAI-compatible endpoint cannot set ``num_ctx``, and Ollama silently
    truncates prompts beyond it. The value is only reported for a loaded model,
    so the model is loaded first (which also warms it up for the first turn).
    Returns None for servers that are not Ollama.
    """
    root = BASE_URL.rstrip("/").removesuffix("/v1")
    try:
        _ollama_get(f"{root}/api/version", timeout=2)
        length = _loaded_context_length(root, model, timeout=5)
        if length is None:
            _ollama_get(f"{root}/api/generate", {"model": model, "prompt": ""}, timeout=load_timeout)
            length = _loaded_context_length(root, model, timeout=5)
    except (OSError, ValueError, AttributeError):
        return None
    return length
