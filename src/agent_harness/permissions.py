"""Permission policy for the tools exposed to the model.

The policy is intentionally conservative: unknown commands require approval,
known destructive/network commands are denied, and file edits are confined to
(the resolved path of) the workspace.
"""
from __future__ import annotations

import atexit
import os
import re
import shlex
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("HARNEASY_PROJECT_ROOT", Path.cwd())).expanduser().resolve()
# Backwards-compatible name used by older code.
PATH = PROJECT_ROOT
_GENERATED_OUTPUTS: set[Path] = set()


def register_generated_output(path: str | os.PathLike[str]) -> None:
    """Allow the model to read back only temporary files created by this harness."""
    _GENERATED_OUTPUTS.add(Path(path).expanduser().resolve())


def is_generated_output(path: str | os.PathLike[str]) -> bool:
    try:
        return Path(path).expanduser().resolve() in _GENERATED_OUTPUTS
    except (OSError, RuntimeError, ValueError):
        return False


def _cleanup_generated_outputs() -> None:
    for path in tuple(_GENERATED_OUTPUTS):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    _GENERATED_OUTPUTS.clear()


atexit.register(_cleanup_generated_outputs)


# These executables/operations are blocked even when the user is prompted.
DENIED_EXECUTABLES = {
    "rm", "sudo", "chmod", "chown", "curl", "wget", "mkfs", "dd",
    "shutdown", "reboot", "poweroff", "halt", "passwd", "useradd",
    "userdel", "iptables", "nft", "nc", "ncat", "netcat", "socat",
    "ssh", "scp", "sftp", "telnet",
}
DENIED_GIT_SUBCOMMANDS = {"push", "reset", "clean", "filter-branch", "gc", "prune"}

READ_ONLY_COMMANDS = {
    "ls", "pwd", "echo", "printf", "sort", "uniq", "cut", "basename",
    "dirname", "date", "cat", "head", "tail", "wc", "file", "which",
    "grep", "rg", "find", "tree", "stat", "du", "df", "realpath", "cd",
}
READ_ONLY_GIT_SUBCOMMANDS = {
    "status", "diff", "log", "show", "ls-files", "branch", "rev-parse",
    "grep", "remote", "tag", "describe",
}
TEST_COMMANDS = {"pytest", "py.test"}
SHELL_COMMANDS = {"sh", "bash", "dash", "zsh"}


def split_command(command: str) -> list[str]:
    """Split a shell command into top-level statements, respecting quotes."""
    if not isinstance(command, str):
        return []

    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False

    for char in command:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote != "'":
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
        elif char in ";|&\n":
            item = "".join(current).strip()
            if item:
                parts.append(item)
            current = []
        else:
            current.append(char)

    item = "".join(current).strip()
    if item:
        parts.append(item)
    return parts


def _has_unquoted_redirect(command: str) -> bool:
    quote: str | None = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char in "<>":
            return True
    return False


def _tokens(segment: str) -> list[str] | None:
    try:
        return shlex.split(segment, posix=(os.name != "nt"))
    except ValueError:
        return None


def _strip_assignments(tokens: list[str]) -> list[str]:
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    return tokens


def _path_is_inside_workspace(raw_path: str) -> bool:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents


def _check_command_paths(executable: str, tokens: list[str]) -> str:
    """Ask before read commands target paths outside the active workspace."""
    # Check obvious path operands regardless of their syntactic position, since
    # flags such as grep -f or sort -o also accept file paths.
    for token in tokens[1:]:
        cleaned = token.strip('"\'')
        looks_like_path = (
            cleaned.startswith(("/", "~/", "../", "..\\"))
            or "/" in cleaned
            or "\\" in cleaned
            or bool(re.match(r"^[A-Za-z]:[\\/]", cleaned))
        )
        if looks_like_path and not _path_is_inside_workspace(cleaned):
            return "ask"
        if executable in {"sort", "uniq"} and cleaned in {"-o", "--output"}:
            return "ask"  # These flags can write a file even though the command is normally read-only.
    tokens = tokens[1:]
    if executable == "cd":
        target = next((token for token in tokens if not token.startswith("-")), ".")
        return "allow" if _path_is_inside_workspace(target) else "ask"
    if executable == "find":
        if any(flag in tokens for flag in {"-fprint", "-fprintf", "-fls"}):
            return "ask"
        candidates = [next((token for token in tokens if not token.startswith("-")), ".")]
    elif executable in {"grep", "rg"}:
        non_options = [token for token in tokens if not token.startswith("-")]
        # grep/rg's first positional argument is the pattern, later ones are paths.
        candidates = non_options[1:]
        if executable == "grep" and not candidates:
            # The shell runner closes stdin, so this cannot wait for interactive input.
            return "allow"
    elif executable in {"cat", "head", "tail", "wc", "file", "stat", "du", "realpath", "ls", "tree"}:
        candidates = [token for token in tokens if not token.startswith("-") and token != "-"]
        if executable in {"cat", "head", "tail"} and not candidates:
            return "ask"  # No file operand means stdin.
    else:
        return "allow"

    for candidate in candidates:
        if candidate.isdigit():
            continue
        if not _path_is_inside_workspace(candidate):
            return "ask"
    return "allow"


