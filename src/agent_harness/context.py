import os
import subprocess
from datetime import datetime
from .todos import todos_prompts

from pathlib import Path

SEEN = {}

def note_read(path):
    SEEN[path] = os.path.getmtime(path)

def states_file():
    return [p for p, mtime in SEEN.items() if os.path.getmtime(p) > mtime]

def git_branch():
    result = subprocess.run(
        'git branch --show-current', shell=True, capture_output=True, text=True
    )

    return result.stdout.strip()

def todos_note():
    plan = todos_prompts()
    if plan:
        return f'\n<todos>\n{plan}\n</todos>'
    else: return ''

def reminder():
    return {
        'role': 'user',
        'content': (
            '<env>\n'
            f'time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'git branch: {git_branch()}\n'
            '</env>' + todos_note() + str(states_file())
        )
    }