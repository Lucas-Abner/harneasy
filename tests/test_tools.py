from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.permissions import PROJECT_ROOT, is_generated_output
from agent_harness.tools import (
    MAX_TOOL_OUTPUT_CHARS,
    TOOLS_SCHEMAS,
    _bounded_output,
    execute_tool,
)


class ToolGatewayTests(unittest.TestCase):
    def test_all_tool_schemas_match_registered_tools(self):
        from agent_harness.tools import TOOLS
        schema_names = {schema["function"]["name"] for schema in TOOLS_SCHEMAS}
        self.assertEqual(schema_names, set(TOOLS))
        for schema in TOOLS_SCHEMAS:
            with self.subTest(tool=schema["function"]["name"]):
                parameters = schema["function"]["parameters"]
                self.assertEqual(parameters.get("type"), "object")
                self.assertIsInstance(parameters.get("properties"), dict)
                self.assertTrue(set(parameters.get("required", [])) <= set(parameters["properties"]))
        read_file_schema = next(s for s in TOOLS_SCHEMAS if s["function"]["name"] == "read_file")
        self.assertEqual(set(read_file_schema["function"]["parameters"]["properties"]), {"path", "start_line", "max_lines"})

    def test_dangerous_command_is_denied_even_if_confirmation_would_be_yes(self):
        asked = []
        result = execute_tool("bash", {"command": "rm -rf do-not-delete"}, confirm=lambda why: asked.append(why) or True)
        self.assertIn("Permissão negada", result)
        self.assertEqual(asked, [])

    def test_unknown_command_needs_explicit_approval(self):
        asked = []
        result = execute_tool("bash", {"command": "touch should-not-be-created.txt"}, confirm=lambda why: asked.append(why) or False)
        self.assertIn("requer aprovação explícita", result)
        self.assertEqual(len(asked), 1)
        self.assertFalse((PROJECT_ROOT / "should-not-be-created.txt").exists())

    def test_write_file_is_confined_to_workspace(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            target = Path(temp_dir) / "created.txt"
            result = execute_tool("write_file", {"path": str(target), "conteudo": "hello"})
            self.assertIn("Arquivo escrito", result)
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "outside.txt"
            result = execute_tool("write_file", {"path": str(target), "conteudo": "blocked"})
            self.assertIn("Permissão negada", result)
            self.assertFalse(target.exists())

    def test_large_output_is_bounded_and_remains_readable(self):
        value = "".join(f"line {i:04d}\n" for i in range(1500))
        preview = _bounded_output(value)
        self.assertLessEqual(len(preview), MAX_TOOL_OUTPUT_CHARS)
        marker = "A saída completa foi salva em "
        self.assertIn(marker, preview)
        # Confirm that the generated temporary output is registered for safe re-reading.
        import re
        match = re.search(r"(/[^ ]*harneasy-output-[^ ]+|[A-Za-z]:\\\\[^ ]*harneasy-output-[^ ]+)", preview)
        self.assertIsNotNone(match)
        output_path = Path(match.group(1).rstrip(".,"))
        self.assertTrue(is_generated_output(output_path))
        excerpt = execute_tool("read_file", {"path": str(output_path), "start_line": 2, "max_lines": 2})
        self.assertIn("line 0001", excerpt)
        self.assertIn("line 0002", excerpt)

    def test_read_file_can_return_a_line_window(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            target = Path(temp_dir) / "sample.txt"
            target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            result = execute_tool("read_file", {"path": str(target), "start_line": 2, "max_lines": 2})
            self.assertIn("two", result)
            self.assertIn("three", result)
            self.assertNotIn("one", result)
            self.assertNotIn("four", result)


if __name__ == "__main__":
    unittest.main()
