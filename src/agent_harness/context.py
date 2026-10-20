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
            + todos_note()
            + changed_note
        ),
    }
