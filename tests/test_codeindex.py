from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from agent_harness import codeindex
from agent_harness.codeindex import CodeIndex, bm25_scores, chunk_file, expand_query, tokenize

PROJECT = {
    "app/storage.py": (
        '"""Persistence helpers."""\n'
        "import json\n"
        "TIMEOUT = 30\n"
        "\n\n"
        "def save_tasks(path, tasks):\n"
        '    """Write the task list to a JSON file."""\n'
        "    path.write_text(json.dumps(tasks))\n"
        "\n\n"
        "class UserRepository:\n"
        '    """Users kept in memory."""\n'
        "    def find_user(self, user_id):\n"
        "        return None\n"
    ),
    "web/app.js": (
        "export function renderCart(items) {\n  return items.length;\n}\n\n"
        "const sendPayment = async (amount) => {\n  return amount;\n};\n\n"
        "function helper() {\n  return 1;\n}\n"
    ),
    "docs/guide.md": "# Guia\n\nIntro.\n\n## Instalação\n\nRode pip install.\n",
    "config.yaml": "# comentário\ndebug: true\n",
}


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        for relative, content in PROJECT.items():
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.root / relative).write_text(content, encoding="utf-8")
        self.index = CodeIndex(self.root)

    def tearDown(self):
        self._temp.cleanup()

    def search(self, query):
        return [(c.path.rsplit("/", 1)[-1], c.name) for c in self.index.search(query, 3)[0]]


class TokenizeTests(unittest.TestCase):
    def test_splits_identifiers_and_removes_accents_and_plurals(self):
        self.assertEqual(tokenize("saveTasks user_id Configuração tarefas"),
                         ["save", "task", "user", "id", "configuracao", "tarefa"])

    def test_portuguese_query_is_expanded_to_english(self):
        self.assertIn("undo", expand_query("desfazer edição"))
        self.assertIn("edit", expand_query("desfazer edição"))

    def test_bm25_prefers_rare_matching_words(self):
        scores = bm25_scores(["payment"], [["payment", "send"], ["user", "user"], ["send"]])
        self.assertGreater(scores[0], 0)
        self.assertEqual(scores[1:], [0.0, 0.0])


class ChunkTests(ProjectTestCase):
    def test_python_functions_classes_methods_and_module_code(self):
        chunks = chunk_file(self.root / "app/storage.py")
        names = [c.name for c in chunks]
        self.assertEqual(names, ["", "def save_tasks(path, tasks)", "class UserRepository", "def find_user(self, user_id)"])
        module = chunks[0]
        self.assertEqual((module.start, module.end, module.doc), (1, 3, "Persistence helpers."))
        self.assertIn("TIMEOUT = 30", module.text)
        self.assertEqual(chunks[1].doc, "Write the task list to a JSON file.")

    def test_javascript_and_markdown_use_patterns(self):
        js = [c.name for c in chunk_file(self.root / "web/app.js")]
        self.assertEqual(len(js), 3)
        self.assertTrue(js[1].startswith("const sendPayment"))
        md = [c.name for c in chunk_file(self.root / "docs/guide.md")]
        self.assertEqual(md, ["# Guia", "## Instalação"])

    def test_yaml_comment_is_not_a_heading(self):
        [chunk] = chunk_file(self.root / "config.yaml")
        self.assertEqual((chunk.name, chunk.start), ("", 1))


class SearchTests(ProjectTestCase):
    def test_finds_by_subject_in_portuguese(self):
        self.assertEqual(self.search("salvar tarefas")[0], ("storage.py", "def save_tasks(path, tasks)"))
        self.assertEqual(self.search("usuário")[0][1], "class UserRepository")
        self.assertTrue(self.search("pagamento")[0][1].startswith("const sendPayment"))

    def test_finds_module_level_constants(self):
        self.assertEqual(self.search("timeout")[0], ("storage.py", ""))

    def test_index_follows_file_changes_and_deletions(self):
        self.assertEqual(self.search("invoice"), [])
        js = self.root / "web/app.js"
        js.write_text("function createInvoice() {}\n")
        os.utime(js, (1, 1))  # make sure the mtime differs
        self.assertEqual(self.search("invoice")[0][0], "app.js")
        js.unlink()
        self.assertEqual(self.search("invoice"), [])

    def test_embeddings_are_merged_and_cached(self):
        calls = []

        def fake_create(model, input):
            calls.append(len(input))
            # A toy "meaning": 1.0 when the text is about payments.
            vectors = [[1.0, 0.0] if ("Payment" in text or "dinheiro" in text) else [0.0, 1.0] for text in input]
            return NS(data=[NS(embedding=vector) for vector in vectors])

        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.dict(os.environ, {"HARNEASY_EMBED_MODEL": "fake-embed"}), \
                mock.patch.object(codeindex, "CACHE_DIR", Path(cache)), \
                mock.patch("agent_harness.llm.client.embeddings.create", side_effect=fake_create):
            results, note = self.index.search("dinheiro", 3)  # no keyword matches at all
            self.assertIn("significado (fake-embed)", note)
            self.assertTrue(results[0].name.startswith("const sendPayment"))
            first_batch = sum(calls)

            calls.clear()
            CodeIndex(self.root).search("dinheiro", 3)  # new index, same disk cache
            self.assertEqual(calls, [1], "only the query is embedded again")
            self.assertGreater(first_batch, 1)

    def test_broken_embedding_server_falls_back_to_bm25(self):
        with mock.patch.dict(os.environ, {"HARNEASY_EMBED_MODEL": "missing"}), \
                mock.patch.object(codeindex, "CACHE_DIR", self.root / ".cache"), \
                mock.patch("agent_harness.llm.client.embeddings.create", side_effect=RuntimeError("404")):
            results, note = self.index.search("salvar tarefas", 3)
        self.assertIn("embeddings indisponíveis", note)
        self.assertEqual(results[0].name, "def save_tasks(path, tasks)")


class ToolOutputTests(ProjectTestCase):
    def test_code_map_and_search_code_output(self):
        with mock.patch.object(codeindex, "PROJECT_ROOT", self.root), mock.patch.object(codeindex, "INDEX", self.index):
            tree = codeindex.code_map(".")
            self.assertIn("app/storage.py\n  6: def save_tasks(path, tasks) — Write the task list to a JSON file.", tree)
            self.assertIn("  13: def find_user(self, user_id)", codeindex.code_map("app/storage.py"))
            found = codeindex.search_code("salvar tarefas", 2)
            self.assertIn("1. app/storage.py:6-8  def save_tasks(path, tasks)", found)
            self.assertIn("Nada encontrado", codeindex.search_code("zzzz"))


if __name__ == "__main__":
    unittest.main()
