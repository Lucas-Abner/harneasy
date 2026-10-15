MARKS = {'pending': '[ ]', 'in_progress': '[~]', 'done': '[x]'}

TODOS = []

def write_todos(todos):
    active = [t for t in todos if t['status'] == 'in_progress']

    if len(active) > 1:
        raise ValueError('Only one task can be in progress at a time.')

    TODOS[:] = todos
    return todos_prompts() or 'Todo list cleared.'

def todos_prompts():
    return "\n".join(f'{MARKS[t['status']]} {t['content']}' for t in TODOS)

def active_todo():
    for t in TODOS:
        if t['status'] == 'in_progress':
            return t
    return 'thinking...'