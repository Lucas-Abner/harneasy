"""Tool definitions and the single execution gateway used by every agent."""
from __future__ import annotations

import ast
import difflib
import importlib.util
import inspect
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable

import yaml

from .codeindex import code_map, search_code, walk_files
from .context import SEEN, note_read
from .permissions import PROJECT_ROOT, check, decide, register_generated_output
from .repair import parse_arguments
from . import sandbox
from .sandbox import run as sandbox_run
from .skills import read_skill
from .todos import write_todos
from .subagents import TASK_SCHEMA, task
from .permissions import resolve_path

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


def _file_read_by(command: str) -> tuple[str, int] | None:
    if any(symbal in command for symbal in "|;&<>$`"):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts or parts[0] not in {'cat', 'head', 'sed'}:
        return None

    words = [part for part in parts[1:] if not part.startswith('-') and not part.isdigit()]
    start = 1
    if parts[0] == 'sed':
        if not words:
            return None
        script, words = words[0], words[1:]
        match = re.match(r'(\d+)', script)
        start = int(match.group(1)) if match else 1
    return (words[0], start) if len(words) == 1 else None

INSTALL = r"\b(npm|pnpm|yarn)\s+(install|i|add|ci)\b|\bnpx\b|\bpip3?\s+install\b|\buv\s+(add|sync|pip\s+install)\b"
GLOBAL_INSTALL = r"\b(npm|pnpm|yarn)\s+(install|i|add)\b.*\s(-g|--global)\b|\bpip3?\s+install\b.*\s--user\b"


def _impossible_command(command: str) -> str | None:
    """Explain why a command cannot work here, instead of letting the model retry it."""
    reason = None
    if re.search(r"\bnohup\b|&\s*$|&\s*\n", command):
        reason = "processos em segundo plano não são suportados. Rode o comando normalmente"
    elif re.search(GLOBAL_INSTALL, command):
        reason = "instale só dentro do projeto (sem -g ou --user)"
    elif re.search(INSTALL, command) and not sandbox.network_enabled():
        reason = (
            "a rede está desligada (HARNEASY_SANDBOX_NETWORK=0), então instalar pacotes "
            "não funciona. Use só o que já está instalado"
        )
    elif re.search(r"\bgit\s+clone\b|\bapt(-get)?\b", command):
        reason = "este comando não é permitido aqui"
    if reason is None:
        return None
    return (
        f"Erro: {reason}. Não tente variações deste comando. Se não for possível "
        "verificar algo neste ambiente, diga isso na resposta final e encerre."
    )


def bash(command: str) -> str:
    if not isinstance(command, str) or not command.strip():
        return "Erro: o comando deve ser uma string não vazia."  
    read = _file_read_by(command)

    if read:
        notice = _repeated_read_notice({'path': read[0], 'start_line': read[1]})
        if notice:
            return notice
                
    timeout = int(os.getenv("HARNEASY_COMMAND_TIMEOUT", "60"))
    if re.search(INSTALL, command):
        timeout = max(timeout, 300)  # downloads are slow; 60s killed npm install
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
    resolved = resolve_path(path)
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


def _resolve(path: str) -> Path:
    return resolve_path(path)



# Every edit saves (file, previous content) here so /undo can restore it.
# A previous content of None means the edit created the file.
UNDO_STACK: list[tuple[Path, str | None]] = []
MAX_UNDO = 50
MAX_DIFF_LINES = 40


def _require_fresh_read(resolved: Path) -> str | None:
    """Return an error unless an existing file was read and is unchanged since."""
    if not resolved.exists():
        return None
    read_mtime = SEEN.get(str(resolved))
    if read_mtime is None:
        content = read_file(str(resolved))
        return (
            f"Erro: você ainda não tinha lido {resolved}; edição não aplicada. "
            f"Conteúdo atual abaixo. Confira e REPITA a mesma chamada.\n{content}"
            )
    if resolved.stat().st_mtime > read_mtime:
        return f"Erro: {resolved} mudou desde a última leitura. Chame read_file nele de novo e depois repita a edição."
    return None


