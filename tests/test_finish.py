from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_harness import context
from agent_harness.permissions import PROJECT_ROOT
from agent_harness.skills import skill_body, suggest_skill
from agent_harness.tools import UNDO_STACK, changes_since, execute_tool, pending_problems
from agent_harness.ui import run_verification
from test_determinism import fake_ui, run, scripted_llm


class SkillRoutingTests(unittest.TestCase):
    def test_requests_pick_the_expected_skill(self):
        cases = {
            "Em calc.py há dois bugs. Corrija os dois.": "corrigir-bug",
            "Os testes em test_stack.py estão falhando. Rode-os com pytest e corrija stack.py.": "corrigir-bug",
            "Renomeie a função get_user para fetch_user em todo o projeto.": "refatorar",
            "Renomeie a classe Pedido para Order": "refatorar",
            "Crie um projeto Python de gerenciador de tarefas com testes": "planejar-projeto",
            "Crie um site de portfólio com HTML e CSS": "iniciar-projeto-web",
            "Adicione a chave port com o valor 8080": "implementar-funcionalidade",
            "Escreva testes para o módulo de pagamento": "escrever-testes",
            "faça commit das mudanças": "checkpoint-git",
            "continue": "retomar-trabalho",
            "Como funciona a autenticação?": "explorar-codigo",
        }
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(suggest_skill(request), expected)

    def test_unrelated_requests_get_no_skill(self):
        for request in ["oi, tudo bem?", "obrigado", "qual a versão do python?"]:
            with self.subTest(request=request):
                self.assertIsNone(suggest_skill(request))

    def test_skill_is_injected_into_the_request_without_frontmatter(self):
        call_llm = scripted_llm([None])
        run_request_messages, _ = run_with(call_llm, "Renomeie a função a para b")
        first_user = run_request_messages[1]["content"]
        self.assertIn('<skill name="refatorar">', first_user)
        self.assertIn("# Refatorar", first_user)
        self.assertNotIn("triggers:", first_user)
        self.assertEqual(skill_body("refatorar").splitlines()[0], "# Refatorar")


def run_with(call_llm, request, **env):
    from agent_harness.ui import run_request

    settings = {"HARNEASY_VERIFY_COMMAND": "off", **env}
    with mock.patch.dict(os.environ, settings):
        return run_request(
            fake_ui(), [{"role": "system", "content": "s"}], request,
            call_llm=call_llm, reminder=lambda: {"role": "user", "content": "env"},
            active_todo=lambda: "pensando", todos=lambda: "", has_open_todos=lambda: False,
        )


def reminders(messages, marker):
    return [m["content"] for m in messages if m["role"] == "user" and marker in m["content"]]


class FinishCheckTests(unittest.TestCase):
    def setUp(self):
        self.created: list[Path] = []

    def tearDown(self):
        for path in self.created:
            path.unlink(missing_ok=True)

    def path(self, name):
        path = PROJECT_ROOT / f"_{id(self)}_{name}"
        self.created.append(path)
        return path

    def test_typo_in_file_name_and_missing_module_are_reported(self):
        # The real failure from the benchmark: "sluggify.py" with unidecode.
        wrong = self.path("sluggify.py")
        wanted = f"_{id(self)}_slugify.py"
        steps = [("write_file", {"path": str(wrong), "content": "import unidecode_nao_existe\n"}), None, None, None]
        messages, status = run_with(scripted_llm(steps), f"Crie o arquivo {wanted}", HARNEASY_FINAL_REVIEW="0")
        # The problem is never fixed: the harness insists twice (the limit), then gives up.
        problems = reminders(messages, "Ainda há problemas")
        self.assertEqual(len(problems), 2)
        problem = problems[0]
        self.assertIn("módulos não instalados: unidecode_nao_existe", problem)
        self.assertIn(f"O pedido cita {wanted}, mas esse arquivo não existe", problem)
        self.assertEqual(status, "done")

    def test_data_files_named_in_the_request_are_not_required(self):
        code = self.path("app.py")
        problems = pending_problems({str(code)}, "salve em tarefas.json e config.yaml")
        self.assertEqual(problems, [])

    def test_final_review_shows_request_and_real_diff_once(self):
        target = self.path("config.json")
        target.write_text('{"debug": true}\n')
        execute_tool("read_file", {"path": str(target)})
        steps = [("write_file", {"path": str(target), "content": '{"debug": false}\n'}), None, None]
        messages, status = run_with(scripted_llm(steps), "Desligue o debug e adicione port 8080")
        [review] = reminders(messages, "Revisão final")
        self.assertIn("Desligue o debug e adicione port 8080", review)
        self.assertIn('-{"debug": true}', review)
        self.assertIn('+{"debug": false}', review)
        self.assertEqual(status, "done")

    def test_no_edits_means_no_review(self):
        messages, _ = run_with(scripted_llm([None]), "o que é isso?")
        self.assertEqual(reminders(messages, "Revisão final"), [])

    def test_changes_since_marks_new_files(self):
        mark = len(UNDO_STACK)
        new = self.path("novo.py")
        execute_tool("write_file", {"path": str(new), "content": "A = 1\nB = 2\n"})
        self.assertIn("(novo arquivo, 2 linhas)", changes_since(mark))


