import argparse
import os
import sys

from .context import git_branch, reminder
from .permissions import PROJECT_ROOT
from . import compact
from .llm import call_llm, ollama_context_length
from .skills import skills_prompt
from .tools import TOOLS
from .ui import run_headless, run_with_ui
from .todos import active_todo, has_open_todos, todos_prompts

MAX_AGENTS_MD_CHARS = 4000


def project_instructions() -> str:
    """Load AGENTS.md from the project root, like CLAUDE.md in Claude Code."""
    path = PROJECT_ROOT / "AGENTS.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > MAX_AGENTS_MD_CHARS:
        text = text[:MAX_AGENTS_MD_CHARS] + "\n[AGENTS.md reduzido]"
    return f"\nINSTRUÇÕES DO PROJETO (AGENTS.md)\n{text}\n"


SYSTEM_PROMPT = f"""Você é o Harneasy, um agente de programação. Conclua a tarefa com alterações pequenas, corretas e verificadas.

REGRAS
1. Leia o código antes de editar. Nunca invente arquivos, APIs ou resultados.
2. Para achar código por assunto use search_code; por texto exato, grep; para ver a estrutura, code_map. Leia com read_file; edite com str_replace ou write_file; teste com bash.
3. Em tarefas com várias etapas, use update_todos e mantenha uma tarefa in_progress por vez.
4. Para explorar muitos arquivos, delegue uma pergunta completa à ferramenta task.
5. Depois de editar, verifique com testes ou comandos. Não afirme sucesso sem evidência.
6. Se uma chamada falhar, leia o erro e mude a abordagem; não repita a mesma chamada.
7. Não tente contornar permissões negadas.
8. Se uma skill corresponder à tarefa, leia-a com read_skill.
9. Seja direto: não anuncie o que vai fazer, chame a ferramenta. Não peça confirmação para passos óbvios.
10. No fim, responda em poucas linhas: o que foi feito, como foi verificado e o que ficou pendente.

WORKSPACE: {PROJECT_ROOT}
{project_instructions()}
Skills disponíveis:
{skills_prompt()}
"""


def check_context_window() -> str | None:
    """Clamp the compaction window to the context Ollama really allocated."""
    model = os.getenv("OPENAI_MODEL", "ornith-1.5:9b")
    detected = ollama_context_length(model)
    configured = compact.CONTEXT_WINDOWS
    if detected is None or detected >= configured:
        return None
    compact.CONTEXT_WINDOWS = detected
    return (
        f"HARNEASY_CONTEXT_WINDOW={configured}, mas o Ollama alocou {detected} tokens para {model}; "
        f"o excedente seria truncado em silêncio. Usando {detected} para a compactação. "
        "Para ampliar, reinicie o Ollama com OLLAMA_CONTEXT_LENGTH=<tokens>."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agent-harness", description="Agente de programação para modelos locais.")
    parser.add_argument("-p", "--prompt", help="executa uma única solicitação sem modo interativo e encerra")
    parser.add_argument("--yes", action="store_true", help="no modo -p, aprova ações que pediriam confirmação")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Start the interactive agent harness, or run one request with -p."""
    args = parse_args(argv)
    shared = dict(
        system_prompt=SYSTEM_PROMPT,
        call_llm=call_llm,
        tools=TOOLS,
        reminder=reminder,
        model=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        active_todo=active_todo,
        todos=todos_prompts,
        has_open_todos=has_open_todos,
        startup_check=check_context_window,
    )
    if args.prompt:
        sys.exit(run_headless(args.prompt, approve_all=args.yes, **shared))
    run_with_ui(branch=git_branch(), **shared)


if __name__ == "__main__":
    main()