COMMENTS = re.compile(r'<!--.*?-->|/\*.*?\*/|//[^\n]*|#[^\n]*', re.DOTALL)


def _only_cosmetic(before: str, after: str) -> bool:
    def bare(text: str) -> str:
        return "".join(COMMENTS.sub("", text).split())

    return before != after and bare(before) == bare(after)


def _short_diff(old_text: str, new_text: str) -> str:
    if _only_cosmetic(old_text, new_text):
        return (
            "\n[Aviso: esta edição só mudou comentários ou espaços; o código ficou igual. "
            "O pedido ainda não foi feito. Faça a mudança real, uma parte por vez.]"
        )
    lines = list(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), lineterm="", n=1,
    ))[2:]  # skip the ---/+++ header
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... (+{len(lines) - MAX_DIFF_LINES} linhas de diff)"]
    return "\n" + "\n".join(lines) if lines else ""


def _is_local_module(name: str, near: Path) -> bool:
    """Whether 'import name' refers to a file or package of the project itself."""
    for folder in (near.parent, PROJECT_ROOT, PROJECT_ROOT / "src"):
        if (folder / f"{name}.py").exists() or (folder / name).is_dir():
            return True
    return False


def _missing_imports(tree: ast.AST, resolved: Path) -> list[str]:
    """Top-level modules imported by the file that cannot be found anywhere."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    missing = []
    for name in sorted(names):
        if name in sys.stdlib_module_names or _is_local_module(name, resolved):
            continue
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing

def _unimported_modules(text: str) -> list[str]:
    """Standard modules used as `re.sub(...)` but never imported."""
    used = set(re.findall(r"\b([a-z_]+)\.", text))
    return sorted(name for name in used & sys.stdlib_module_names
              if not re.search(rf"^\s*(import|from)\s.*\b{name}\b", text, re.MULTILINE))


def _syntax_warning(resolved: Path) -> str:
    """Check the syntax of common file types right after an edit."""
    text = resolved.read_text(encoding="utf-8", errors="replace")
    suffix = resolved.suffix.lower()
    try:
        if suffix == ".py":
            tree = ast.parse(text, filename=str(resolved))
            unimported = _unimported_modules(text)
            if unimported:
                imports = "; ".join(f"import {name}" for name in unimported)
                return f"\n[Aviso: o código usa {', '.join(unimported)} sem importar. Acrescente no topo: {imports}]"
            missing = _missing_imports(tree, resolved)
            if missing:
                advice = (
                    "instale com `uv add` se precisar deles" if sandbox.network_enabled()
                    else "não há rede para instalá-los; use a biblioteca padrão"
                )
                return f"\n[Aviso: módulos não instalados: {', '.join(missing)}. {advice[0].upper()}{advice[1:]}.]"
        elif suffix == ".json":
            json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            yaml.safe_load(text)
        elif suffix == ".toml":
            tomllib.loads(text)
    except SyntaxError as error:
        return f"\n[Aviso: erro de sintaxe Python na linha {error.lineno}: {error.msg}. Corrija o arquivo.]"
    except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as error:
        return f"\n[Aviso: o arquivo {suffix} ficou inválido: {error}. Corrija o arquivo.]"
    return ""


def _save_edit(resolved: Path, new_text: str, summary: str) -> str:
    """Write the file, remember it for /undo and report diff + syntax problems."""
    old_text = resolved.read_text(encoding="utf-8", errors="replace") if resolved.exists() else None
    UNDO_STACK.append((resolved, old_text))
    del UNDO_STACK[:-MAX_UNDO]
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(new_text, encoding="utf-8")
    note_read(resolved)  # our own edit must not make the next edit look stale
    diff = _short_diff(old_text, new_text) if old_text is not None else ""
    return summary + diff + _syntax_warning(resolved)


# Source files the user may name in a request ("crie slugify.py").
# Data files like tarefas.json are left out: programs often create them at runtime.
MENTIONED_FILE = re.compile(r"\b[\w./-]+\.(?:py|js|jsx|ts|tsx|html|css|go|rs|java|rb|php)\b")


def pending_problems(edited: set[str], request: str) -> list[str]:
    """Problems the harness can see by itself before accepting "done"."""
    problems = []
    for path in sorted(edited):
        resolved = _resolve(path)
        warning = _syntax_warning(resolved) if resolved.exists() else ""
        if warning:
            problems.append(f"{_display(resolved)}: {warning.strip()}")
    existing = {file.name for file in walk_files(PROJECT_ROOT)}
    for mentioned in sorted(set(MENTIONED_FILE.findall(request))):
        if Path(mentioned).name not in existing:
            problems.append(f"O pedido cita {mentioned}, mas esse arquivo não existe no projeto.")
    return problems


def changes_since(mark: int, max_chars: int = 3000) -> str:
    """Diff of every file edited since UNDO_STACK had `mark` entries."""
    originals: dict[Path, str | None] = {}
    for path, old_text in UNDO_STACK[mark:]:
        originals.setdefault(path, old_text)  # the first entry holds the original
    parts = []
    for path, old_text in originals.items():
        new_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if old_text is None:
            parts.append(f"{_display(path)} (novo arquivo, {len(new_text.splitlines())} linhas)")
        else:
            parts.append(f"{_display(path)}:{_short_diff(old_text, new_text)}")
    text = "\n".join(parts)
    return text[:max_chars] + ("\n[... diff reduzido]" if len(text) > max_chars else "")


def undo_last_edit() -> str:
    """Restore the file changed by the most recent edit."""
    if not UNDO_STACK:
        return "Nada para desfazer."
    resolved, old_text = UNDO_STACK.pop()
    if old_text is None:
        resolved.unlink(missing_ok=True)
        return f"Desfeito: {resolved} foi removido (tinha sido criado pelo agente)."
    resolved.write_text(old_text, encoding="utf-8")
    note_read(resolved)
    return f"Desfeito: {resolved} voltou ao conteúdo anterior."


def write_file(path: str, content: str) -> str:
    resolved = _resolve(path)
    if not isinstance(content, str):
        raise TypeError("'content' precisa ser uma string.")
    if resolved.exists() and len(resolved.read_text(encoding="utf-8").splitlines()) > 30:
        return f"Erro: {resolved} tem mais de 30 linhas. Use str_replace para editar só o trecho necessário."
    error = _require_fresh_read(resolved)
    if error:
        return error
    action = "sobrescrito" if resolved.exists() else "novo arquivo"
    return _save_edit(resolved, content, f"Arquivo escrito: {resolved} ({len(content)} caracteres, {action}).")


def _find_line_matches(lines: list[str], old_lines: list[str], normalize: Callable[[str], str]) -> list[int]:
    """Return every line index where old_lines matches the file after normalize()."""
    target = [normalize(line) for line in old_lines]
    size = len(old_lines)
    return [
        start for start in range(len(lines) - size + 1)
        if [normalize(line) for line in lines[start:start + size]] == target
    ]


def _reindent(new_lines: list[str], old_first: str, file_first: str) -> list[str]:
    """Shift new_lines from the indentation the model used to the file's real one."""
    old_indent = old_first[:len(old_first) - len(old_first.lstrip())]
    file_indent = file_first[:len(file_first) - len(file_first.lstrip())]
    result = []
    for line in new_lines:
        if line.strip() and line.startswith(old_indent):
            result.append(file_indent + line[len(old_indent):])
        else:
            result.append(line)
    return result