class DefaultVerifyTests(unittest.TestCase):
    def test_projects_with_tests_are_verified_with_pytest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with mock.patch.object(context, "PROJECT_ROOT", root), mock.patch.dict(os.environ, {"HARNEASY_VERIFY_COMMAND": ""}):
                self.assertEqual(context.verify_command(), "")
                (root / "test_app.py").write_text("")
                self.assertEqual(context.verify_command(), "python -m pytest -q")
                with mock.patch.dict(os.environ, {"HARNEASY_VERIFY_COMMAND": "off"}):
                    self.assertEqual(context.verify_command(), "")
                with mock.patch.dict(os.environ, {"HARNEASY_VERIFY_COMMAND": "make test"}):
                    self.assertEqual(context.verify_command(), "make test")

    def test_missing_pytest_is_not_reported_as_a_failing_test(self):
        output = "/usr/bin/python: No module named pytest\n[processo finalizado com código 1]"
        with mock.patch("agent_harness.ui.execute_tool", return_value=output):
            self.assertIsNone(run_verification(fake_ui(), "python -m pytest -q"))

    def test_finishing_after_failing_tests_is_refused(self):
        failing = "1 failed, 1 passed\n[processo finalizado com código 1]"
        steps = [("bash", {"command": "python -m pytest -q"}), None, None, None]
        with mock.patch("agent_harness.ui.execute_tool", return_value=failing):
            messages, _ = run_with(scripted_llm(steps), "corrija os testes", HARNEASY_FINAL_REVIEW="0")
        self.assertEqual(len(reminders(messages, "testes falhou")), 2)  # insists twice, then gives up

    def test_wandering_without_progress_is_stopped(self):
        steps = [("bash", {"command": f"echo {i}"}) for i in range(20)]
        with mock.patch("agent_harness.ui.execute_tool", return_value="ok"):
            messages, status = run_with(scripted_llm(steps), "tarefa", HARNEASY_IDLE_LIMIT="3")
        self.assertEqual(status, "stuck")
        self.assertEqual(len(reminders(messages, "sem editar arquivos")), 1)
        self.assertEqual(messages[-1]["role"], "tool")  # history is valid: every call has its result

    def test_repeated_call_is_reported(self):
        steps = [("bash", {"command": "echo oi"})] * 3 + [None]
        with mock.patch("agent_harness.ui.execute_tool", return_value="oi"):
            messages, _ = run_with(scripted_llm(steps), "tarefa", HARNEASY_FINAL_REVIEW="0")
        self.assertIn("estagnação", [m for m in messages if m["role"] == "tool"][-1]["content"])

    def test_reading_new_files_is_not_wandering(self):
        steps = [("read_file", {"path": f"arquivo{i}.py"}) for i in range(15)] + [None]
        with mock.patch("agent_harness.ui.execute_tool", return_value="conteúdo"):
            _, status = run_with(scripted_llm(steps), "tarefa", HARNEASY_IDLE_LIMIT="3", HARNEASY_FINAL_REVIEW="0")
        self.assertEqual(status, "done")


if __name__ == "__main__":
    unittest.main()
