"""Repair the formatting mistakes small models make in tool calls."""
from __future__ import annotations

import ast
import json
import re
import uuid
from typing import Any

from openai.types.chat import ChatCompletionMessageFunctionToolCall


def _strip_code_fence(text: str) -> str:
    """Turn '```json\\n{...}\\n```' into '{...}'."""
    match = re.fullmatch(r"\s*```[a-zA-Z]*\s*(.*?)\s*```\s*", text, re.DOTALL)
    return match.group(1) if match else text


def _close_brackets(text: str) -> str:
    """Close braces, brackets and strings left open by a truncated answer."""
    closers = []
    in_string = False
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string and char in "{[":
            closers.append("}" if char == "{" else "]")
        elif not in_string and char in "}]" and closers:
            closers.pop()
    return text + ('"' if in_string else "") + "".join(reversed(closers))


def _try_load(text: str) -> Any:
    """Return the parsed value, or None if this text is not valid JSON/Python."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        # Accepts single quotes, True/False/None and other Python-style dicts.
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Parse tool arguments, repairing common mistakes. Raises ValueError if impossible."""
    if isinstance(raw, dict):
        return raw
    if raw is None or not str(raw).strip():
        return {}

    text = _strip_code_fence(str(raw).strip())
    candidates = [
        text,
        re.sub(r",\s*([}\]])", r"\1", text),  # trailing commas: {"a": 1,}
        _close_brackets(text),                  # truncated: {"a": "b
    ]

    for candidate in candidates:
        value = _try_load(candidate)
        # Double-encoded JSON: the model sent the object as a string.
        if isinstance(value, str):
            value = _try_load(value)
        if isinstance(value, dict):
            # Some models wrap the arguments: {"name": "...", "arguments": {...}}.
            inner = value.get("arguments", value.get("parameters"))
            if isinstance(inner, dict) and set(value) <= {"name", "arguments", "parameters"}:
                return inner
            return value

    raise ValueError(f"argumentos não são um objeto JSON válido: {str(raw)[:120]}")


# Formats in which models write a tool call as plain text instead of using the API.
TEXT_TOOL_CALL_PATTERNS = [
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",  # Hermes / Qwen
    r"```(?:json)?\s*(\{.*?\})\s*```",          # Markdown code block
]


def _call_from_object(data: Any, tool_names: set[str]) -> dict[str, Any] | None:
    """Return {'name', 'arguments'} when data looks like a call to a known tool."""
    if not isinstance(data, dict) or data.get("name") not in tool_names:
        return None
    arguments = data.get("arguments", data.get("parameters", {}))
    try:
        arguments = parse_arguments(arguments)
    except ValueError:
        return None
    return {"name": data["name"], "arguments": arguments}


def extract_text_tool_calls(content: str, tool_names: set[str]) -> tuple[list[dict[str, Any]], str]:
    """Find tool calls written as text. Return (calls, content without the calls).

    Only calls to known tools are accepted, so a JSON example the model shows
    the user is not executed by accident.
    """
    calls = []
    remaining = content
    for pattern in TEXT_TOOL_CALL_PATTERNS:
        for match in re.finditer(pattern, content, re.DOTALL):
            call = _call_from_object(_try_load(match.group(1)), tool_names)
            if call:
                calls.append(call)
                remaining = remaining.replace(match.group(0), "")
        if calls:
            return calls, remaining.strip()

    # The whole answer is a single bare JSON object: {"name": ..., "arguments": ...}.
    call = _call_from_object(_try_load(content.strip()), tool_names)
    if call:
        return [call], ""
    return [], content


def to_tool_call_objects(calls: list[dict[str, Any]]) -> list[ChatCompletionMessageFunctionToolCall]:
    """Convert parsed calls to the same objects the API returns for native calls."""
    return [
        ChatCompletionMessageFunctionToolCall(
            id=f"call_text_{uuid.uuid4().hex[:12]}",
            type="function",
            function={"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
        )
        for call in calls
    ]
