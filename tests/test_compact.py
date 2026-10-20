from __future__ import annotations

import unittest

from agent_harness.compact import safe_boundary


class CompactBoundaryTests(unittest.TestCase):
    def test_boundary_never_splits_multiple_tool_results(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "do the work"},
            {"role": "assistant", "tool_calls": [{"id": "1"}, {"id": "2"}]},
            {"role": "tool", "tool_call_id": "1", "content": "result one"},
            {"role": "tool", "tool_call_id": "2", "content": "result two"},
            {"role": "assistant", "content": "continued"},
        ]
        self.assertEqual(safe_boundary(messages, 3), 2)
        self.assertEqual(safe_boundary(messages, 4), 2)
        self.assertEqual(safe_boundary(messages, 5), 5)


if __name__ == "__main__":
    unittest.main()