def _closest_snippet(lines: list[str], old_lines: list[str]) -> str:
    """Show the part of the file most similar to old_lines, with line numbers."""
    size = len(old_lines)
    target = "\n".join(line.strip() for line in old_lines)
    best_ratio, best_start = 0.0, 0
    for start in range(max(1, len(lines) - size + 1)):
        window = "\n".join(line.strip() for line in lines[start:start + size])
        ratio = difflib.SequenceMatcher(None, target, window).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, start
    if best_ratio < 0.5:
        return ""
    numbered = "\n".join(
        f"{number:>5}  {line}"
        for number, line in enumerate(lines[best_start:best_start + size], start=best_start + 1)
    )
    return f"\nO trecho mais parecido está nas linhas {best_start + 1}-{best_start + size}:\n{numbered}"


def str_replace(path: str, old_str: str, new_str: str, allow_multi_edit: bool = False) -> str:
    if not old_str:
        return (
            "Erro: a string antiga não pode ser vazia. Para adicionar texto, use como old_str a linha "
            "que vem antes e repita essa linha no new_str, com a novidade embaixo."
        )

    resolved = _resolve(path)
    error = _require_fresh_read(resolved)
    if error:
        return error
    content = resolved.read_text(encoding="utf-8", errors="replace")
    old_str = old_str.replace("\r\n", "\n")
    new_str = new_str.replace("\r\n", "\n")

    # 1. Exact match.
    count = content.count(old_str)
    if count > 1 and not allow_multi_edit:
        return (
            f"Erro: o texto aparece {count} vezes em {resolved}. "
            "Copie também a linha de cima ou de baixo para o trecho ficar único. "
            "Se quiser trocar todas, use allow_multi_edit=true."
        )
    if count >= 1:
        noun = "ocorrência" if count == 1 else "ocorrências"
        return _save_edit(resolved, content.replace(old_str, new_str), f"Substituído {count} {noun} em {resolved}.")

    # 2. Small models often get whitespace wrong: retry line by line, first
    # ignoring trailing spaces, then ignoring indentation. Only a unique match
    # is applied; anything fuzzier than whitespace is reported, never applied.
    lines = content.split("\n")
    old_lines = old_str.strip("\n").split("\n")
    new_lines = new_str.strip("\n").split("\n") if new_str.strip("\n") else []
    strategies = [
        ("ignorando espaços no fim das linhas", str.rstrip),
        ("ignorando diferenças de indentação", str.strip),
    ]
    for label, normalize in strategies:
        matches = _find_line_matches(lines, old_lines, normalize)
        if len(matches) > 1:
            return (
                f"Erro: o texto aparece {len(matches)} vezes em {resolved} ({label}). "
                "Copie também a linha de cima ou de baixo para o trecho ficar único."
            )
        if len(matches) == 1:
            start = matches[0]
            replacement = new_lines
            if normalize is str.strip:
                first = next((i for i, line in enumerate(old_lines) if line.strip()), 0)
                replacement = _reindent(new_lines, old_lines[first], lines[start + first])
            lines[start:start + len(old_lines)] = replacement
            return _save_edit(
                resolved, "\n".join(lines), f"Substituído 1 ocorrência em {resolved} ({label}, linha {start + 1})."
            )

    # 3. No match: show the closest snippet so the model can fix its next try.
    return (
        f"Erro: texto não encontrado em {resolved}. Copie old_str exatamente do arquivo, sem os números das linhas."
        + _closest_snippet(lines, old_lines)
    )


