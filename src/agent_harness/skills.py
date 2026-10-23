"""Skill discovery with local-project precedence and resilient parsing."""
from __future__ import annotations

import unicodedata
from pathlib import Path
import yaml

from .permissions import PROJECT_ROOT

# Later folders override earlier ones with the same skill name:
# built-in skills < user skills (~/.agents/skills) < project skills.
SKILL_DIR = [
    Path(__file__).parent / "builtin_skills",
    Path.home() / ".agents" / "skills",
    PROJECT_ROOT / ".agents" / "skills",
]


def normalize(text: str) -> str:
    """Lowercase without accents, so "Ação" and "acao" compare equal."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


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
                triggers = [normalize(str(t)) for t in meta.get("triggers") or []]
                skills[name] = {"description": description, "path": path, "triggers": triggers}
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


def suggest_skill(request: str) -> str | None:
    """Pick the skill whose trigger phrases appear in the request.

    Small models rarely read skills on their own, so the harness chooses.
    Each matching trigger counts one point; on a tie, the skill whose
    trigger appears first in the request wins (the main verb usually
    comes first).
    """
    text = normalize(request)
    short = len(text.split()) <= 4
    best: tuple[int, int, str] | None = None
    for name, info in SKILLS.items():
        if name == 'retomar-trabalho' and not short:
            continue
        positions = [text.find(trigger) for trigger in info.get("triggers", []) if trigger in text]
        if not positions:
            continue
        candidate = (-len(positions), min(positions), name)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best else None


def skill_body(name: str) -> str:
    """The skill text without its frontmatter."""
    text = read_skill(name)
    return text.split("\n---\n", 1)[1].strip() if text.startswith("---") and "\n---\n" in text else text


def read_skill(name: str) -> str:
    if name not in SKILLS:
        return f"Não existe uma skill com o nome '{name}'."
    path = SKILLS[name]["path"]
    return Path(path).read_text(encoding="utf-8")


if __name__ == "__main__":
    print(read_skill("code"))
    print(SKILLS)
