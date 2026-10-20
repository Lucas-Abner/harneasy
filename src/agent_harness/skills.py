"""Skill discovery with local-project precedence and resilient parsing."""
from __future__ import annotations

from pathlib import Path
import yaml

from .permissions import PROJECT_ROOT

# User-level skills load first; project-local definitions can override them.
SKILL_DIR = [
    Path.home() / ".agents" / "skills",
    PROJECT_ROOT / ".agents" / "skills",
]


def find_skills() -> dict[str, dict[str, object]]:
    skills: dict[str, dict[str, object]] = {}
    for directory in SKILL_DIR:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*/SKILL.md")):
            try:
                content = path.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    continue
                parts = content.split("---", 2)
                if len(parts) < 3:
                    continue
                meta = yaml.safe_load(parts[1]) or {}
                if not isinstance(meta, dict):
                    continue
                name = meta.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                description = " ".join(str(meta.get("description", "")).split())
                skills[name] = {"description": description, "path": path}
            except (OSError, yaml.YAMLError, UnicodeError):
                # A malformed unrelated skill should not prevent the harness starting.
                continue
    return skills


SKILLS = find_skills()


def skills_prompt() -> str:
    return "\n".join(
        f"- {name}: {info['description']}"
        for name, info in SKILLS.items()
    )


def read_skill(name: str) -> str:
    if name not in SKILLS:
        return f"Não existe uma skill com o nome '{name}'."
    path = SKILLS[name]["path"]
    return Path(path).read_text(encoding="utf-8")


if __name__ == "__main__":
    print(read_skill("code"))
    print(SKILLS)
