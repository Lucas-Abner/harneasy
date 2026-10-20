"""Tool definitions and the single execution gateway used by every agent."""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .permissions import PROJECT_ROOT, check, decide, register_generated_output
from .sandbox import run as sandbox_run
from .skills import read_skill
from .todos import write_todos
from .subagents import TASK_SCHEMA, task

MAX_TOOL_OUTPUT_CHARS = max(1000, int(os.getenv("HARNEASY_MAX_TOOL_OUTPUT_CHARS", "6000")))


def _bounded_output(value: Any) -> str:
    text = value if isinstance(value, str) else str(value)
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text

    # Preserve the complete output for targeted follow-up reads rather than
    # flooding the model's context window with thousands of irrelevant lines.
    fd, filename = tempfile.mkstemp(prefix="harneasy-output-", suffix=".txt", text=True)
    with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as handle:
        handle.write(text)
    register_generated_output(filename)

    marker = (
        f"\n\n[Saída reduzida: {len(text)} caracteres no total. "
        f"A saída completa foi salva em {filename}. Use read_file com start_line/max_lines para consultar trechos.]\n\n"
    )
    available = max(0, MAX_TOOL_OUTPUT_CHARS - len(marker))
    head_size = available // 2
    tail_size = available - head_size
    return text[:head_size] + marker + (text[-tail_size:] if tail_size else "")


def bash(command: str) -> str:
    if not isinstance(command, str) or not command.strip():
        return "Erro: o comando deve ser uma string não vazia."

    timeout = int(os.getenv("HARNEASY_COMMAND_TIMEOUT", "60"))
    is_powershell = command.lstrip().lower().startswith("powershell ")
    if os.name == "nt":
        if os.getenv("HARNEASY_REQUIRE_SANDBOX", "0").lower() in {"1", "true", "yes"}:
            return (
                "Comando bloqueado: o modo HARNEASY_REQUIRE_SANDBOX está ativo, "
                "mas o executor PowerShell ainda não possui isolamento de sistema operacional."
            )
        powershell_command = command.lstrip()[len("powershell"):].strip() if is_powershell else command
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", powershell_command],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    elif is_powershell:
        return "Erro: comandos PowerShell só podem ser executados no Windows."
    else:
        result = sandbox_run(command, timeout=timeout)

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        output += f"\n[processo finalizado com código {result.returncode}]"
    return output or f"[comando finalizado com código {result.returncode}, sem saída]"


def read_file(path: str, start_line: int = 1, max_lines: int = 120) -> str:
    """Read a file or a targeted line range to avoid flooding model context."""
    if start_line < 1:
        raise ValueError("start_line precisa ser maior ou igual a 1.")
    if max_lines < 1:
        raise ValueError("max_lines precisa ser maior ou igual a 1.")
    max_lines = min(max_lines, 500)
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    from .context import note_read
    selected: list[str] = []
    total_lines = 0
    range_end = start_line + max_lines - 1
    # Count lines while retaining only the requested window, so an enormous
    # log never has to be materialized as one Python list in memory.
    with resolved.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            total_lines = line_number
            if start_line <= line_number <= range_end:
                selected.append(line)
    if not is_generated_output_path(resolved):
        note_read(resolved)
    end_line = start_line + len(selected) - 1
    header = f"[Arquivo: {resolved} | linhas {start_line}-{max(start_line - 1, end_line)} de {total_lines}]\n"
    content = "".join(selected)
    if end_line < total_lines:
        content += f"\n[Há mais linhas. Continue com start_line={end_line + 1}, max_lines={max_lines}.]\n"
    return header + content


def is_generated_output_path(path: str | os.PathLike[str]) -> bool:
    from .permissions import is_generated_output
    return is_generated_output(path)


def write_file(path: str, conteudo: str) -> str:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    if not isinstance(conteudo, str):
        raise TypeError("'conteudo' precisa ser uma string.")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(conteudo, encoding="utf-8")
    return f"Arquivo escrito: {resolved} ({len(conteudo)} caracteres)."


def str_replace(path: str, old: str, new: str, allow_multi_edit: bool = False) -> str:
    if not old:
        return "Erro: a string antiga não pode ser vazia."

    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    resolved = resolved.resolve()
    content = resolved.read_text(encoding="utf-8", errors="replace")
    count = content.count(old)

    if count == 0:
        return f"Erro: texto não encontrado em {resolved}."
    if count > 1 and not allow_multi_edit:
        return (
            f"Erro: o texto aparece {count} vezes em {resolved}. "
            "Informe allow_multi_edit=true para substituir todas as ocorrências."
        )

    resolved.write_text(content.replace(old, new), encoding="utf-8")
    noun = "ocorrência" if count == 1 else "ocorrências"
    return f"Substituído {count} {noun} em {resolved}."


def update_todos(todos: list[dict[str, str]]) -> str:
    return str(write_todos(todos))


