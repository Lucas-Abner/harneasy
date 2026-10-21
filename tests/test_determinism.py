from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from openai.types.chat import ChatCompletionMessage
from rich.console import Console

from agent_harness import llm
from agent_harness.permissions import PROJECT_ROOT
from agent_harness.tools import execute_tool, forget_reads
from agent_harness.ui import AgentUI, run_request


def fake_ui() -> AgentUI:
    ui = AgentUI(model="fake", tool_names=[], auto_confirm=True)
    ui.console = Console(file=io.StringIO())
    return ui


def scripted_llm(steps):
    """A fake model that answers with the given tool calls, then 'pronto'."""
    replies = []
    for index, step in enumerate(steps):
        if step is None:
            replies.append(ChatCompletionMessage(role="assistant", content="pronto"))
        else:
            name, args = step
            call = {"id": f"c{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            replies.append(ChatCompletionMessage(role="assistant", content="", tool_calls=[call]))
    replies = iter(replies)
    seen = []

    def call_llm(messages, **kwargs):
        seen.append(messages)
        return next(replies), {}, None, None

    call_llm.seen = seen
    return call_llm


def run(call_llm):
    return run_request(
        fake_ui(), [{"role": "system", "content": "s"}], "tarefa",
        call_llm=call_llm, reminder=lambda: {"role": "user", "content": "env"},
        active_todo=lambda: "pensando", todos=lambda: "", has_open_todos=lambda: False,
    )


class SeedTests(unittest.TestCase):
    def test_requests_use_temperature_zero_and_a_seed(self):
        response = NS(choices=[NS(message=ChatCompletionMessage(role="assistant", content="oi"), finish_reason="stop")], usage=None)
        with mock.patch.object(llm.client.chat.completions, "create", return_value=response) as create:
            llm.call_llm([{"role": "user", "content": "x"}])
        self.assertEqual(create.call_args.kwargs["temperature"], 0.0)
        self.assertEqual(create.call_args.kwargs["seed"], 42)


class TurnBudgetTests(unittest.TestCase):
    def test_reminder_shows_the_turn_number(self):
        call_llm = scripted_llm([None])
        run(call_llm)
        self.assertIn("turno: 1 de", call_llm.seen[0][-1]["content"])


class RepeatedReadTests(unittest.TestCase):
    def setUp(self):
        forget_reads()
        self.path = PROJECT_ROOT / f"_read_test_{id(self)}.txt"
        self.path.write_text("conteúdo\n")

    def tearDown(self):
        self.path.unlink(missing_ok=True)
        forget_reads()

    def test_second_identical_read_gets_a_notice_and_third_gets_content(self):
        read = lambda: execute_tool("read_file", {"path": str(self.path)})
        self.assertIn("conteúdo", read())
        self.assertIn("Você já leu", read())
        self.assertIn("conteúdo", read())

    def test_changed_file_or_compaction_sends_content_again(self):
        execute_tool("read_file", {"path": str(self.path)})
        os.utime(self.path, (1, 1))
        self.assertIn("conteúdo", execute_tool("read_file", {"path": str(self.path)}))
        forget_reads()
        self.assertIn("conteúdo", execute_tool("read_file", {"path": str(self.path)}))

    def test_subagent_reads_are_never_deduplicated(self):
        execute_tool("read_file", {"path": str(self.path)})
        self.assertIn("conteúdo", execute_tool("read_file", {"path": str(self.path)}, readonly=True))


class DisabledToolsTests(unittest.TestCase):
    def test_disabled_tools_are_hidden_and_rejected(self):
        code = (
            "from agent_harness.tools import TOOLS, TOOLS_SCHEMAS, execute_tool\n"
            "print(sorted(TOOLS) == sorted(s['function']['name'] for s in TOOLS_SCHEMAS), 'task' in TOOLS,"
            " execute_tool('task', {'description': 'x'}))\n"
        )
        env = {**os.environ, "HARNEASY_DISABLED_TOOLS": "task, read_skill"}
        out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.strip(), "True False Erro: ferramenta desconhecida: task.")


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.path = PROJECT_ROOT / f"_verify_test_{id(self)}.txt"

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def run_with_verify(self, command, steps):
        call_llm = scripted_llm(steps)
        with mock.patch.dict(os.environ, {"HARNEASY_VERIFY_COMMAND": command, "HARNEASY_FINAL_REVIEW": "0"}):
            messages, status = run(call_llm)
        reminders = [m["content"] for m in messages if m["role"] == "user" and "verificação automática" in m["content"]]
        return status, reminders

    def test_failed_verification_sends_the_model_back_to_work(self):
        edit = ("write_file", {"path": str(self.path), "content": "x"})
        # 'ls' of a missing file exits with an error, like a failing test.
        status, reminders = self.run_with_verify(f"ls {self.path}.nao_existe", [edit, None, None])
        self.assertEqual(status, "done")
        self.assertEqual(len(reminders), 1)
        self.assertIn("falhou", reminders[0])

    def test_passing_verification_finishes_at_once(self):
        edit = ("write_file", {"path": str(self.path), "content": "x"})
        status, reminders = self.run_with_verify(f"ls {self.path}", [edit, None])
        self.assertEqual((status, reminders), ("done", []))

    def test_no_edit_means_no_verification(self):
        status, reminders = self.run_with_verify("ls /nao/existe", [None])
        self.assertEqual((status, reminders), ("done", []))


if __name__ == "__main__":
    unittest.main()