MAX_SEARCH_RESULTS = 100
MAX_GREP_FILE_BYTES = 1_000_000


def _matches_glob(relative: str, pattern: str) -> bool:
    """'*.py' matches by file name anywhere; 'src/**/*.py' matches the path."""
    if "/" not in pattern:
        return fnmatch(Path(relative).name, pattern)
    # '**/' may match zero folders: 'src/**/*.py' must also find 'src/app.py'.
    return fnmatch(relative, pattern) or fnmatch(relative, pattern.replace("**/", ""))


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def glob_files(pattern: str, path: str = ".") -> str:
    base = _resolve(path)
    found = [
        _display(file) for file in walk_files(base)
        if _matches_glob(str(file.relative_to(base)), pattern)
    ]
    if not found:
        return f"Nenhum arquivo corresponde a '{pattern}' em {_display(base)}."
    extra = f"\n[... e mais {len(found) - MAX_SEARCH_RESULTS} arquivos. Use um padrão mais específico.]" if len(found) > MAX_SEARCH_RESULTS else ""
    return "\n".join(found[:MAX_SEARCH_RESULTS]) + extra


def grep(pattern: str, path: str = ".", include: str | None = None, ignore_case: bool = False) -> str:
    try:
        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as error:
        return f"Erro: expressão regular inválida: {error}. Para buscar o texto literal, coloque \\ antes de ( ) [ ] . * + ?"
    base = _resolve(path)
    files = [base] if base.is_file() else walk_files(base)
    matches: list[str] = []
    for file in files:
        if include and not _matches_glob(file.name if base.is_file() else str(file.relative_to(base)), include):
            continue
        try:
            if file.stat().st_size > MAX_GREP_FILE_BYTES:
                continue
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or binary file
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{_display(file)}:{number}: {line.strip()[:200]}")
                if len(matches) >= MAX_SEARCH_RESULTS:
                    return "\n".join(matches) + "\n[Limite de resultados atingido. Refine a busca.]"
    return "\n".join(matches) if matches else f"Nenhuma ocorrência de '{pattern}'."


