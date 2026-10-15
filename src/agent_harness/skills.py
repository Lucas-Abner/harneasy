from pathlib import Path
import yaml

SKILL_DIR = [
    Path.cwd() / '.agents' / 'skills',
    Path.home() / '.agents' / 'skills',
]

def find_skills():
    skills = {}

    for dir in SKILL_DIR:
        for path in sorted(dir.glob("*/SKILL.md")):
            _, frontmatter, _ = path.read_text().split('---', 2)
            meta = yaml.safe_load(frontmatter)
            description = " ".join(meta.get('description', '').split())
            skills[meta['name']] = {
                'description': description,
                'path': path,
            }

    return skills

SKILLS = find_skills()

def skills_prompt():
    return '\n'.join(f'- {name}: {info['description']}' for name, info in SKILLS.items())

def read_skill(name):
    if name not in SKILLS:
        return f"Sem skills com o nome '{name}'"
    return SKILLS[name]['path'].read_text()

if __name__ == '__main__':
    print(read_skill('code'))

    print(SKILLS)
