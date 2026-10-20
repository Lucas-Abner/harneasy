"""Session todo plan with validation before state mutation."""
from __future__ import annotations

MARKS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}
VALID_STATUSES = set(MARKS)
TODOS: list[dict[str, str]] = []


def write_todos(todos: list[dict[str, str]]) -> str:
    if not isinstance(todos, list):
        raise TypeError("todos precisa ser uma lista.")

    validated: list[dict[str, str]] = []
    for index, item in enumerate(todos):
        if not isinstance(item, dict):
            raise TypeError(f"A tarefa {index + 1} precisa ser um objeto.")
        status = item.get("status")
        content = item.get("content")
        if status not in VALID_STATUSES:
            raise ValueError(f"Status inválido na tarefa {index + 1}: {status!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"A tarefa {index + 1} precisa ter conteúdo textual não vazio.")
        validated.append({"status": status, "content": content.strip()})

    active = [todo for todo in validated if todo["status"] == "in_progress"]
    if len(active) > 1:
        raise ValueError("Somente uma tarefa pode estar in_progress por vez.")

    TODOS[:] = validated
    return todos_prompts() or "Lista de tarefas limpa."


def todos_prompts() -> str:
    return "\n".join(f"{MARKS[todo['status']]} {todo['content']}" for todo in TODOS)


def active_todo() -> dict[str, str] | str:
    for todo in TODOS:
        if todo["status"] == "in_progress":
            return todo
    return "pensando..."


def has_open_todos() -> bool:
    return any(todo["status"] in {"pending", "in_progress"} for todo in TODOS)
