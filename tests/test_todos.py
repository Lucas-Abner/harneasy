from __future__ import annotations

import unittest

from agent_harness import todos as todo_module


class TodoValidationTests(unittest.TestCase):
    def setUp(self):
        todo_module.TODOS[:] = []

    def tearDown(self):
        todo_module.TODOS[:] = []

    def test_accepts_valid_plan_and_reports_active_task(self):
        todo_module.write_todos([
            {"status": "done", "content": "inspect code"},
            {"status": "in_progress", "content": "fix loop"},
            {"status": "pending", "content": "add tests"},
        ])
        self.assertEqual(todo_module.active_todo()["content"], "fix loop")
        self.assertTrue(todo_module.has_open_todos())

    def test_rejects_multiple_active_tasks_without_mutating_existing_plan(self):
        todo_module.write_todos([{"status": "pending", "content": "original"}])
        with self.assertRaises(ValueError):
            todo_module.write_todos([
                {"status": "in_progress", "content": "first"},
                {"status": "in_progress", "content": "second"},
            ])
        self.assertEqual(todo_module.TODOS, [{"status": "pending", "content": "original"}])

    def test_rejects_invalid_status_and_empty_content(self):
        with self.assertRaises(ValueError):
            todo_module.write_todos([{"status": "finished", "content": "x"}])
        with self.assertRaises(ValueError):
            todo_module.write_todos([{"status": "pending", "content": "  "}])


if __name__ == "__main__":
    unittest.main()
