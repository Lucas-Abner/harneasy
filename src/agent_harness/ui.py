from __future__ import annotations

import json
import os
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

ACCENT = "#7aa2f7"
MUTED = "#565f89"


class AgentUI:
    """Terminal interface for the agent conversation."""

    def __init__(self, *, model: str, tool_names: list[str]) -> None:
        self.console = Console(highlight=False)
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
            ("◆ ", "bold bright_cyan"),
            ("agent-harness", "bold white"),
            ("  ·  coding session", "dim"),
        )
        meta = Text.assemble(
            ("workspace ", "dim"), (cwd, "white"),
            ("\nbranch ", "dim"), (branch or "detached", "bright_yellow"),
            ("\nmodel ", "dim"), (self.model, "bright_green"),
        )
        self.console.print(Panel(Group(title, Rule(style="grey30"), meta), border_style="bright_cyan", padding=(1, 2)))
        self.console.print("[dim]Describe a task, ask about the code, or use /help.[/dim]\n")

    def prompt(self) -> str:
        try:
            return self.console.input("[bold bright_cyan]❯[/bold bright_cyan] ").strip()
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
    """Run the interactive loop while keeping orchestration outside the renderer."""
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
        while True:
            try:
                todo = active_todo()
                label = todo.get("content", "thinking...") if isinstance(todo, dict) else todo
                with ui.thinking(label=label):
                    message, usage, _, _ = call_llm(messages + [reminder()])
                messages.append(message.model_dump(exclude_none=True))

                if message.content:
                    ui.show_agent_message(message.content)
                    ui.show_usage(usage)
                if not message.tool_calls and not has_open_todos():
                    break

                for tool_call in message.tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    try:
                        result = str(tools[tool_call.function.name](**args))
                    except Exception as error:
                        result = f"Tool error: {error}"
                    ui.show_tool_call(tool_call.function.name, args, result)
                    if tool_call.function.name == "update_todos":
                        ui.show_todos(todos())
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
            except Exception as error:
                ui.show_error(error)
                break

            if needed(usage):
                messages = compact(messages)