def list_dir(path: str = ".") -> str:
    base = _resolve(path)
    if not base.is_dir():
        return f"Erro: {base} não é um diretório. Se for um arquivo, use read_file; para achar a pasta, use glob."
    entries = sorted(base.iterdir(), key=lambda item: (not item.is_dir(), item.name))
    lines = []
    for item in entries[:MAX_SEARCH_RESULTS]:
        if item.is_dir():
            lines.append(f"{item.name}/")
        else:
            lines.append(f"{item.name}  ({item.stat().st_size} bytes)")
    if len(entries) > MAX_SEARCH_RESULTS:
        lines.append(f"[... e mais {len(entries) - MAX_SEARCH_RESULTS} itens]")
    return f"[{_display(base)}]\n" + ("\n".join(lines) or "(vazio)")


def update_todos(todos: list[dict[str, str]]) -> str:
    return str(write_todos(todos))


JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _coerce(value: Any, expected: str) -> Any:
    """Repair the scalar type slips small models make, e.g. ``"10"`` for 10."""
    if expected == "integer":
        if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
            return int(value)
        if isinstance(value, float) and value.is_integer():
            return int(value)
    elif expected == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    elif expected == "boolean" and isinstance(value, str):
        return {"true": True, "false": False}.get(value.strip().lower(), value)
    elif expected in {"array", "object"} and isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed if isinstance(parsed, JSON_TYPES[expected]) else value
    elif expected == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value


def _matches(value: Any, expected: str) -> bool:
    if isinstance(value, bool) and expected in {"integer", "number"}:
        return False
    return isinstance(value, JSON_TYPES.get(expected, (object,)))


# Names models commonly use for our arguments (canonical name -> aliases).
ARG_ALIASES = {
    "path": ["file_path", "filepath", "filename", "file"],
    "content": ["conteudo", "contents", "text", "file_text"],
    "old_str": ["old", "old_string", "old_text"],
    "new_str": ["new", "new_string", "new_text"],
    "command": ["cmd"],
}


def _schema_properties(name: str) -> dict[str, Any]:
    schema = next((s["function"] for s in TOOLS_SCHEMAS if s["function"]["name"] == name), None)
    return (schema or {}).get("parameters", {}).get("properties", {})