def _contains_obvious_external_path(tokens: list[str]) -> bool:
    for token in tokens[1:]:
        cleaned = token.strip('"\'')
        looks_like_path = (
            cleaned.startswith(("/", "~/", "../", "..\\"))
            or "/" in cleaned
            or "\\" in cleaned
            or bool(re.match(r"^[A-Za-z]:[\\/]", cleaned))
        )
        if looks_like_path and not _path_is_inside_workspace(cleaned):
            return True
    return False


def _segment_decision(segment: str, *, readonly: bool, depth: int) -> str:
    tokens = _tokens(segment)
    if not tokens:
        return "ask"
    if tokens is None:
        return "ask"
    tokens = _strip_assignments(tokens)
    if not tokens:
        return "ask"

    executable = Path(tokens[0].strip('"\'')).name.lower()
    powershell_denied = {
        "remove-item", "ri", "del", "erase", "rm", "invoke-webrequest", "iwr",
        "start-bitstransfer", "stop-computer", "restart-computer",
        "set-executionpolicy", "clear-content",
    }
    if executable in powershell_denied:
        return "deny"

    # A shell -c command must be checked recursively, not as a harmless shell.
    if executable in SHELL_COMMANDS:
        if "-c" in tokens:
            index = tokens.index("-c")
            if index + 1 >= len(tokens) or depth >= 4:
                return "ask"
            nested = decide(tokens[index + 1], readonly=readonly, _depth=depth + 1)
            return nested
        return "ask"

    if executable in DENIED_EXECUTABLES:
        return "deny"

    git_subcommand = tokens[1].lower() if executable == "git" and len(tokens) > 1 else ""
    if executable == "git" and git_subcommand in DENIED_GIT_SUBCOMMANDS:
        return "deny"
    if executable == "find" and "-delete" in tokens:
        return "deny"

    # Inspect command wrappers before path checks; otherwise `env rm /outside`
    # could fall back to an approval prompt instead of being blocked.
    if executable in {"env", "command", "nohup", "time", "exec"}:
        nested_tokens = tokens[1:]
        wrapper_forces_ask = False
        if executable == "env":
            # Parse common env options so `env -i rm ...` remains a hard deny.
            while nested_tokens:
                token = nested_tokens[0]
                if token == "--":
                    nested_tokens = nested_tokens[1:]
                    break
                if token in {"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}:
                    nested_tokens = nested_tokens[1:]
                    continue
                if token in {"-u", "--unset", "-C", "--chdir", "--argv0"}:
                    if len(nested_tokens) < 2:
                        return "ask"
                    nested_tokens = nested_tokens[2:]
                    continue
                if token in {"-S", "--split-string"}:
                    if len(nested_tokens) < 2:
                        return "ask"
                    try:
                        split_string = shlex.split(nested_tokens[1])
                    except ValueError:
                        return "ask"
                    nested_tokens = split_string + nested_tokens[2:]
                    continue
                if token.startswith(("--unset=", "--chdir=", "--argv0=")):
                    nested_tokens = nested_tokens[1:]
                    continue
                if token.startswith("--split-string="):
                    try:
                        split_string = shlex.split(token.split("=", 1)[1])
                    except ValueError:
                        return "ask"
                    nested_tokens = split_string + nested_tokens[1:]
                    continue
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                    nested_tokens = nested_tokens[1:]
                    continue
                if token.startswith("-"):
                    # An unknown wrapper option is not safe to infer. Still
                    # deny if an explicit blocked executable appears afterward.
                    if any(Path(arg.strip('\"\'')).name.lower() in DENIED_EXECUTABLES | powershell_denied for arg in nested_tokens[1:]):
                        return "deny"
                    return "ask"
                break
        elif executable == "command":
            if nested_tokens and nested_tokens[0] in {"-v", "-V", "--help", "--version"}:
                return "ask"  # command lookup/help, not an automatic allow-list entry.
            while nested_tokens and nested_tokens[0] == "-p":
                nested_tokens = nested_tokens[1:]
            if nested_tokens and nested_tokens[0] == "--":
                nested_tokens = nested_tokens[1:]
        elif executable in {"nohup", "exec"} and nested_tokens and nested_tokens[0] == "--":
            nested_tokens = nested_tokens[1:]
        elif executable == "time":
            while nested_tokens:
                token = nested_tokens[0]
                if token == "--":
                    nested_tokens = nested_tokens[1:]
                    break
                if token in {"-p", "-v", "--verbose"}:
                    nested_tokens = nested_tokens[1:]
                    continue
                if token in {"-f", "--format"}:
                    if len(nested_tokens) < 2:
                        return "ask"
                    nested_tokens = nested_tokens[2:]
                    continue
                if token in {"-o", "--output"}:
                    if len(nested_tokens) < 2:
                        return "ask"
                    nested_tokens = nested_tokens[2:]
                    wrapper_forces_ask = True  # time can write a report to a path.
                    continue
                if token.startswith("--output="):
                    nested_tokens = nested_tokens[1:]
                    wrapper_forces_ask = True
                    continue
                if token.startswith("-"):
                    return "ask"
                break
        if not nested_tokens or depth >= 4:
            return "ask"
        nested = _segment_decision(shlex.join(nested_tokens), readonly=readonly, depth=depth + 1)
        if nested == "deny":
            return "deny"
        if _has_unquoted_redirect(segment) or "`" in segment or re.search(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)", segment):
            return "ask"
        if wrapper_forces_ask:
            return "ask"
        return nested

    if executable == "find" and any(flag in tokens for flag in {"-exec", "-execdir", "-ok"}):
        try:
            index = max(i for i, token in enumerate(tokens) if token in {"-exec", "-execdir", "-ok"})
            nested_tokens = tokens[index + 1:]
        except (ValueError, IndexError):
            return "ask"
        while nested_tokens and nested_tokens[-1] in {";", "+", r"\;"}:
            nested_tokens = nested_tokens[:-1]
        if nested_tokens:
            nested = _segment_decision(shlex.join(nested_tokens), readonly=readonly, depth=depth + 1)
            if nested == "deny":
                return "deny"
        return "ask"  # find -exec is never automatically allow-listed.

    # xargs can invoke an arbitrary command, so never treat it as a harmless
    # read-only utility. Deny known dangerous commands even when wrapped by
    # xargs; require approval for all other xargs invocations.
    if executable == "xargs":
        dangerous_names = DENIED_EXECUTABLES | powershell_denied
        if any(Path(token.strip('"\'')).name.lower() in dangerous_names for token in tokens[1:]):
            return "deny"
        return "ask"

    # BusyBox/Toybox can expose a destructive applet behind an innocuous name.
    if executable in {"busybox", "toybox"}:
        if len(tokens) > 1 and Path(tokens[1].strip('"\'')).name.lower() in (DENIED_EXECUTABLES | powershell_denied):
            return "deny"
        return "ask"

    # Validate path-like arguments before allowing any read-only utility. This
    # covers secondary file flags such as `grep -f /path` as well as operands.
    if _contains_obvious_external_path(tokens):
        return "ask"

    if executable == "git":
        subcommand = git_subcommand
        git_args = tokens[2:]
        if subcommand in {"branch", "tag"}:
            destructive_flags = {"-D", "-d", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy"}
            if any(arg in destructive_flags for arg in git_args):
                return "ask"
            if subcommand == "branch":
                if any(arg.startswith("-") for arg in git_args) and any(
                    flag in git_args for flag in {"--list", "-l", "--show-current", "-a", "-r", "-vv", "--merged", "--no-merged"}
                ):
                    return "allow"
                return "allow" if not git_args else "ask"
            if subcommand == "tag":
                if any(flag in git_args for flag in {"-l", "--list", "--sort", "--contains", "--merged", "--no-merged"}):
                    return "allow"
                return "allow" if not git_args else "ask"
        if subcommand == "remote":
            mutating_remote_ops = {"add", "remove", "rm", "rename", "set-url", "set-head", "set-branches"}
            if any(arg.lower() in mutating_remote_ops for arg in git_args):
                return "ask"
            return "allow"
        if subcommand in READ_ONLY_GIT_SUBCOMMANDS:
            # Some nominally read-only Git commands support writing output to a file.
            if any(arg in {"--ext-diff", "--textconv", "-o", "--output"} or arg.startswith("--output=") for arg in git_args):
                return "ask"
            return "allow"
        return "ask"

    if depth >= 4:
        return "ask"

    # Do not treat redirection, expansion, or xargs as read-only. The variable
    # check also prevents paths like "$HOME/.ssh/id_rsa" from bypassing path checks.
    if (
        _has_unquoted_redirect(segment)
        or "`" in segment
        or re.search(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)", segment)
    ):
        return "ask"
    if executable in {"python", "python3", "python3.12", "python3.13"}:
        if len(tokens) >= 3 and tokens[1:3] == ["-m", "pytest"] and not readonly:
            return "allow"
        return "ask"

    if executable in TEST_COMMANDS and not readonly:
        return "allow"

    if executable == "date" and any(arg in {"-s", "--set", "-f", "--file"} for arg in tokens[1:]):
        return "ask"

    if executable in READ_ONLY_COMMANDS:
        # Also ensure read tools do not silently inspect files beyond the workspace.
        path_decision = _check_command_paths(executable, tokens)
        if path_decision != "allow":
            return path_decision
        return "allow"

    return "ask"


def decide(command: str, *, readonly: bool = False, _depth: int = 0) -> str:
    """Return ``allow``, ``ask`` or ``deny`` for a shell command.

    A compound command is only allowed when every part is allow-listed. A deny
    decision on any part dominates all other decisions.
    """
    if not isinstance(command, str) or not command.strip():
        return "ask"

    stripped = command.strip()
    powershell_prefix = re.match(r"(?i)^(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\s+(.+)$", stripped, flags=re.DOTALL)
    if powershell_prefix:
        # PowerShell aliases and nested -Command strings do not follow POSIX
        # tokenization. Fail closed when known destructive/network commands
        # appear anywhere in a PowerShell invocation.
        body = powershell_prefix.group(1)
        denied_powershell = {
            "remove-item", "ri", "del", "erase", "rm", "curl", "wget",
            "invoke-webrequest", "iwr", "start-bitstransfer", "stop-computer",
            "restart-computer", "set-executionpolicy", "clear-content",
            "clear-item", "move-item", "copy-item", "set-content", "add-content",
        }
        pattern = r"(?i)(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(name) for name in sorted(denied_powershell, key=len, reverse=True)) + r")(?![A-Za-z0-9_-])"
        if re.search(pattern, body):
            return "deny"
        return "ask"  # PowerShell syntax is not auto-allowlisted.

    parts = split_command(command)
    if not parts:
        return "ask"

    decisions = [_segment_decision(part, readonly=readonly, depth=_depth) for part in parts]
    if "deny" in decisions:
        return "deny"
    if "ask" in decisions:
        return "ask"
    return "allow"


def resolve_path(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def inside_project(path: str | os.PathLike[str]) -> bool:
    """Whether a path resolves to the workspace itself or one of its children."""
    resolved = resolve_path(path)
    return resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents


def check(name: str, args: dict) -> tuple[str, str | None]:
    """Apply the tool-level policy before any tool function is called."""
    if not isinstance(args, dict):
        return "deny", "tool arguments must be a JSON object"

    if name == "bash":
        command = args.get("command")
        if not isinstance(command, str):
            return "deny", "missing or invalid 'command' argument"
        return decide(command), f"run command: {command}"

    if name in {"read_file", "write_file", "str_replace"}:
        raw_path = args.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return "deny", "missing or invalid file path"
        try:
            resolved = resolve_path(raw_path)
        except (OSError, RuntimeError, ValueError):
            return "deny", "invalid or unresolvable file path"
        in_workspace = resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents
        if not in_workspace:
            if name == "read_file" and is_generated_output(resolved):
                return "allow", None
            if name == "read_file":
                return "ask", f"read file outside workspace: {resolved}"
            return "deny", f"refusing to modify a file outside workspace: {resolved}"
        return "allow", None

    if name in {"grep", "glob", "list_dir", "code_map", "search_code"}:
        raw_path = args.get("path") or "."
        if not isinstance(raw_path, str):
            return "deny", "invalid search path"
        if inside_project(raw_path):
            return "allow", None
        return "ask", f"search outside workspace: {resolve_path(raw_path)}"

    if name in {"read_skill", "update_todos", "task"}:
        return "allow", None

    return "deny", f"unknown tool: {name}"
