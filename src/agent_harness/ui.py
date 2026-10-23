from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status
from rich.table import Table
from rich.text import Text
from .compact import needed, compact
from .repair import parse_arguments
from .context import verify_command
from .skills import skill_body, suggest_skill
from .tools import UNDO_STACK, changes_since, execute_tool, forget_reads, pending_problems
from rich.padding import Padding
from rich.prompt import Confirm

ACCENT = "#7aa2f7"
MUTED = "#565f89"


class AgentUI:
    """Terminal interface for the agent conversation."""

    def __init__(self, *, model: str, tool_names: list[str], auto_confirm: bool | None = None) -> None:
        if os.name == "nt":
            for stream in (sys.stdout, sys.stderr):
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(encoding="utf-8", errors="replace")
        self.console = Console(highlight=False, legacy_windows=False)
        self.model = model
        self.tool_names = tool_names
        # None = ask the user; True/False = answer every permission prompt automatically (-p mode).
        self.auto_confirm = auto_confirm
        self.commands = {
            "/help": "show available commands",
            "/clear": "clear the conversation",
            "/status": "show session and model information",
            "/undo": "undo the agent's last file edit",
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

    def agent_panel(self, content: str) -> Panel:
        return Panel(Markdown(content), border_style="bright_cyan", title="[bold bright_cyan]agent[/bold bright_cyan]", padding=(1, 2))

    def show_agent_message(self, content: str) -> None:
        self.console.print(self.agent_panel(content))

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
        if self.auto_confirm is not None:
            self.console.print(f"[dim]Resposta automática: {'aprovado' if self.auto_confirm else 'negado'} (use --yes para aprovar).[/dim]")
            return self.auto_confirm
        return Confirm.ask("Autorizar esta ação?", default=False, console=self.console)

    def goodbye(self) -> None:
        self.console.print("\n[dim]Session closed.[/dim]")


class StreamView:
    """Show a spinner until the first token arrives, then the answer as it is written."""

    def __init__(self, ui: AgentUI, label: str) -> None:
        self.ui = ui
        self.label = label
        self.text = ""
        self.live = Live(self._render(), console=ui.console, refresh_per_second=8, vertical_overflow="visible")

    def _render(self):
        if not self.text:
            return Spinner("dots", text=Text(f" {self.label}", style="dim"), style="bright_cyan")
        return self.ui.agent_panel(self.text)

    def add(self, chunk: str) -> None:
        self.text += chunk
        self.live.update(self._render())

    def __enter__(self) -> "StreamView":
        self.live.start()
        return self

    def __exit__(self, *exc_info) -> None:
        if not self.text:
            self.live.transient = True  # remove the spinner when nothing was written
        self.live.stop()


EDIT_TOOLS = {"write_file", "str_replace"}

INTERRUPTED_RESULT = "Execução interrompida pelo usuário antes de concluir esta ferramenta."


def close_dangling_tool_calls(messages: list[dict[str, Any]]) -> None:
    """Answer tool calls left unanswered by an interruption.

    Chat Completions rejects an assistant tool_calls message whose ids have no
    matching tool messages, which would break every later request.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            answered = {m.get("tool_call_id") for m in messages[index + 1:] if m.get("role") == "tool"}
            for call in message["tool_calls"]:
                if call.get("id") not in answered:
                    messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": INTERRUPTED_RESULT})
            return
        if message.get("role") != "tool":
            return


def split_request(call_llm: Callable[..., Any], request: str) -> str:
    """Ask the model, without tools, for the parts of the request; "" if it is a single part.

    Small models often do the first part and stop, so the parts are shown to them up front.
    """
    question = (
        "Liste as partes que precisam ser feitas neste pedido, uma por linha, começando com '- '. "
        "No máximo 5. Não resolva nada agora.\n\nPedido: " + request
    )
    try:
        message, *_ = call_llm([{"role": "user", "content": question}], tools=[])
    except Exception:
        return ""
    lines = [line.strip() for line in (message.content or "").splitlines()]
    parts = [line for line in lines if line.startswith(("-", "*")) or line[:1].isdigit()]
    return "\n".join(parts[:5]) if len(parts) > 1 else ""


def nudge_for(content: str | None, open_todos: bool, todo_list: str) -> str | None:
    """Return a reminder when the model ends its turn too early, else None."""
    if not (content or "").strip():
        return (
            "<system-reminder>Sua resposta veio vazia. Continue a tarefa usando as "
            "ferramentas ou responda ao usuário.</system-reminder>"
        )
    if open_todos:
        return (
            "<system-reminder>Ainda há tarefas abertas no plano:\n"
            f"{todo_list}\n"
            "Continue a próxima tarefa. Se ela não for mais necessária, marque-a "
            "como done com update_todos e explique o motivo.</system-reminder>"
        )
    return None


def run_verification(ui: AgentUI, command: str) -> str | None:
    """Run the project's verification command. Return a reminder if it failed."""
    result = execute_tool("bash", {"command": command}, confirm=ui.confirm)
    ui.show_tool_call("verificação automática", {"command": command}, result)
    cannot_run = ("No module named pytest", "no tests ran")
    if result.startswith(("Permissão negada", "Execução de bash recusada")) or any(text in result for text in cannot_run):
        ui.console.print("[yellow]A verificação automática não pôde ser executada.[/yellow]")
        return None
    failed = result.startswith("Erro") or "[processo finalizado com código" in result
    if not failed:
        return None
    return (
        f"<system-reminder>A verificação automática falhou ({command}):\n{result[-3000:]}\n"
        "Corrija o problema e só então encerre.</system-reminder>"
    )


def run_request(
    ui: AgentUI,
    messages: list[dict[str, Any]],
    user_input: str,
    *,
    call_llm: Callable[..., tuple[Any, dict[str, Any], Any, Any]],
    reminder: Callable[[], dict[str, str]],
    active_todo: Callable[[], dict[str, str] | str],
    todos: Callable[[], str],
    has_open_todos: Callable[[], bool],
) -> tuple[list[dict[str, Any]], str]:
    """Run one user request until the model gives its final answer.

    Returns the updated messages and a status: "done", "error",
    "interrupted" or "turn_limit".
    """
    from collections import Counter

    max_turns = max(1, int(os.getenv("HARNEASY_MAX_TURNS_PER_REQUEST", "30")))
    max_tool_calls = max(1, int(os.getenv("HARNEASY_MAX_TOOL_CALLS_PER_TURN", "8")))
    repeat_limit = max(2, int(os.getenv("HARNEASY_REPEAT_TOOL_LIMIT", "3")))
    max_nudges = max(0, int(os.getenv("HARNEASY_MAX_NUDGES", "2")))
    final_review = os.getenv("HARNEASY_FINAL_REVIEW", "1") not in {"0", "false", "no"}
    auto_skills = os.getenv("HARNEASY_AUTO_SKILLS", "1") not in {"0", "false", "no"}
    split = os.getenv("HARNEASY_SPLIT_REQUEST", "1") not in {"0", "false", "no"}
    max_verifications = max(0, int(os.getenv("HARNEASY_MAX_VERIFY", "2")))

    content = user_input
    skill = suggest_skill(user_input) if auto_skills else None
    if skill:
        # Small models rarely read skills on their own, so the harness picks one.
        ui.console.print(f"[dim]skill: {skill}[/dim]")
        content += f"\n\n<skill name=\"{skill}\">\n{skill_body(skill)}\n</skill>\nSiga os passos desta skill."
    # Only for requests that picked a skill: a chat message has nothing to split.
    parts = split_request(call_llm, user_input) if skill and split else ""
    if parts:
        ui.console.print(f"[dim]partes do pedido:\n{parts}[/dim]")
        content += f"\n\nPartes do pedido (faça todas, uma por vez):\n{parts}"
    messages.append({"role": "user", "content": content})
    undo_mark = len(UNDO_STACK)
    edited_paths: set[str] = set()
    reviewed = False
    repeated_calls: Counter[str] = Counter()
    tool_calls_this_request = 0
    nudges = 0
    verifications = 0
    files_changed = False
    idle_limit = max(3, int(os.getenv("HARNEASY_IDLE_LIMIT", "6")))
    idle_calls = 0  # tool calls in a row without editing a file or updating the todo list
    idle_warned = False
    last_failed_tests: str | None = None
    last_search: dict | None = None  # the model's last grep; checked again before it finishes
    read_paths: set[str] = set()  # files read in this request; a first read is not wandering

    try:
        for turn in range(max_turns):
            try:
                todo = active_todo()
                label = todo.get("content", "thinking...") if isinstance(todo, dict) else todo
                view = StreamView(ui, label)
                with view:
                    env = reminder()
                    env = {**env, "content": env["content"] + f"\nturno: {turn + 1} de {max_turns}"}
                    message, usage, _, _ = call_llm(messages + [env], on_text=view.add)
                messages.append(message.model_dump(exclude_none=True))
            except Exception as error:
                ui.show_error(error)
                return messages, "error"

            if message.content:
                if not view.text:  # not streamed: show the whole answer now
                    ui.show_agent_message(message.content)
                ui.show_usage(usage or {})

            if not message.tool_calls:
                # The model stopped too early: remind it and let it continue.
                nudge = nudge_for(message.content, has_open_todos(), todos())
                if nudge and nudges < max_nudges:
                    nudges += 1
                    messages.append({"role": "user", "content": nudge})
                    continue
                # From here on, the harness checks the work instead of trusting "done".
                # 1) Problems visible without the model: bad syntax, missing modules or files.
                problems = pending_problems(edited_paths, user_input) if edited_paths else []
                if problems and nudges < max_nudges:
                    nudges += 1
                    messages.append({"role": "user", "content": (
                        "<system-reminder>Ainda há problemas:\n- " + "\n- ".join(problems)
                        + "\nCorrija antes de encerrar.</system-reminder>"
                    )})
                    continue
                if last_failed_tests and nudges < max_nudges:
                    nudges += 1
                    messages.append({"role": "user", "content": (
                        "<system-reminder>A última execução dos testes falhou e não foi repetida com sucesso:\n"
                        f"{last_failed_tests[-2000:]}\n"
                        "Corrija o código e rode os testes de novo antes de encerrar.</system-reminder>"
                    )})
                    continue
                # The model searched for something; does the search still find it?
                if last_search and files_changed and nudges < max_nudges:
                    still_found = execute_tool("grep", last_search)
                    last_search = None
                    if not still_found.startswith(("Nenhuma ocorrência", "Erro")):
                        nudges += 1
                        messages.append({"role": "user", "content": (
                            "<system-reminder>Sua última busca ainda encontra resultados:\n"
                            f"{still_found[:1500]}\n"
                            "Se eles deveriam ter mudado, corrija antes de encerrar.</system-reminder>"
                        )})
                        continue
                # 2) The project's tests.
                command = verify_command()
                if command and files_changed and verifications < max_verifications:
                    verifications += 1
                    files_changed = False
                    failure = run_verification(ui, command)
                    if failure:
                        messages.append({"role": "user", "content": failure})
                        continue
                # 3) One review of the request against the real diff.
                if final_review and edited_paths and not reviewed:
                    reviewed = True
                    messages.append({"role": "user", "content": (
                        f"<system-reminder>Revisão final. O pedido foi:\n{user_input}\n\n"
                        + (f"Partes do pedido:\n{parts}\n\n" if parts else "") +
                        f"Alterações feitas (diff real):\n{changes_since(undo_mark)}\n\n"
                        f"Arquivos como estão agora:\n{''.join(execute_tool('read_file', {'path': p})[:3000] for p in edited_paths)}\n\n"
                        "Compare o pedido com o diff e com os arquivos, item por item. Se faltar algo, continue usando as "
                        "ferramentas. Se estiver completo, responda só o resumo final.</system-reminder>"
                    )})
                    continue
                if has_open_todos():
                    ui.console.print(
                        "[yellow]A resposta terminou, mas ainda existem tarefas abertas no plano. "
                        "Revise a lista antes de considerar o trabalho concluído.[/yellow]"
                    )
                    ui.show_todos(todos())
                return messages, "done"

            reporter = lambda name, args, result: ui.show_tool_call(name, args, result)
            for call_index, tool_call in enumerate(message.tool_calls):
                name = tool_call.function.name
                try:
                    args = parse_arguments(tool_call.function.arguments)
                except ValueError as error:
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
                        if name in EDIT_TOOLS and not result.startswith("Erro"):
                            # The files changed, so running the same command again
                            # (e.g. the tests) is progress, not a loop.
                            repeated_calls.clear()
                            files_changed = True
                            edited_paths.add(args["path"])
                        if name == "bash" and "pytest" in str(args.get("command", "")):
                            failed = "[processo finalizado com código" in result
                            not_a_test_failure = "no tests ran" in result or "No module named pytest" in result
                            last_failed_tests = result if failed and not not_a_test_failure else None
                        if name == "grep" and not str(result).startswith("Erro"):
                            last_search = dict(args)
                made_progress = name in EDIT_TOOLS or name == "update_todos"
                new_file = name == "read_file" and args.get("path") not in read_paths
                if name == "read_file":
                    read_paths.add(args.get("path"))
                if made_progress and not str(result).startswith("Erro"):
                    idle_calls, idle_warned = 0, False
                elif not new_file:
                    idle_calls += 1

                ui.show_tool_call(name, args, result)
                if name == "update_todos":
                    ui.show_todos(todos())
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result),
                })

            # Wandering: many actions in a row and nothing changed.
            # Checked after the loop, so every tool call already has its result.
            if idle_calls >= 2 * idle_limit:
                ui.console.print(
                    f"[yellow]O agente fez {idle_calls} ações seguidas sem progresso e foi parado.[/yellow]"
                )
                return messages, "stuck"
            if idle_calls >= idle_limit and not idle_warned:
                idle_warned = True
                already_read = ", ".join(sorted(Path(p).name for p in read_paths)) or "nenhum"
                messages.append({"role": "user", "content": (
                    f"<system-reminder>Você fez {idle_calls} ações seguidas sem editar arquivos. "
                    f"Você já leu: {already_read}. Isso basta para começar. "
                    "Na PRÓXIMA resposta, chame write_file ou str_replace com a mudança pedida. "
                    "Se não for possível, explique o motivo e encerre.</system-reminder>"
                )})

            try:
                if needed(usage or {}, messages):
                    messages = compact(messages)
                    forget_reads()
            except Exception as error:
                # A summarizer failure should not destroy the active session.
                ui.show_error(RuntimeError(f"Falha ao compactar contexto; mantendo histórico atual: {error}"))
    except KeyboardInterrupt:
        # Ctrl+C cancels only the current request; the session stays usable.
        close_dangling_tool_calls(messages)
        ui.console.print("\n[yellow]Solicitação interrompida pelo usuário.[/yellow]")
        return messages, "interrupted"

    if has_open_todos():
        ui.console.print(
            f"[yellow]Limite de {max_turns} turnos atingido com tarefas pendentes. "
            "Envie uma instrução mais específica para continuar.[/yellow]"
        )
    else:
        ui.console.print(
            f"[yellow]Limite de {max_turns} turnos atingido para esta solicitação. "
            "O agente parou para evitar um loop infinito.[/yellow]"
        )
    return messages, "turn_limit"


