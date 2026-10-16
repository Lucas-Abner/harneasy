import subprocess
import json
from .skills import read_skill
from .todos import write_todos
from .permissions import check
from .subagents import TASK_SCHEMA, task
from .sandbox import run as sandbox_run


def bash(command):
    windows = False
    if command.startswith("Powershell"):
        windows = True
        command = command[len("Powershell"):].strip()

    if windows:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout + result.stderr
    else:
        result = sandbox_run(command)
        return result.stdout + result.stderr

def read_file(path: str) -> str:
    with open(path, 'r') as f:
        return f.read()

def write_file(path: str, conteudo: str) -> str:
    with open(path, 'w') as f:
        f.write(conteudo)
    return f'Wrote { path }'

def str_replace(path: str, old: str, new: str, allow_multi_edit: bool = False):
    with open(path) as f:
        content = f.read()

    count = content.count(old)

    if count == 0:
        return f'Erro: valor antigo não encontrado em {path}'

    if count > 1 and not allow_multi_edit:
        return (
            f'Erro: valor antigo com {count} ocorrências em {path}'
            'Add allow_multi_edit=True para permitir a substituição de todas as ocorrências.'
            'Se você deseja substituir todas as ocorrências, use allow_multi_edit=True.'
        )

    with open(path, 'w') as f:
        content = content.replace(old, new)
        f.write(content)

    return f'Substituído {count} ocorrências de em {path}'


def update_todos(todos: list[dict[str, str]]) -> str:
    return write_todos(todos)

def execute(tool_call):
    from .ui import ui


    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except Exception as error:
        return f"Erro ao analisar argumentos da ferramenta: {error}"

    action, reason = check(name, args)

    if action == 'deny':
        return args, f"Permissão negada para executar a ferramenta {name}. Razão {reason}"
    if action == 'ask' and not ui.confirm(reason):
        return args, f"Permissão negada para executar a ferramenta {name}. Razão: {reason}"
    return args, TOOLS[name](**args)

TOOLS_SCHEMAS = [
    {
        'type': 'function',
        'function': {
            'name': 'bash',
            'description': 'Rode o shell command e return as saidas.',
            'parameters': {
            'type': 'object',
            'properties': {
                'command': {
                    'type': 'string',
                    'description': 'Oshell command da rodada',
                }
            },
            'required': ['command'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Leia o conteúdo de um arquivo e retorne como uma string.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'O caminho do arquivo a ser lido.',
                    }
                },
                'required': ['path'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_skill',
            'description': 'Leia o conteúdo de uma skill pelo nome.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'O nome da skill.',
                    }
                },
                'required': ['name'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_file',
            'description': 'Escreva o conteúdo em um arquivo.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'O caminho do arquivo a ser escrito.',
                    },
                    'conteudo': {
                        'type': 'string',
                        'description': 'O conteúdo a ser escrito no arquivo.',
                    }
                },
                'required': ['path', 'conteudo'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'str_replace',
            'description': 'Substitua uma string antiga por uma nova em um arquivo.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'path': {
                        'type': 'string',
                        'description': 'O caminho do arquivo a ser modificado.',
                    },
                    'old': {
                        'type': 'string',
                        'description': 'A string antiga a ser substituída.',
                    },
                    'new': {
                        'type': 'string',
                        'description': 'A nova string que substituirá a antiga.',
                    },
                    'allow_multi_edit': {
                        'type': 'boolean',
                        'description': (
                            "Permitir substituição de múltiplas ocorrências. "
                            "Se False, apenas uma ocorrência será substituída."
                        ),
                    }
                },
                'required': ['path', 'old', 'new'],
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_todos',
            'description': 'Atualize a lista de tarefas da sessão. Use no máximo uma tarefa in_progress.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'todos': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'status': {
                                    'type': 'string',
                                    'enum': ['pending', 'in_progress', 'done'],
                                },
                                'content': {'type': 'string'},
                            },
                            'required': ['status', 'content'],
                        },
                    }
                },
                'required': ['todos'],
            }
        }
    },
    TASK_SCHEMA
]

TOOLS = {
    'bash': bash,
    'read_file': read_file,
    'read_skill': read_skill,
    'write_file': write_file,
    'str_replace': str_replace,
    'update_todos': update_todos,
    'task': task,
}