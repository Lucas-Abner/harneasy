from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_harness import agent, compact, llm, sandbox
from agent_harness.permissions import PROJECT_ROOT
from agent_harness.tools import _impossible_command, coerce_args, execute_tool
from agent_harness.ui import INTERRUPTED_RESULT, close_dangling_tool_calls


class ArgumentCoercionTests(unittest.TestCase):
    def test_numeric_strings_become_integers(self):
        args, error = coerce_args("read_file", {"path": "a.py", "start_line": "10", "max_lines": 5.0})
        self.assertIsNone(error)
        self.assertEqual(args, {"path": "a.py", "start_line": 10, "max_lines": 5})

    def test_boolean_and_json_array_strings_are_parsed(self):
        args, error = coerce_args("str_replace", {"path": "a", "old_str": "x", "new_str": "y", "allow_multi_edit": "True"})
        self.assertIsNone(error)
        self.assertIs(args["allow_multi_edit"], True)

        args, error = coerce_args("update_todos", {"todos": '[{"status": "pending", "content": "x"}]'})
        self.assertIsNone(error)
        self.assertEqual(args["todos"], [{"status": "pending", "content": "x"}])

    def test_uncoercible_value_returns_readable_error(self):
        _, error = coerce_args("read_file", {"path": "a.py", "start_line": "dez"})
        self.assertIn("'start_line' precisa ser do tipo integer", error)
        _, error = coerce_args("read_file", {"path": "a.py", "start_line": True})
        self.assertIsNotNone(error)

    def test_gateway_reads_file_with_string_line_numbers(self):
        with tempfile.NamedTemporaryFile("w", dir=PROJECT_ROOT, suffix=".txt", delete=False) as handle:
            handle.write("um\ndois\ntres\n")
        try:
            result = execute_tool("read_file", {"path": handle.name, "start_line": "2", "max_lines": "1"})
        finally:
            Path(handle.name).unlink()
        self.assertIn("linhas 2-2 de 3", result)
        self.assertIn("dois", result)


class NetworkTests(unittest.TestCase):
    def test_install_is_refused_with_a_reason_when_network_is_off(self):
        with mock.patch.dict(os.environ, {"HARNEASY_SANDBOX_NETWORK": "0"}):
            self.assertIn("rede está desligada", execute_tool("bash", {"command": "npm install jsdom"}))
            self.assertIsNone(_impossible_command("node --check js/app.js"))

    def test_install_is_possible_but_only_inside_the_project_when_network_is_on(self):
        with mock.patch.dict(os.environ, {"HARNEASY_SANDBOX_NETWORK": "1"}):
            self.assertIsNone(_impossible_command("npm install jsdom"))
            self.assertIn("dentro do projeto", _impossible_command("npm install -g jsdom"))
            self.assertIn("dentro do projeto", _impossible_command("pip install requests --user"))

    def test_background_processes_are_refused(self):
        for command in ["nohup npm start &", "python server.py &"]:
            with self.subTest(command=command):
                self.assertIn("segundo plano", _impossible_command(command))
        self.assertIsNone(_impossible_command("make test && echo ok"))

    def test_bubblewrap_shares_network_only_when_enabled(self):
        with mock.patch.object(sandbox.sys, "platform", "linux"), \
                mock.patch.object(sandbox.shutil, "which", return_value="/usr/bin/bwrap"):
            with mock.patch.dict(os.environ, {"HARNEASY_SANDBOX_NETWORK": "0"}):
                self.assertIn("--unshare-net", sandbox.wrap("true"))
            with mock.patch.dict(os.environ, {"HARNEASY_SANDBOX_NETWORK": "1"}), \
                    mock.patch.object(sandbox, "CACHE_DIRS", []):
                self.assertNotIn("--unshare-net", sandbox.wrap("true"))


class InterruptionTests(unittest.TestCase):
    def test_unanswered_tool_calls_receive_synthetic_results(self):
        messages = [
            {"role": "user", "content": "x"},
            {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
        ]
        close_dangling_tool_calls(messages)
        self.assertEqual([m.get("tool_call_id") for m in messages[2:]], ["a", "b", "c"])
        self.assertEqual(messages[-1]["content"], INTERRUPTED_RESULT)

    def test_complete_history_is_left_untouched(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "a"}]},
            {"role": "tool", "tool_call_id": "a", "content": "ok"},
            {"role": "user", "content": "next"},
        ]
        close_dangling_tool_calls(messages)
        self.assertEqual(len(messages), 3)


