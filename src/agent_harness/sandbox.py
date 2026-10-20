"""Best-effort OS sandbox for shell commands.

Permission checks still run before this module is called. If an OS sandbox is
unavailable, commands can run unsandboxed for local usability; set
HARNEASY_REQUIRE_SANDBOX=1 to fail closed instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("HARNEASY_PROJECT_ROOT", Path.cwd())).expanduser().resolve()


def _seatbelt_profile() -> str:
    escaped = str(PROJECT_ROOT).replace("\\", "\\\\").replace('"', '\\"')
    git_dir = PROJECT_ROOT / ".git"
    git_rule = f'(deny file-write* (subpath "{git_dir}"))' if git_dir.exists() else ""
    return f'''(version 1)
(deny default)
(allow process-exec process-fork signal)
(allow file-read*)
(allow sysctl-read)
(deny network*)
(allow file-write* (subpath "{escaped}") (literal "/dev/null"))
{git_rule}
'''


def wrap(command: str) -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        # Use an unpredictable, owner-only temporary profile instead of a fixed
        # filename in /tmp, which could be pre-created as a symlink by another user.
        fd, profile_name = tempfile.mkstemp(prefix="harneasy-agent-", suffix=".sb")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_seatbelt_profile())
        return ["sandbox-exec", "-f", profile_name, "/bin/sh", "-c", command]

    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        args = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--bind", str(PROJECT_ROOT), str(PROJECT_ROOT),
            "--dev", "/dev", "--proc", "/proc",
            "--unshare-net", "--die-with-parent",
        ]
        git_dir = PROJECT_ROOT / ".git"
        if git_dir.is_dir():
            args.extend(["--ro-bind", str(git_dir), str(git_dir)])
        args.extend(["/bin/sh", "-c", command])
        return args

    return None


def name() -> str:
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return "none"


def run(command: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    timeout = timeout or int(os.getenv("HARNEASY_COMMAND_TIMEOUT", "60"))
    sandbox = wrap(command)
    if sandbox is None and os.getenv("HARNEASY_REQUIRE_SANDBOX", "0").lower() in {"1", "true", "yes"}:
        raise RuntimeError(
            "No supported OS sandbox was found. Install bubblewrap (Linux) or "
            "use macOS sandbox-exec, or set HARNEASY_REQUIRE_SANDBOX=0 to opt "
            "into running commands with permission checks but without OS isolation."
        )

    profile_path = None
    if sandbox and sandbox[0] == "sandbox-exec" and "-f" in sandbox:
        profile_path = Path(sandbox[sandbox.index("-f") + 1])
    try:
        return subprocess.run(
            sandbox if sandbox is not None else ["/bin/sh", "-c", command],
            cwd=PROJECT_ROOT,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    finally:
        if profile_path is not None:
            try:
                profile_path.unlink(missing_ok=True)
            except OSError:
                pass