def normalize_arg_names(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Rename known aliases and drop arguments the tool does not have.

    Returns (args, ignored argument names).
    """
    properties = _schema_properties(name)
    normalized = dict(args)
    for canonical, aliases in ARG_ALIASES.items():
        if canonical not in properties or canonical in normalized:
            continue
        for alias in aliases:
            if alias in normalized:
                normalized[canonical] = normalized.pop(alias)
                break
    ignored = [key for key in normalized if key not in properties]
    for key in ignored:
        normalized.pop(key)
    return normalized, ignored


def coerce_args(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Coerce top-level arguments to the tool schema; return an error if impossible."""
    properties = _schema_properties(name)
    coerced = dict(args)
    for key, spec in properties.items():
        expected = spec.get("type")
        if key not in coerced or expected not in JSON_TYPES:
            continue
        value = _coerce(coerced[key], expected)
        if not _matches(value, expected):
            shown = json.dumps(coerced[key], ensure_ascii=False, default=str)[:80]
            return args, (
                f"Erro nos argumentos da ferramenta {name}: '{key}' precisa ser do tipo "
                f"{expected}, mas recebeu {type(coerced[key]).__name__}: {shown}"
            )
        coerced[key] = value
    return coerced, None


# Reads done by the main agent: (path, start_line, max_lines) -> file mtime.
# Cleared after compaction, because the old content leaves the context then.
RECENT_READS: dict[tuple[str, int, int], float] = {}


def forget_reads() -> None:
    RECENT_READS.clear()


def _repeated_read_notice(args: dict[str, Any]) -> str | None:
    """Stop the model from reading the same unchanged lines again and again."""
    path = str(_resolve(args["path"]))
    start = args.get("start_line", 1)
    end = start + args.get("max_lines", 120) - 1
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return None
    seen_mtime, ranges, repeats = RECENT_READS.get(path, (None, [], 0))
    if seen_mtime != mtime:
        RECENT_READS[path] = (mtime, [(start, end)], 0)  # first read, or the file changed
        return None
    if not any(first <= start <= last for first, last in ranges):
        ranges.append((start, end))  # a new part of the file: paging is fine
        return None
    repeats += 1
    RECENT_READS[path] = (mtime, ranges, repeats)
    if repeats == 1:
        return (
            f"[Você já leu {path} (a partir da linha {start}) e ele não mudou. O conteúdo está acima "
            "na conversa. Use o que já leu e faça a próxima ação (editar, rodar, ou responder).]"
        )
    if repeats >= 3:
        return f"[{path} já foi lido várias vezes sem mudar. Não leia de novo: edite-o ou encerre.]"
    return None  # 2nd repeat: send it, the old content may have scrolled too far


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
    if readonly and name not in {"bash", "read_file", "read_skill", "grep", "glob", "list_dir", "code_map", "search_code"}:
        return f"Permissão negada: o modo somente leitura não permite a ferramenta {name}."

    args, ignored = normalize_arg_names(name, args)
    args, type_error = coerce_args(name, args)
    if type_error:
        return type_error

    function = TOOLS[name]
    try:
        inspect.signature(function).bind(**args)
    except TypeError as error:
        return f"Erro nos argumentos da ferramenta {name}: {error}"

    if name == "bash":
        # Checked before asking permission: the user should not approve what cannot work.
        impossible = _impossible_command(args["command"])
        if impossible:
            return impossible

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

    if name == "read_file" and not readonly:
        # Subagents have their own fresh context, so the notice is main-agent only.
        notice = _repeated_read_notice(args)
        if notice:
            return notice

    try:
        if name == "task":
            result = function(**args, confirm=confirm, reporter=reporter)
        else:
            result = function(**args)
    except subprocess.TimeoutExpired as error:
        result = (
            f"Erro: o comando excedeu o limite de {error.timeout} segundos e foi encerrado. "
            "Não rode servidores nem comandos que esperam entrada; use um comando que termine sozinho."
        )
    except Exception as error:  # A tool error should be returned to the model for recovery.
        result = f"Erro na ferramenta {name}: {type(error).__name__}: {error}"

    if ignored:
        result = f"{result}\n[Aviso: argumentos desconhecidos ignorados: {', '.join(ignored)}]"
    return _bounded_output(result)


def execute(tool_call, *, confirm=None, reporter=None, readonly: bool = False) -> tuple[dict[str, Any], str]:
    """Compatibility wrapper used by subagents; always return (args, result)."""
    name = getattr(getattr(tool_call, "function", None), "name", "")
    raw_arguments = getattr(getattr(tool_call, "function", None), "arguments", "{}")
    try:
        args = parse_arguments(raw_arguments)
    except ValueError as error:
        return {}, f"Erro ao analisar argumentos da ferramenta {name}: {error}"
    result = execute_tool(name, args, confirm=confirm, reporter=reporter, readonly=readonly)
    if reporter:
        try:
            reporter(name, args, result)
        except Exception:
            pass
    return args, result


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """Build an OpenAI tool schema. Descriptions stay short: every word costs context."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


STRING = {"type": "string"}

TOOLS_SCHEMAS = [
    _tool("bash", "Executa um comando de shell e retorna a saída e o código de saída.",
          {"command": STRING}, ["command"]),
    _tool("read_file", "Lê um arquivo. Use start_line/max_lines para arquivos longos.",
          {"path": STRING,
           "start_line": {"type": "integer", "minimum": 1},
           "max_lines": {"type": "integer", "minimum": 1, "maximum": 500}},
          ["path"]),
    _tool("read_skill", "Lê as instruções de uma skill pelo nome.", {"name": STRING}, ["name"]),
    _tool("write_file", "Cria um arquivo ou reescreve um arquivo de até 30 linhas. Para arquivos maiores, use str_replace.",
          {"path": STRING, "content": STRING}, ["path", "content"]),
    _tool("str_replace", "Substitui old_str por new_str em um arquivo. old_str deve ser único e copiado do arquivo.",
          {"path": STRING, "old_str": STRING, "new_str": STRING,
           "allow_multi_edit": {"type": "boolean", "description": "Substituir todas as ocorrências."}},
          ["path", "old_str", "new_str"]),
    _tool("update_todos", "Atualiza a lista de tarefas. No máximo uma in_progress.",
          {"todos": {"type": "array", "items": {
              "type": "object",
              "properties": {"status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                             "content": STRING},
              "required": ["status", "content"]}}},
          ["todos"]),
    _tool("grep", "Busca uma regex no conteúdo dos arquivos. Retorna arquivo:linha: texto.",
          {"pattern": STRING, "path": STRING,
           "include": {"type": "string", "description": "Filtro de arquivos, ex: *.py"},
           "ignore_case": {"type": "boolean"}},
          ["pattern"]),
    _tool("glob", "Encontra arquivos pelo nome, ex: *.py ou src/**/test_*.py",
          {"pattern": STRING, "path": STRING}, ["pattern"]),
    _tool("list_dir", "Lista arquivos e pastas de um diretório.", {"path": STRING}, []),
    _tool("search_code", "Busca por assunto: retorna as funções e trechos mais relacionados, ex: 'salvar tarefas em arquivo'.",
          {"query": STRING, "max_results": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
    _tool("code_map", "Mostra os arquivos com suas classes e funções (índice do código).", {"path": STRING}, []),
    TASK_SCHEMA,
]

TOOLS = {
    'bash': bash,
    'read_file': read_file,
    'read_skill': read_skill,
    'write_file': write_file,
    'str_replace': str_replace,
    'grep': grep,
    'glob': glob_files,
    'list_dir': list_dir,
    'search_code': search_code,
    'code_map': code_map,
    'update_todos': update_todos,
    'task': task,
}
# HARNEASY_DISABLED_TOOLS=task,read_skill hides tools a small model misuses.
# Fewer options mean fewer wrong choices.
DISABLED_TOOLS = {name.strip() for name in os.getenv("HARNEASY_DISABLED_TOOLS", "").split(",") if name.strip()}
TOOLS_SCHEMAS = [schema for schema in TOOLS_SCHEMAS if schema["function"]["name"] not in DISABLED_TOOLS]
for _name in DISABLED_TOOLS:
    TOOLS.pop(_name, None)

# Backwards-compatible alias: subagent implementations in earlier revisions
# imported this singular spelling.
TOOL_SCHEMAS = TOOLS_SCHEMAS
