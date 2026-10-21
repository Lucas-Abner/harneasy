from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.permissions import PROJECT_ROOT
from agent_harness.repair import extract_text_tool_calls, parse_arguments, to_tool_call_objects
from agent_harness.tools import execute_tool, normalize_arg_names
from agent_harness.ui import nudge_for

TOOL_NAMES = {"read_file", "bash"}


class ParseArgumentsTests(unittest.TestCase):
    def test_repairs_common_mistakes(self):
        cases = {
            "valid json": ('{"path": "a.py"}', {"path": "a.py"}),
            "code fence": ('```json\n{"path": "a.py"}\n```', {"path": "a.py"}),
            "trailing comma": ('{"path": "a.py",}', {"path": "a.py"}),
            "python dict": ("{'path': 'a.py', 'flag': True}", {"path": "a.py", "flag": True}),
            "double encoded": (json.dumps('{"path": "a.py"}'), {"path": "a.py"}),
            "truncated": ('{"command": "ls -la', {"command": "ls -la"}),
            "wrapped": ('{"name": "read_file", "arguments": {"path": "a.py"}}', {"path": "a.py"}),
            "empty": ("", {}),
        }
        for label, (raw, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(parse_arguments(raw), expected)

    def test_tool_argument_called_name_is_not_unwrapped(self):
        self.assertEqual(parse_arguments('{"name": "code"}'), {"name": "code"})

    def test_garbage_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_arguments("isso não é json")
        with self.assertRaises(ValueError):
            parse_arguments("[1, 2]")


class TextToolCallTests(unittest.TestCase):
    def test_hermes_tool_call_tag(self):
        content = 'Vou ler.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
        calls, remaining = extract_text_tool_calls(content, TOOL_NAMES)
        self.assertEqual(calls, [{"name": "read_file", "arguments": {"path": "a.py"}}])
        self.assertEqual(remaining, "Vou ler.")

    def test_code_block_and_bare_json(self):
        block = '```json\n{"name": "bash", "parameters": {"command": "ls"}}\n```'
        self.assertEqual(extract_text_tool_calls(block, TOOL_NAMES)[0][0]["name"], "bash")
        bare = '{"name": "bash", "arguments": {"command": "ls"}}'
        self.assertEqual(extract_text_tool_calls(bare, TOOL_NAMES), ([{"name": "bash", "arguments": {"command": "ls"}}], ""))

    def test_unknown_tool_or_plain_json_example_is_not_executed(self):
        for content in [
            '<tool_call>{"name": "rm_everything", "arguments": {}}</tool_call>',
            'Exemplo de config:\n```json\n{"name": "meu-projeto", "version": "1.0"}\n```',
            "Resposta normal, sem ferramentas.",
        ]:
            with self.subTest(content=content[:30]):
                self.assertEqual(extract_text_tool_calls(content, TOOL_NAMES), ([], content))

    def test_converts_to_api_tool_call_objects(self):
        [call] = to_tool_call_objects([{"name": "bash", "arguments": {"command": "ls"}}])
        self.assertTrue(call.id.startswith("call_text_"))
        self.assertEqual(call.function.name, "bash")
        self.assertEqual(json.loads(call.function.arguments), {"command": "ls"})
        self.assertEqual(call.model_dump()["type"], "function")


class ArgumentAliasTests(unittest.TestCase):
    def test_aliases_are_renamed_and_unknown_args_dropped(self):
        args, ignored = normalize_arg_names(
            "str_replace", {"file_path": "a.py", "old_string": "x", "new": "y", "reason": "?"}
        )
        self.assertEqual(args, {"path": "a.py", "old_str": "x", "new_str": "y"})
        self.assertEqual(ignored, ["reason"])

    def test_canonical_name_wins_over_alias(self):
        args, ignored = normalize_arg_names("write_file", {"path": "a", "content": "real", "text": "alias"})
        self.assertEqual(args, {"path": "a", "content": "real"})
        self.assertEqual(ignored, ["text"])


class TolerantStrReplaceTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile("w", dir=PROJECT_ROOT, suffix=".py", delete=False)
        handle.write("class A:\n    def run(self):  \n        return 1\n\n    def stop(self):\n        return 2\n")
        handle.close()
        self.path = Path(handle.name)
        execute_tool("read_file", {"path": str(self.path)})  # edits require a prior read

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def replace(self, old, new, **extra):
        return execute_tool("str_replace", {"path": str(self.path), "old_str": old, "new_str": new, **extra})

    def test_exact_match_still_works(self):
        result = self.replace("return 2", "return 3")
        self.assertIn("Substituído 1 ocorrência", result)
        self.assertIn("return 3", self.path.read_text())

    def test_ignores_trailing_spaces(self):
        result = self.replace("    def run(self):\n        return 1", "    def run(self):\n        return 10")
        self.assertIn("ignorando espaços no fim das linhas", result)
        self.assertIn("        return 10\n", self.path.read_text())

    def test_ignores_indentation_and_reindents_new_text(self):
        result = self.replace("def stop(self):\n    return 2", "def stop(self):\n    if True:\n        return 3")
        self.assertIn("ignorando diferenças de indentação", result)
        self.assertTrue(self.path.read_text().endswith(
            "    def stop(self):\n        if True:\n            return 3\n"
        ))

    def test_ambiguous_fuzzy_match_is_refused(self):
        result = self.replace("return", "return 0")
        self.assertIn("Erro", result)

    def test_not_found_shows_closest_snippet_and_keeps_file(self):
        before = self.path.read_text()
        result = self.replace("def stop(self):\n    return 99", "x")
        self.assertIn("texto não encontrado", result)
        self.assertIn("linhas 5-6", result)
        self.assertEqual(self.path.read_text(), before)

    def test_unknown_argument_produces_warning(self):
        result = self.replace("return 2", "return 3", motivo="teste")
        self.assertIn("argumentos desconhecidos ignorados: motivo", result)


class NudgeTests(unittest.TestCase):
    def test_nudges_only_when_the_model_stopped_too_early(self):
        self.assertIn("vazia", nudge_for("", False, ""))
        self.assertIn("[ ] testar", nudge_for("Pronto!", True, "[ ] testar"))
        self.assertIsNone(nudge_for("Pronto!", False, ""))


if __name__ == "__main__":
    unittest.main()
