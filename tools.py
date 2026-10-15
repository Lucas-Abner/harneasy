import subprocess

def bash(command):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout + result.stderr

def read_file(path: str) -> str:
    with open(path, 'r') as f:
        return f.read()

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
    }
]

TOOLS = {
    'bash': bash,
    'read_file': read_file
}