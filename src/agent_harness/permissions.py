import os
from pathlib import Path
import fnmatch

PATH = Path.cwd().resolve()

BASH_RULES = {
    "*": "ask",
    # read-only: let them through
    "ls*": "allow",
    "pwd": "allow",
    "cd *": "allow",
    "echo *": "allow",
    "sort*": "allow",
    "uniq*": "allow",
    "cut *": "allow",
    "basename *": "allow",
    "dirname *": "allow",
    "date*": "allow",
    "env": "allow",
    "cat *": "allow",
    "head *": "allow",
    "tail *": "allow",
    "wc *": "allow",
    "file *": "allow",
    "which *": "allow",
    "grep *": "allow",
    "rg *": "allow",
    "find *": "allow",
    "tree*": "allow",
    "git status*": "allow",
    "git diff*": "allow",
    "git log*": "allow",
    "git show*": "allow",
    "git ls-files*": "allow",
    "pytest*": "allow",
    "python -m pytest*": "allow",
    # risky: never, even if the user says yes
    "rm *": "deny",
    "sudo *": "deny",
    "chmod *": "deny",
    "chown *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git push*": "deny",
    "git reset*": "deny",
    "git clean*": "deny",
}

def split_command(command:str):
    parts, current, quote = [], [], None
    index = 0

    while index < len(command):
        char = command[index]
        
        if quote:
            current.append(char)
            quote = None if quote == char else quote
        elif char == "\\":
            current.append(char)
            index += 1
            if index < len(command):
                current.append(command[index])
        elif char in "\"'":
            quote = char
            current.append(char)    
        elif char in "&|;":
            parts.append(''.join(current))
            current = []
            while index + 1 < len(command) and command[index+1] in "&|;":
                index += 1

        else:
            current.append(char)
        index += 1

    parts.append(''.join(current))
    return [p.strip() for p in parts if p.strip()]

def decide(command):
    veridict = []

    for part in split_command(command):
        action = 'ask'
        for pattern, rule in BASH_RULES.items():
            if fnmatch.fnmatch(part, pattern):
                action = rule
                break
        veridict.append((part, action))
    for strictest in ('deny', 'allow'):
        if strictest in veridict:
            return strictest
    return 'allow'

def inside_project(path):
    return PATH in Path(path).resolve().parents

def check(name, args):
    if name == 'bash':
        return decide(args['command']), f'run: {args['command']}' 
    if name in ('write_file', 'str_replace'):
        return "ask", f'{name} outside{PATH}: {args['path']}'

    return 'allow', None