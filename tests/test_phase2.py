from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent_harness.permissions import PROJECT_ROOT, check
from agent_harness.tools import UNDO_STACK, execute_tool, undo_last_edit


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.root = Path(self._temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def main():\n    return 'hello'\n")
        (self.root / "src" / "util.py").write_text("# TODO: remover\nVALUE = 1\n")
        (self.root / "notes.txt").write_text("nada aqui\n")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "lib.py").write_text("def main(): pass\n")
        UNDO_STACK.clear()

    def tearDown(self):
        self._temp.cleanup()

    def run_tool(self, name, **args):
        return execute_tool(name, args)


class SearchToolTests(WorkspaceTestCase):
    def test_glob_by_name_and_by_path_skips_dependencies(self):
        found = self.run_tool("glob", pattern="*.py", path=str(self.root))
        self.assertIn("src/app.py", found)
        self.assertNotIn("node_modules", found)
        self.assertIn("util.py", self.run_tool("glob", pattern="src/**/*.py", path=str(self.root)))

    def test_grep_reports_file_and_line(self):
        found = self.run_tool("grep", pattern="def main", path=str(self.root))
        self.assertIn("src/app.py:1: def main():", found)
        self.assertNotIn("node_modules", found)
        self.assertIn("util.py:1", self.run_tool("grep", pattern="todo", path=str(self.root), ignore_case=True, include="*.py"))
        self.assertIn("Nenhuma", self.run_tool("grep", pattern="todo", path=str(self.root), include="*.txt"))

    def test_grep_invalid_regex_is_a_readable_error(self):
        self.assertIn("expressão regular inválida", self.run_tool("grep", pattern="(", path=str(self.root)))

    def test_list_dir_shows_folders_first(self):
        listing = self.run_tool("list_dir", path=str(self.root))
        self.assertLess(listing.index("src/"), listing.index("notes.txt"))

    def test_search_outside_workspace_asks(self):
        self.assertEqual(check("grep", {"pattern": "x", "path": "/etc"})[0], "ask")
        self.assertEqual(check("glob", {"pattern": "*"})[0], "allow")


class EditSafetyTests(WorkspaceTestCase):
    def test_edit_requires_prior_read(self):
        app = str(self.root / "src" / "app.py")
        self.assertIn("leia", self.run_tool("str_replace", path=app, old_str="hello", new_str="oi"))
        self.assertIn("leia", self.run_tool("write_file", path=app, content="x"))
        self.run_tool("read_file", path=app)
        self.assertIn("Substituído", self.run_tool("str_replace", path=app, old_str="hello", new_str="oi"))
        # Our own edit keeps the file "fresh": a second edit needs no new read.
        self.assertIn("Substituído", self.run_tool("str_replace", path=app, old_str="oi", new_str="olá"))

    def test_external_change_after_read_is_detected(self):
        app = self.root / "src" / "app.py"
        self.run_tool("read_file", path=str(app))
        time.sleep(0.01)
        app.write_text("def main():\n    return 'mudou'\n")
        self.assertIn("mudou desde a última leitura", self.run_tool("str_replace", path=str(app), old_str="mudou", new_str="x"))

    def test_new_file_needs_no_read(self):
        result = self.run_tool("write_file", path=str(self.root / "novo.py"), content="X = 1\n")
        self.assertIn("novo arquivo", result)

    def test_edit_result_shows_diff_and_syntax_errors(self):
        app = str(self.root / "src" / "app.py")
        self.run_tool("read_file", path=app)
        result = self.run_tool("str_replace", path=app, old_str="return 'hello'", new_str="return 'hello'(")
        self.assertIn("-    return 'hello'", result)
        self.assertIn("+    return 'hello'(", result)
        self.assertIn("erro de sintaxe Python na linha 2", result)

        bad_json = self.run_tool("write_file", path=str(self.root / "c.json"), content="{oops}")
        self.assertIn("ficou inválido", bad_json)

    def test_undo_restores_edit_and_removes_created_file(self):
        app = self.root / "src" / "app.py"
        original = app.read_text()
        self.run_tool("read_file", path=str(app))
        self.run_tool("str_replace", path=str(app), old_str="hello", new_str="oi")
        self.run_tool("write_file", path=str(self.root / "novo.py"), content="X = 1\n")

        self.assertIn("removido", undo_last_edit())
        self.assertFalse((self.root / "novo.py").exists())
        self.assertIn("voltou", undo_last_edit())
        self.assertEqual(app.read_text(), original)
        self.assertEqual(undo_last_edit(), "Nada para desfazer.")


if __name__ == "__main__":
    unittest.main()


class MissingImportTests(WorkspaceTestCase):
    def test_warns_about_packages_that_are_not_installed(self):
        result = self.run_tool(
            "write_file", path=str(self.root / "slug.py"),
            content="import json\nimport unidecode_nao_existe\nfrom src.app import main\n",
        )
        self.assertIn("módulos não instalados: unidecode_nao_existe.", result)

    def test_stdlib_installed_and_local_imports_are_fine(self):
        (self.root / "helpers.py").write_text("X = 1\n")
        result = self.run_tool(
            "write_file", path=str(self.root / "ok.py"),
            content="import os.path\nfrom collections import Counter\nimport yaml\nimport helpers\nfrom . import x\n",
        )
        self.assertNotIn("Aviso", result)
