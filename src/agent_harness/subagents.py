"""Isolated, read-only exploration agents for repository questions."""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Callable

MAX_TURNS = max(1, int(os.getenv("HARNEASY_SUBAGENT_MAX_TURNS", "10")))
MAX_TOOL_CALLS_PER_TURN = max(1, int(os.getenv("HARNEASY_SUBAGENT_MAX_TOOL_CALLS_PER_TURN", "5")))
REPEAT_LIMIT = max(2, int(os.getenv("HARNEASY_REPEAT_TOOL_LIMIT", "3")))
WITHHELD = {"task", "update_todos", "write_file", "str_replace"}

SYSTEM_PROMPT = f"""
Você é um subagente de exploração. Sua tarefa é investigar o repositório e
retornar descobertas curtas, precisas e verificáveis. Você não deve modificar
arquivos nem executar ações com efeitos colaterais.

Workspace: {os.getcwd()}

Use bash apenas para comandos de leitura, e use read_file/read_skill quando
necessário. Prefira buscas em lote. Não invente resultados: informe caminhos,
nomes de funções, linhas e incertezas. Mire em menos de 150 palavras.
"""


def toolset() -> list[dict[str, Any]]:
    """Return schemas for the limited set of tools available to a subagent."""
    from .tools import TOOLS_SCHEMAS

    return [
        schema for schema in TOOLS_SCHEMAS
        if schema.get("function", {}).get("name") not in WITHHELD
    ]


def task(
    description: str,
    *,
    confirm: Callable[[str], bool] | None = None,
    reporter: Callable[[str, dict[str, Any], str], None] | None = None,
) -> str:
    """Run a fresh, bounded, read-only agent and return its final report."""
    from .compact import compact, needed
    from .llm import call_llm
    from .tools import execute

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": description},
    ]
    last_report: str | None = None
    seen_calls: Counter[str] = Counter()

    if reporter:
        reporter("subagent", {"description": description}, "Exploração iniciada em contexto isolado.")

    for turn in range(MAX_TURNS):
        try:
            message, usage, _, _ = call_llm(messages, tools=toolset())
        except Exception as error:
            if last_report:
                return f"Subagente interrompido após erro: {type(error).__name__}: {error}\n\nDescobertas parciais:\n{last_report}"
            return f"Erro no subagente: {type(error).__name__}: {error}"

        messages.append(message.model_dump(exclude_none=True))
        if message.content:
            last_report = message.content

        if not message.tool_calls:
            return last_report or "O subagente terminou sem retornar descobertas."

        for call_index, tool_call in enumerate(message.tool_calls):
            name = tool_call.function.name
            try:
                parsed_args = json.loads(tool_call.function.arguments or "{}")
                signature = name + ":" + json.dumps(parsed_args, sort_keys=True, ensure_ascii=False)
            except (TypeError, json.JSONDecodeError):
                signature = name + ":invalid-arguments"
            seen_calls[signature] += 1

            if seen_calls[signature] >= REPEAT_LIMIT:
                args = {}
                result = (
                    f"Estagnação detectada: {name} repetiu a mesma chamada {seen_calls[signature]} vezes. "
                    "Escolha uma ação diferente ou encerre com as descobertas parciais."
                )
                if reporter:
                    reporter(name, args, result)
            elif call_index >= MAX_TOOL_CALLS_PER_TURN:
                args = {}
                result = (
                    f"Limite de {MAX_TOOL_CALLS_PER_TURN} chamadas de ferramenta por turno do subagente. "
                    "Reduza o escopo e retorne as descobertas disponíveis."
                )
                if reporter:
                    reporter(name, args, result)
            else:
                # The readonly flag is enforced by the central executor, not merely
                # requested in the prompt or inferred from the offered schemas.
                args, result = execute(
                    tool_call,
                    confirm=None,
                    reporter=reporter,
                    readonly=True,
                )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        if needed(usage, messages):
            try:
                messages = compact(messages)
            except Exception as error:
                return (
                    f"Subagente não conseguiu compactar o contexto: {error}. "
                    f"Descobertas parciais: {last_report or '(nenhuma)'}"
                )

    if last_report:
        return (
            f"Subagente atingiu o limite de {MAX_TURNS} turnos sem finalizar. "
            f"Descobertas parciais:\n{last_report}"
        )
    return f"Subagente atingiu o limite de {MAX_TURNS} turnos sem descobertas."


TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "task",
        "description": (
            "Delegue uma pergunta autocontida de exploração a um subagente "
            "isolado e somente leitura. Use para localizar funcionalidades, "
            "seguir fluxo de dados ou entender a estrutura do código. Ele não "
            "pode editar arquivos nem chamar outros subagentes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Pergunta completa, com contexto e formato esperado das descobertas.",
                }
            },
            "required": ["description"],
        },
    },
}
