"""Context compaction designed to keep small local models focused."""
from __future__ import annotations

import json
import os
from typing import Any

SYSTEM_PROMPT = """
Você está sintetizando o histórico de uma sessão de programação que excedeu
sua janela de contexto. Produza uma nota de transição curta e fiel para que
outro turno possa continuar sem reler toda a conversa.

Use, nesta ordem, apenas seções relevantes:
## Objetivo
O pedido do usuário e as restrições importantes.
## Decisões e descobertas
O que foi tentado, resultados observados e abordagens descartadas.
## Arquivos
Caminhos reais e alterações feitas.
## Estado atual
O que funciona, o que falha e o que não foi concluído.
## Próximos passos
A ação imediata recomendada.

Não invente progresso. Preserve mensagens de erro, nomes de funções e comandos
necessários para continuar. Não inclua introdução nem despedida.
"""

HANDOFF = """<summary>
O histórico antigo foi compactado para liberar contexto. Trate o conteúdo abaixo
como memória de trabalho: não como uma nova solicitação do usuário.

{summary}
</summary>"""

CONTEXT_WINDOWS = max(1024, int(os.getenv("HARNEASY_CONTEXT_WINDOW", "4200")))
COMPACT_TOTAL = min(0.95, max(0.5, float(os.getenv("HARNEASY_COMPACT_TOTAL", "0.85"))))
COMPACT_AT = min(0.8, max(0.25, float(os.getenv("HARNEASY_COMPACT_AT", "0.55"))))
ROLES = {"user": "USER", "assistant": "ASSISTANT", "tool": "TOOL RESULT"}


def needed(usage: dict[str, Any] | None, messages: list[dict[str, Any]] | None = None) -> bool:
    """Trigger compaction from provider usage or an estimate of current history.

    The estimate matters for local servers that omit usage and for the tool
    results appended *after* the last LLM call.
    """
    prompt_tokens = 0
    if usage:
        try:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
        except (TypeError, ValueError):
            prompt_tokens = 0
    if messages:
        prompt_tokens = max(prompt_tokens, estimate(messages))
    return prompt_tokens >= CONTEXT_WINDOWS * COMPACT_TOTAL


def render(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.get("role") == "system":
            continue
        content = str(message.get("content") or "")
        for call in message.get("tool_calls", []) or []:
            function = call.get("function", {})
            content += f"\n[called {function.get('name', 'unknown')}: {function.get('arguments', '{}')}]"
        lines.append(f"{ROLES.get(message.get('role', ''), message.get('role', 'unknown'))}: {content}")
    return "\n\n".join(lines)


def _deterministic_summary(messages: list[dict[str, Any]], error: Exception) -> str:
    """Fallback when the summarization model is unavailable or fails."""
    useful = []
    for message in messages:
        role = message.get("role", "unknown")
        content = str(message.get("content") or "")
        if message.get("tool_calls"):
            calls = message["tool_calls"]
            content += "\n" + "\n".join(
                f"Tool call: {c.get('function', {}).get('name')} {c.get('function', {}).get('arguments')}"
                for c in calls
            )
        if content.strip():
            useful.append(f"{role}: {content[:500]}")
    tail = "\n\n".join(useful[-8:])
    return (
        "## Estado atual\nA compactação por LLM falhou; resumo mecânico dos últimos eventos.\n"
        f"Erro do sumarizador: {type(error).__name__}: {error}\n\n{tail}"
    )


def summarize(messages: list[dict[str, Any]]) -> str:
    try:
        # Import lazily so boundary/estimate helpers remain testable without an
        # installed SDK and compaction can fall back if the provider is absent.
        from .llm import client

        result = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render(messages)},
            ],
        )
        summary = result.choices[0].message.content
        if summary and summary.strip():
            summary = summary.strip()
            maximum = max(1200, int(CONTEXT_WINDOWS * COMPACT_AT))
            if len(summary) > maximum:
                summary = summary[:maximum] + "\n\n[Resumo reduzido para preservar a janela de contexto.]"
            return summary
        raise ValueError("o modelo de compactação retornou conteúdo vazio")
    except Exception as error:
        return _deterministic_summary(messages, error)


def safe_boundary(messages: list[dict[str, Any]], start: int) -> int:
    """Never split an assistant tool-call block from its tool responses."""
    boundary = max(start, 1)
    if boundary < len(messages) and messages[boundary].get("role") == "tool":
        # A response block can contain several consecutive tool messages. If
        # compaction starts at any one of them, retain the assistant request and
        # the complete set of results so the API never receives orphaned tools.
        for index in range(boundary - 1, 0, -1):
            message = messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                return index
            if message.get("role") != "tool":
                break
    return boundary


def estimate(messages: list[dict[str, Any]]) -> int:
    # JSON length is not a tokenizer; divide conservatively for Latin source text.
    return sum(len(json.dumps(m, ensure_ascii=False, default=str)) for m in messages) // 3


def tail_start(messages: list[dict[str, Any]], budget: int) -> int:
    total = 0
    for index in range(len(messages) - 1, 0, -1):
        message_size = estimate([messages[index]])
        if total + message_size > budget:
            return safe_boundary(messages, index)
        total += message_size
    return safe_boundary(messages, 1)


def compact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) < 3:
        return messages
    cut = tail_start(messages, int(CONTEXT_WINDOWS * COMPACT_AT))
    if cut <= 1:
        return messages

    summary = summarize(messages[1:cut])
    if not summary.strip():
        return messages
    return [
        messages[0],
        {"role": "user", "content": HANDOFF.format(summary=summary)},
        *messages[cut:],
    ]
