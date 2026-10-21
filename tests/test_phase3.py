from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from agent_harness import agent, llm


def chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    choices = [] if usage else [NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish_reason)]
    return NS(choices=choices, usage=usage)


def call_piece(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


class StreamingTests(unittest.TestCase):
    def test_rebuilds_text_and_tool_calls_sent_in_pieces(self):
        chunks = [
            chunk(content="Vou "),
            chunk(content="ler."),
            chunk(tool_calls=[call_piece(0, id="c1", name="read_file", arguments='{"pa')]),
            chunk(tool_calls=[call_piece(0, arguments='th": "a.py"}')]),
            chunk(tool_calls=[call_piece(1, id="c2", name="bash", arguments='{"command": "ls"}')]),
            chunk(finish_reason="tool_calls"),
            chunk(usage=NS(prompt_tokens=50, completion_tokens=7)),
        ]
        received = []
        with mock.patch.object(llm.client.chat.completions, "create", return_value=iter(chunks)):
            message, usage, _, _ = llm.call_llm([{"role": "user", "content": "x"}], on_text=received.append)

        self.assertEqual(received, ["Vou ", "ler."])
        self.assertEqual(message.content, "Vou ler.")
        self.assertEqual([(c.id, c.function.name) for c in message.tool_calls], [("c1", "read_file"), ("c2", "bash")])
        self.assertEqual(json.loads(message.tool_calls[0].function.arguments), {"path": "a.py"})
        self.assertEqual(usage["prompt_tokens"], 50)

    def test_tool_only_answer_keeps_empty_content_in_history(self):
        chunks = [chunk(tool_calls=[call_piece(0, id="c1", name="bash", arguments='{"command": "ls"}')])]
        with mock.patch.object(llm.client.chat.completions, "create", return_value=iter(chunks)):
            message, _, _, _ = llm.call_llm([{"role": "user", "content": "x"}], on_text=lambda _: None)
        self.assertEqual(message.model_dump(exclude_none=True)["content"], "")

    def test_without_callback_uses_a_normal_request(self):
        response = NS(choices=[NS(message=llm.ChatCompletionMessage(role="assistant", content="oi"), finish_reason="stop")], usage=None)
        with mock.patch.object(llm.client.chat.completions, "create", return_value=response) as create:
            message, _, _, _ = llm.call_llm([{"role": "user", "content": "x"}])
        self.assertEqual(message.content, "oi")
        self.assertNotIn("stream", create.call_args.kwargs)
        self.assertEqual(create.call_args.kwargs["temperature"], llm.TEMPERATURE)


class ProjectInstructionsTests(unittest.TestCase):
    def test_agents_md_is_loaded_and_limited(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(agent, "PROJECT_ROOT", root):
                self.assertEqual(agent.project_instructions(), "")
                (root / "AGENTS.md").write_text("Use pytest.\n")
                self.assertIn("Use pytest.", agent.project_instructions())
                (root / "AGENTS.md").write_text("x" * (agent.MAX_AGENTS_MD_CHARS + 10))
                self.assertIn("[AGENTS.md reduzido]", agent.project_instructions())


if __name__ == "__main__":
    unittest.main()
