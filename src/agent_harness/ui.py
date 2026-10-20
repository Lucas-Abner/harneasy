from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status
from rich.table import Table
from rich.text import Text
from .compact import needed, compact
from rich.padding import Padding
from rich.prompt import Confirm

ACCENT = "#7aa2f7"
MUTED = "#565f89"


class AgentUI:
    """Terminal interface for the agent conversation."""

    def __init__(self, *, model: str, tool_names: list[str]) -> None:
        if os.name == "nt":
            for stream in (sys.stdout, sys.stderr):
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="replace")
        self.console = Console(highlight=False, legacy_windows=False)
        self.model = model
        self.tool_names = tool_names
        self.commands = {
            "/help": "show available commands",
            "/clear": "clear the conversation",
            "/status": "show session and model information",
            "/exit": "leave the harness",
        }

    def show_welcome(self, *, cwd: str, branch: str) -> None:
        title = Text.assemble(
            ("* ", "bold bright_cyan"),
            ("Harneasy", "bold white"),
            ("  ·  local coding agent", "dim"),
        )
        from .sandbox import name as sandbox_name
        meta = Text.assemble(
            ("workspace ", "dim"), (cwd, "white"),
            ("\nbranch ", "dim"), (branch or "detached", "bright_yellow"),
            ("\nmodel ", "dim"), (self.model, "bright_green"),
            ("\nsandbox ", "dim"), (sandbox_name(), "bright_yellow" if sandbox_name() != "none" else "red"),
        )
        self.console.print(Panel(Group(title, Rule(style="grey30"), meta), border_style="bright_cyan", padding=(1, 2)))
        self.console.print("[dim]Describe a task, ask about the code, or use /help.[/dim]\n")

    def prompt(self) -> str:
        try:
            return self.console.input("[bold bright_cyan]>[/bold bright_cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return "/exit"

    def command_help(self) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold bright_cyan", width=12)
        table.add_column(style="dim")
        for command, description in self.commands.items():
            table.add_row(command, description)
        self.console.print(Panel(table, title="Commands", border_style="grey30"))

    def show_status(self, *, message_count: int, tool_count: int) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="white")
        table.add_row("model", self.model)
        table.add_row("messages", str(message_count))
        table.add_row("tools", f"{tool_count} available")
        table.add_row("directory", os.getcwd())
        from .sandbox import name as sandbox_name
        table.add_row("sandbox", sandbox_name())
        self.console.print(Panel(table, title="Session", border_style="grey30"))

    def show_todos(self, content: str) -> None:
        if content:
            self.console.print(
                Panel(
                    Text(content),
                    title="[bold bright_yellow]todo list[/bold bright_yellow]",
                    border_style="yellow",
                    padding=(0, 1),
                )
            )

    def thinking(self, label: str = "thinking") -> Status:
        return self.console.status(
            Spinner("dots", text=Text(f" {label}", style="dim")),
            spinner_style="bright_cyan",
        )

    def show_agent_message(self, content: str) -> None:
        self.console.print(Panel(Markdown(content), border_style="bright_cyan", title="[bold bright_cyan]agent[/bold bright_cyan]", padding=(1, 2)))

    def show_tool_call(self, name: str, args: dict[str, Any], result: str) -> None:
        rendered_args = json.dumps(args, ensure_ascii=False, indent=2)
        preview = result if len(result) <= 1800 else result[:1800] + "\n… [output truncated]"
        body = Group(
            Text(rendered_args, style="dim"),
            Rule(style="grey30"),
            Text(preview or "(no output)", style="white"),
        )
        self.console.print(Panel(body, title=f"[bold bright_yellow]tool · {name}[/bold bright_yellow]", border_style="yellow", padding=(0, 1)))

    def show_error(self, error: Exception) -> None:
        self.console.print(Panel(str(error), title="[bold red]error[/bold red]", border_style="red"))

    def show_usage(self, usage: dict[str, Any]) -> None:
        formatted_usage = (" =°= ").join(f"{key.replace('_', ' ')}: {value}" for key, value in usage.items())
        self.console.print(f'[dim]{" "*40}{formatted_usage}[/dim]')


    def confirm(self, reason: str) -> bool:
        """Ask before executing a command outside the automatic safe allowlist."""
        self.console.print(Panel(reason or "A ferramenta solicita aprovação.", title="[bold yellow]Permissão necessária[/bold yellow]", border_style="yellow"))
        return Confirm.ask("Autorizar esta ação?", default=False, console=self.console)

    def goodbye(self) -> None:
        self.console.print("\n[dim]Session closed.[/dim]")


