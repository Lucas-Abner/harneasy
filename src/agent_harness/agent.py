import os

from .context import git_branch, reminder
from .llm import call_llm
from .skills import skills_prompt
from .tools import TOOLS
from .ui import run_with_ui
from .todos import active_todo


SYSTEM_PROMPT = f"""Você é um agente de codificação.
Use comandos de shell compatíveis com o ambiente atual.
Para ler arquivos, use a ferramenta read_file.

Você tem acesso a uma lista de habilidades (skills) que podem ser usadas para realizar tarefas específicas.
Se a solicitação do usuário corresponder a uma habilidade, use a função read_skill para ler o conteúdo do arquivo SKILL.md correspondente e execute as instruções contidas nele.

{skills_prompt()}
"""


def main() -> None:
    """Start the interactive agent harness."""
    run_with_ui(
        system_prompt=SYSTEM_PROMPT,
        call_llm=call_llm,
        tools=TOOLS,
        reminder=reminder,
        branch=git_branch(),
        model=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        active_todo=active_todo
    )


if __name__ == "__main__":
    main()