class OllamaContextTests(unittest.TestCase):
    def _fake_server(self, ps_responses):
        calls = []

        def fake(url, payload=None, *, timeout):
            calls.append(url.rsplit("/", 1)[-1])
            if url.endswith("/api/ps"):
                return ps_responses.pop(0)
            return {}

        return fake, calls

    def test_loads_model_before_reading_its_context(self):
        loaded = {"models": [{"name": "granite4.1:3b", "context_length": 4096}]}
        fake, calls = self._fake_server([{"models": []}, loaded])
        with mock.patch.object(llm, "_ollama_get", fake):
            self.assertEqual(llm.ollama_context_length("granite4.1:3b"), 4096)
        self.assertEqual(calls, ["version", "ps", "generate", "ps"])

    def test_untagged_model_name_matches_latest(self):
        fake, _ = self._fake_server([{"models": [{"name": "qwen:latest", "context_length": 8192}]}])
        with mock.patch.object(llm, "_ollama_get", fake):
            self.assertEqual(llm.ollama_context_length("qwen"), 8192)

    def test_non_ollama_server_returns_none(self):
        with mock.patch.object(llm, "_ollama_get", side_effect=OSError("404")):
            self.assertIsNone(llm.ollama_context_length("any"))

    def test_window_grows_to_what_ollama_allocated_when_not_configured(self):
        original = compact.CONTEXT_WINDOWS
        try:
            compact.CONTEXT_WINDOWS = 4200
            env = {k: v for k, v in os.environ.items() if k != "HARNEASY_CONTEXT_WINDOW"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(agent, "ollama_context_length", return_value=10000):
                self.assertIsNone(agent.check_context_window())
            self.assertEqual(compact.CONTEXT_WINDOWS, 10000)
        finally:
            compact.CONTEXT_WINDOWS = original

    def test_window_is_clamped_only_when_ollama_allocated_less(self):
        original = compact.CONTEXT_WINDOWS
        try:
            self.enterContext(mock.patch.dict(os.environ, {"HARNEASY_CONTEXT_WINDOW": "4200"}))
            compact.CONTEXT_WINDOWS = 4200
            with mock.patch.object(agent, "ollama_context_length", return_value=4096):
                warning = agent.check_context_window()
            self.assertEqual(compact.CONTEXT_WINDOWS, 4096)
            self.assertIn("OLLAMA_CONTEXT_LENGTH", warning)

            with mock.patch.object(agent, "ollama_context_length", return_value=32768):
                self.assertIsNone(agent.check_context_window())
            self.assertEqual(compact.CONTEXT_WINDOWS, 4096)
        finally:
            compact.CONTEXT_WINDOWS = original


if __name__ == "__main__":
    unittest.main()


class RepeatDetectorTests(unittest.TestCase):
    def test_same_command_after_an_edit_is_not_stagnation(self):
        import io
        import json as json_module

        from openai.types.chat import ChatCompletionMessage
        from rich.console import Console

        from agent_harness.ui import AgentUI, run_request

        target = str(PROJECT_ROOT / f"_repeat_test_{id(self)}.txt")  # new file: no read needed

        def call(name, **args):
            return {"id": f"c{len(script)}", "type": "function",
                    "function": {"name": name, "arguments": json_module.dumps(args)}}

        script = []
        for step in [
            call("bash", command="echo oi"),
            call("bash", command="echo oi"),
            call("write_file", path=target, content="novo"),
            call("bash", command="echo oi"),
            None,
        ]:
            script.append(step)
        replies = iter(
            ChatCompletionMessage(role="assistant", content="" if step else "pronto", tool_calls=[step] if step else None)
            for step in script
        )

        ui = AgentUI(model="fake", tool_names=[])
        ui.console = Console(file=io.StringIO())
        self.enterContext(mock.patch.dict(os.environ, {"HARNEASY_FINAL_REVIEW": "0", "HARNEASY_VERIFY_COMMAND": "off"}))
        try:
            messages, status = run_request(
                ui, [{"role": "system", "content": "s"}], "tarefa",
                call_llm=lambda messages, **kw: (next(replies), {}, None, None),
                reminder=lambda: {"role": "user", "content": "env"},
                active_todo=lambda: "pensando", todos=lambda: "", has_open_todos=lambda: False,
            )
        finally:
            Path(target).unlink(missing_ok=True)

        self.assertEqual(status, "done")
        results = [m["content"] for m in messages if m["role"] == "tool"]
        self.assertTrue(all("estagnação" not in r for r in results), results)
        self.assertIn("oi", results[-1])
