from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_harness import context
from agent_harness.skills import SKILL_DIR, SKILLS, find_skills, read_skill
from agent_harness.tools import TOOLS

BUILTIN = SKILL_DIR[0]


class BuiltinSkillTests(unittest.TestCase):
    def test_every_builtin_skill_loads_with_a_short_description(self):
        folders = sorted(path.parent.name for path in BUILTIN.glob("*/SKILL.md"))
        self.assertGreaterEqual(len(folders), 10)
        for name in folders:
            with self.subTest(skill=name):
                self.assertIn(name, SKILLS, "name in frontmatter must match the folder")
                # The list of skills goes into every prompt: keep it cheap.
                self.assertLessEqual(len(SKILLS[name]["description"]), 90)
                self.assertIn("# ", read_skill(name))

    def test_skills_only_reference_existing_skills_and_tools(self):
        for name in SKILLS:
            text = read_skill(name)
            with self.subTest(skill=name):
                for referenced in re.findall(r"skill `([a-z-]+)`", text):
                    self.assertIn(referenced, SKILLS)
                for tool in re.findall(r"`(read_file|write_file|str_replace|grep|glob|list_dir|bash|update_todos|task|read_skill)`", text):
                    self.assertIn(tool, TOOLS)

    def test_project_skill_overrides_builtin_with_same_name(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "corrigir-bug"
            project.mkdir()
            (project / "SKILL.md").write_text('---\nname: "corrigir-bug"\ndescription: "versão do projeto"\n---\nx\n')
            with mock.patch("agent_harness.skills.SKILL_DIR", [BUILTIN, Path(folder)]):
                self.assertEqual(find_skills()["corrigir-bug"]["description"], "versão do projeto")


class PlanNoteTests(unittest.TestCase):
    def test_reports_progress_and_next_step(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(context, "PROJECT_ROOT", root):
                self.assertEqual(context.plan_note(), "")
                (root / "PLANO.md").write_text("# Plano\n## Etapas\n- [x] 1. Base\n- [ ] 2. Salvar em JSON\n- [ ] 3. CLI\n")
                self.assertIn("1/3 etapas concluídas. Próxima etapa: 2. Salvar em JSON", context.plan_note())
                (root / "PLANO.md").write_text("- [x] 1. Base\n- [X] 2. CLI\n")
                self.assertIn("2/2 etapas concluídas. Todas as etapas concluídas.", context.plan_note())


if __name__ == "__main__":
    unittest.main()
