"""Small, low-token environment reminders for each model turn."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from .permissions import PROJECT_ROOT
from .todos import todos_prompts

SEEN: dict[str, float] = {}


def note_read(path: str | os.PathLike[str]) -> None:
    resolved = str(Path(path).expanduser().resolve())
    try:
        SEEN[resolved] = Path(resolved).stat().st_mtime
    except OSError:
        return


def states_file() -> list[str]:
    changed: list[str] = []
    for raw_path, old_mtime in list(SEEN.items()):
        try:
            current_mtime = Path(raw_path).stat().st_mtime
            if current_mtime > old_mtime:
                changed.append(raw_path)
                SEEN[raw_path] = current_mtime
        except OSError:
            # A removed/renamed file is also a state change worth noting.
            changed.append(f"{raw_path} (removido ou inacessível)")
            SEEN.pop(raw_path, None)
    return changed


def git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def todos_note() -> str:
    plan = todos_prompts()
    return f"\n<todos>\n{plan}\n</todos>" if plan else ""


def verify_command() -> str:
    """The command the harness runs to check the work, or "" for none.

    HARNEASY_VERIFY_COMMAND wins; "off" disables it. Otherwise, a project
    with tests is checked with pytest. Evaluated when the agent finishes, so
    tests created during the request count too.
    """
    configured = os.getenv("HARNEASY_VERIFY_COMMAND", "").strip()
    if configured.lower() == "off":
        return ""
    if configured:
        return configured
    has_tests = (PROJECT_ROOT / "tests").is_dir() or any(PROJECT_ROOT.glob("test_*.py"))
    return "python -m pytest -q" if has_tests else ""


PLAN_FILE = "PLANO.md"


def plan_note() -> str:
    """Point the model at the next step of PLANO.md, which survives compaction."""
    try:
        lines = (PROJECT_ROOT / PLAN_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    steps = [line.strip() for line in lines if line.strip().startswith(("- [ ]", "- [x]", "- [X]"))]
    if not steps:
        return ""
    pending = [step[len("- [ ]"):].strip() for step in steps if step.startswith("- [ ]")]
    done = len(steps) - len(pending)
    next_step = f" Próxima etapa: {pending[0][:200]}" if pending else " Todas as etapas concluídas."
    return f"\n{PLAN_FILE}: {done}/{len(steps)} etapas concluídas.{next_step}"


def reminder() -> dict[str, str]:
    changed = states_file()
    changed_note = "\nArquivos lidos e alterados desde então: " + ", ".join(changed) if changed else ""
    return {
        "role": "user",
        "content": (
            "<env>\n"
            f"time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"workspace: {PROJECT_ROOT}\n"
            f"git branch: {git_branch() or 'indisponível'}\n"
            "</env>"
            + plan_note()
            + todos_note()
            + changed_note
        ),
    }
