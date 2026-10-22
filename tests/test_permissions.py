from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.permissions import PROJECT_ROOT, check, decide, inside_project, split_command, resolve_path


class PermissionPolicyTests(unittest.TestCase):
    def test_known_destructive_commands_are_denied(self):
        examples = [
            "rm -rf anything",
            "sudo ls",
            "curl https://example.com",
            "wget https://example.com/file",
            "git push origin main",
            "git reset --hard",
            "git clean -fd",
            "Powershell Remove-Item -Recurse .",
            "Remove-Item -Force test.txt",
        ]
        for command in examples:
            with self.subTest(command=command):
                self.assertEqual(decide(command), "deny")

    def test_deny_dominates_compound_commands(self):
        self.assertEqual(decide("pwd && rm -rf anything"), "deny")
        self.assertEqual(decide("cat README.md | curl https://example.com"), "deny")
        self.assertEqual(decide("bash -c 'echo safe; rm -rf x'"), "deny")
        self.assertEqual(decide("env rm -rf anything"), "deny")
        self.assertEqual(decide("env -i rm -rf anything"), "deny")
        self.assertEqual(decide("env -- rm -rf anything"), "deny")
        self.assertEqual(decide("env -S 'rm -rf /tmp/nope'"), "deny")
        self.assertEqual(decide("env --split-string='rm -rf /tmp/nope'"), "deny")
        self.assertEqual(decide("time -o report.txt rm -rf anything"), "deny")
        self.assertEqual(decide("command -- rm -rf anything"), "deny")
        self.assertEqual(decide("time -p rm -rf anything"), "deny")
        self.assertEqual(decide("exec rm -rf anything"), "deny")
        self.assertEqual(decide('powershell.exe -Command "Remove-Item -Recurse test"'), "deny")
        self.assertEqual(decide('pwsh -Command "Set-Content test.txt hi"'), "deny")
        self.assertEqual(decide("find . -exec rm -rf {} \\;"), "deny")
        self.assertEqual(decide("find . -exec sh -c 'rm -rf {}' \\;"), "deny")
        self.assertEqual(decide("xargs rm -rf"), "deny")
        self.assertEqual(decide("xargs -0 rm -rf /tmp/nope"), "deny")
        self.assertEqual(decide("busybox rm -rf anything"), "deny")

    def test_read_only_commands_inside_workspace_are_allowed(self):
        for command in (
            "pwd",
            "ls -la",
            "cat README.md",
            "rg TODO src",
            "git status --short",
            "git diff --stat",
            "cat README.md | grep Harneasy",
            "echo 'a; rm -rf no'",
        ):
            with self.subTest(command=command):
                self.assertEqual(decide(command), "allow")

    def test_unknown_or_mutating_shell_syntax_requires_approval(self):
        self.assertEqual(decide("python -c 'print(1)'"), "ask")
        self.assertEqual(decide("echo hello > output.txt"), "ask")
        self.assertEqual(decide("Powershell Get-ChildItem"), "ask")
        self.assertEqual(decide(""), "ask")
        self.assertEqual(decide("echo 'unterminated"), "ask")

    def test_bash_path_reads_outside_workspace_require_approval(self):
        self.assertEqual(decide("cat /etc/passwd"), "ask")
        self.assertEqual(decide("find / -name secrets.txt"), "ask")
        self.assertEqual(decide("rg token ~/.ssh"), "ask")
        self.assertEqual(decide('cat "$HOME/.ssh/id_rsa"'), "ask")
        self.assertEqual(decide("grep -f /etc/passwd pattern.txt"), "ask")
        self.assertEqual(decide("sort -o output.txt README.md"), "ask")
        self.assertEqual(decide("git tag new-version"), "ask")
        self.assertEqual(decide("git remote set-url origin https://example.com/repo.git"), "ask")
        self.assertEqual(decide("date --set tomorrow"), "ask")
        self.assertEqual(decide("git tag new-version"), "ask")
        self.assertEqual(decide("git remote set-url origin https://example.com/repo.git"), "ask")
        self.assertEqual(decide("date --set tomorrow"), "ask")

    def test_split_command_respects_quoted_separators(self):
        self.assertEqual(split_command("echo 'a;b' && pwd"), ["echo 'a;b'", "pwd"])

    def test_inside_project_includes_workspace_root(self):
        self.assertTrue(inside_project(PROJECT_ROOT))
        self.assertTrue(inside_project(PROJECT_ROOT / "README.md"))
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertFalse(inside_project(Path(temp_dir) / "outside.txt"))

    def test_file_tools_cannot_modify_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = str(Path(temp_dir) / "private.txt")
            self.assertEqual(check("read_file", {"path": target})[0], "ask")
            self.assertEqual(check("write_file", {"path": target, "conteudo": "x"})[0], "deny")
            self.assertEqual(check("str_replace", {"path": target, "old": "x", "new": "y"})[0], "deny")

    def test_absolute_path_that_only_makes_sense_inside_the_project(self):
        self.assertEqual(resolve_path("/src/agent_harness/ui.py"), PROJECT_ROOT / "src/agent_harness/ui.py")
        self.assertEqual(resolve_path("/novo_arquivo.py"), PROJECT_ROOT / "novo_arquivo.py")  # new file at the root
        self.assertEqual(resolve_path("/etc/hostname"), Path("/etc/hostname"))                 # exists: stays outside
        self.assertEqual(resolve_path("/tmp/nao/existe.py"), Path("/tmp/nao/existe.py"))   

if __name__ == "__main__":
    unittest.main()