def _run_startup_check(ui: AgentUI, startup_check: Callable[[], str | None] | None) -> None:
    if startup_check is None:
        return
    try:
        with ui.thinking(label="carregando modelo..."):
            warning = startup_check()
    except KeyboardInterrupt:
        warning = None
    if warning:
        ui.console.print(f"[yellow]{warning}[/yellow]\n")


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
    startup_check: Callable[[], str | None] | None = None,
) -> None:
    """Interactive shell: read a request, run it, repeat."""
    ui = AgentUI(model=model, tool_names=list(tools))
    ui.show_welcome(cwd=os.getcwd(), branch=branch)
    _run_startup_check(ui, startup_check)
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
            forget_reads()
            ui.console.clear()
            ui.show_welcome(cwd=os.getcwd(), branch=branch)
            continue
        if user_input == "/status":
            ui.show_status(message_count=len(messages), tool_count=len(tools))
            continue
        if user_input == "/undo":
            from .tools import undo_last_edit
            result = undo_last_edit()
            ui.console.print(f"[yellow]{result}[/yellow]")
            # Tell the model, otherwise it keeps assuming its edit is in place.
            messages.append({"role": "user", "content": f"<system-reminder>O usuário desfez sua última edição. {result}</system-reminder>"})
            continue

        messages, _ = run_request(
            ui, messages, user_input,
            call_llm=call_llm, reminder=reminder, active_todo=active_todo,
            todos=todos, has_open_todos=has_open_todos,
        )


def run_headless(
    prompt: str,
    *,
    system_prompt: str,
    call_llm: Callable[..., tuple[Any, dict[str, Any], Any, Any]],
    tools: dict[str, Callable[..., str]],
    reminder: Callable[[], dict[str, str]],
    model: str,
    active_todo: Callable[[], dict[str, str] | str],
    todos: Callable[[], str],
    has_open_todos: Callable[[], bool],
    approve_all: bool = False,
    startup_check: Callable[[], str | None] | None = None,
) -> int:
    """Run a single request without prompts (-p mode). Returns a process exit code."""
    ui = AgentUI(model=model, tool_names=list(tools), auto_confirm=approve_all)
    _run_startup_check(ui, startup_check)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    _, status = run_request(
        ui, messages, prompt,
        call_llm=call_llm, reminder=reminder, active_todo=active_todo,
        todos=todos, has_open_todos=has_open_todos,
    )
    return 0 if status == "done" else 1