def execute_tool(
    name: str,
    args: dict[str, Any],
    *,
    confirm: Callable[[str], bool] | None = None,
    readonly: bool = False,
    reporter: Callable[[str, dict[str, Any], str], None] | None = None,
) -> str:
    """Validate, authorize and execute a tool through one consistent gateway."""
    if not isinstance(args, dict):
        return "Erro: os argumentos da ferramenta precisam ser um objeto JSON."
    if name not in TOOLS:
        return f"Erro: ferramenta desconhecida: {name}."
    if readonly and name not in {"bash", "read_file", "read_skill"}:
        return f"Permissão negada: o modo somente leitura não permite a ferramenta {name}."

    function = TOOLS[name]
    try:
        inspect.signature(function).bind(**args)
    except TypeError as error:
        return f"Erro nos argumentos da ferramenta {name}: {error}"

    action, reason = check(name, args)
    if name == "bash" and readonly:
        # Subagents must not use a broad allow/ask policy to obtain write access.
        action = decide(args["command"], readonly=True)
        reason = f"comando de exploração: {args['command']}"

    if action == "deny":
        return f"Permissão negada para executar {name}. Motivo: {reason or 'política de segurança'}."
    if action == "ask":
        if confirm is None or not confirm(reason or f"executar ferramenta {name}"):
            return f"Execução de {name} recusada: requer aprovação explícita. Motivo: {reason}."

    try:
        if name == "task":
            result = function(**args, confirm=confirm, reporter=reporter)
        else:
            result = function(**args)
    except subprocess.TimeoutExpired as error:
        result = f"Erro: o comando excedeu o limite de {error.timeout} segundos e foi encerrado."
    except Exception as error:  # A tool error should be returned to the model for recovery.
        result = f"Erro na ferramenta {name}: {type(error).__name__}: {error}"

    return _bounded_output(result)


def execute(tool_call, *, confirm=None, reporter=None, readonly: bool = False) -> tuple[dict[str, Any], str]:
    """Compatibility wrapper used by subagents; always return (args, result)."""
    name = getattr(getattr(tool_call, "function", None), "name", "")
    raw_arguments = getattr(getattr(tool_call, "function", None), "arguments", "{}")
    try:
        args = json.loads(raw_arguments or "{}")
    except (TypeError, json.JSONDecodeError) as error:
        return {}, f"Erro ao analisar argumentos da ferramenta {name}: {error}"
    if not isinstance(args, dict):
        return {}, "Erro ao analisar argumentos: esperado um objeto JSON."
    result = execute_tool(name, args, confirm=confirm, reporter=reporter, readonly=readonly)
    if reporter:
        try:
            reporter(name, args, result)
        except Exception:
            pass
    return args, result


TOOLS_SCHEMAS = [
    {
        'type': 'function',
        'function': {
            'name': 'bash',
            'description': 'Execute um comando de shell permitido e retorne stdout/stderr e o código de saída.',
            'parameters': {
            'type': 'object',
            'properties': {
                'command': {
                    'type': 'string',
                    'description': 'Comando a executar. Comandos desconhecidos pedem aprovação e comandos bloqueados não são executados.',
                }
            },
            'required': ['command'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Leia o conteúdo de um arquivo e retorne como uma string.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'Caminho do arquivo. Arquivos longos podem ser lidos em intervalos de linhas.',
                    },
                    'start_line': {
                        'type': 'integer',
                        'minimum': 1,
                        'description': 'Primeira linha a ler (padrão: 1).',
                    },
                    'max_lines': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': 500,
                        'description': 'Quantidade máxima de linhas (padrão: 120).',
                    },
                },
                'required': ['path'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_skill',
            'description': 'Leia as instruções de uma skill instalada pelo nome.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'O nome da skill.',
                    }
                },
                'required': ['name'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_file',
            'description': 'Crie ou sobrescreva um arquivo dentro do workspace atual.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'O caminho do arquivo a ser escrito.',
                    },
                    'conteudo': {
                        'type': 'string',
                        'description': 'O conteúdo a ser escrito no arquivo.',
                    }
                },
                'required': ['path', 'conteudo'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'str_replace',
            'description': 'Substitua texto em um arquivo. Se houver várias ocorrências, peça allow_multi_edit=true explicitamente.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'O caminho do arquivo a ser modificado.',
                    },
                    'old': {
                        'type': 'string',
                        'description': 'A string antiga a ser substituída.',
                    },
                    'new': {
                        'type': 'string',
                        'description': 'A nova string que substituirá a antiga.',
                    },
                    'allow_multi_edit': {
                        'type': 'boolean',
                        'description': (
                            "Permitir substituição de múltiplas ocorrências. "
                            "Se False, apenas uma ocorrência será substituída."
                        ),
                    }
                },
                'required': ['path', 'old', 'new'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_todos',
            'description': 'Atualize a lista de tarefas da sessão. Use no máximo uma tarefa in_progress.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'todos': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'status': {
                                    'type': 'string',
                                    'enum': ['pending', 'in_progress', 'done'],
                                },
                                'content': {'type': 'string'},
                            },
                            'required': ['status', 'content'],
                        },
                    }
                },
                'required': ['todos'],
            }
        }
    },
    TASK_SCHEMA
]

TOOLS = {
    'bash': bash,
    'read_file': read_file,
    'read_skill': read_skill,
    'write_file': write_file,
    'str_replace': str_replace,
    'update_todos': update_todos,
    'task': task,
}
# Backwards-compatible alias: subagent implementations in earlier revisions
# imported this singular spelling.
TOOL_SCHEMAS = TOOLS_SCHEMAS