def run_with_ui(
    *,
    system_prompt: str,
    call_llm: Callable[..., tuple[Any, dict[str, Any], Any, Any]],
    tools: dict[str, Callable[..., str]],
    reminder: Callable[[], dict[str, str]],
    branch: str,
    model: str,
    active_todo: Callable[[], dict[str, str] | str],
    todos: Callable[[], str],
    has_open_todos: Callable[[], bool],
) -> None:
    """Interactive shell with bounded turns and a single guarded tool gateway."""
    from collections import Counter
    from .tools import execute_tool

    max_turns = max(1, int(os.getenv("HARNEASY_MAX_TURNS_PER_REQUEST", "30")))
    max_tool_calls = max(1, int(os.getenv("HARNEASY_MAX_TOOL_CALLS_PER_TURN", "8")))
    repeat_limit = max(2, int(os.getenv("HARNEASY_REPEAT_TOOL_LIMIT", "3")))

    ui = AgentUI(model=model, tool_names=list(tools))
    ui.show_welcome(cwd=os.getcwd(), branch=branch)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    while True:
        user_input = ui.prompt()
        if not user_input:
            continue
        if user_input == "/exit":
            ui.goodbye()
            return
        if user_input == "/help":
            ui.command_help()
            continue
        if user_input == "/clear":
            messages = [{"role": "system", "content": system_prompt}]
            ui.console.clear()
            ui.show_welcome(cwd=os.getcwd(), branch=branch)
            continue
        if user_input == "/status":
            ui.show_status(message_count=len(messages), tool_count=len(tools))
            continue

        messages.append({"role": "user", "content": user_input})
        repeated_calls: Counter[str] = Counter()
        tool_calls_this_request = 0
        finished = False

        for turn in range(max_turns):
            try:
                todo = active_todo()
                label = todo.get("content", "thinking...") if isinstance(todo, dict) else todo
                with ui.thinking(label=label):
                    message, usage, _, _ = call_llm(messages + [reminder()])
                messages.append(message.model_dump(exclude_none=True))
            except Exception as error:
                ui.show_error(error)
                finished = True
                break

            if message.content:
                ui.show_agent_message(message.content)
                ui.show_usage(usage or {})

            if not message.tool_calls:
                if has_open_todos():
                    ui.console.print(
                        "[yellow]A resposta terminou, mas ainda existem tarefas abertas no plano. "
                        "Revise a lista antes de considerar o trabalho concluído.[/yellow]"
                    )
                    ui.show_todos(todos())
                finished = True
                break

            reporter = lambda name, args, result: ui.show_tool_call(name, args, result)
            for call_index, tool_call in enumerate(message.tool_calls):
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("os argumentos precisam ser um objeto JSON")
                except (TypeError, json.JSONDecodeError, ValueError) as error:
                    args = {}
                    result = f"Erro ao analisar argumentos da ferramenta {name}: {error}"
                else:
                    signature = name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)
                    repeated_calls[signature] += 1
                    if repeated_calls[signature] >= repeat_limit:
                        result = (
                            f"Possível estagnação: a ferramenta {name} foi chamada com os mesmos "
                            f"argumentos {repeated_calls[signature]} vezes nesta solicitação. "
                            "Não repita a mesma chamada. Escolha uma ação diferente ou explique o bloqueio."
                        )
                    elif tool_calls_this_request >= max_turns * max_tool_calls:
                        result = "Limite total de chamadas de ferramenta nesta solicitação atingido."
                    elif call_index >= max_tool_calls:
                        result = f"Limite de {max_tool_calls} chamadas de ferramenta por turno atingido; esta chamada não foi executada."
                    else:
                        result = execute_tool(
                            name,
                            args,
                            confirm=ui.confirm,
                            reporter=reporter if name == "task" else None,
                        )
                        tool_calls_this_request += 1

                ui.show_tool_call(name, args, result)
                if name == "update_todos":
                    ui.show_todos(todos())
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

            try:
                if needed(usage or {}, messages):
                    messages = compact(messages)
            except Exception as error:
                # A summarizer failure should not destroy the active session.
                ui.show_error(RuntimeError(f"Falha ao compactar contexto; mantendo histórico atual: {error}"))

        if not finished and not has_open_todos():
            ui.console.print(
                f"[yellow]Limite de {max_turns} turnos atingido para esta solicitação. "
                "O agente parou para evitar um loop infinito.[/yellow]"
            )
        elif not finished and has_open_todos():
            ui.console.print(
                f"[yellow]Limite de {max_turns} turnos atingido com tarefas pendentes. "
                "Envie uma instrução mais específica para continuar.[/yellow]"
            )
