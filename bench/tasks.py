"""Benchmark tasks. Each task is a tiny project, a request and a check.

- files:  the project the agent starts with
- prompt: what we ask the agent
- check:  Python code run AFTER the agent finishes; it must exit with an
          error (e.g. a failing assert) when the task was not solved.
          The agent never sees it.

To add a task, copy one of the dicts below.
"""

TASKS = [
    {
        "name": "corrigir_bug",
        "files": {
            "calc.py": "def soma(a, b):\n    return a - b\n\n\ndef dobro(x):\n    return x * 3\n",
        },
        "prompt": "Em calc.py, soma deveria somar e dobro deveria multiplicar por 2. Corrija os dois bugs.",
        "check": "import calc\nassert calc.soma(2, 3) == 5\nassert calc.dobro(4) == 8\n",
    },
    {
        "name": "editar_metodo_indentado",
        "files": {
            "cart.py": (
                "class Cart:\n"
                "    def __init__(self, discount=0):\n"
                "        self.items = []\n"
                "        self.discount = discount\n"
                "\n"
                "    def add(self, price):\n"
                "        self.items.append(price)\n"
                "\n"
                "    def total(self):\n"
                "        subtotal = sum(self.items)\n"
                "        return subtotal\n"
            ),
        },
        "prompt": (
            "Em cart.py, o método total ignora o desconto. self.discount é um percentual de 0 a 100. "
            "Faça total aplicar o desconto sobre o subtotal."
        ),
        "check": (
            "from cart import Cart\n"
            "c = Cart(discount=10)\nc.add(100)\nc.add(50)\n"
            "assert abs(c.total() - 135) < 1e-9, c.total()\n"
            "assert Cart().total() == 0\n"
        ),
    },
    {
        "name": "encontrar_em_varios_arquivos",
        "files": {
            "app/__init__.py": "",
            "app/main.py": "from app.settings import TIMEOUT\n\n\ndef run():\n    return TIMEOUT\n",
            "app/db.py": "def connect(url):\n    return url\n",
            "app/settings.py": "DEBUG = False\nTIMEOUT = 3\nRETRIES = 2\n",
            "README.md": "# App\n\nO timeout padrão é de 30 segundos.\n",
        },
        "prompt": (
            "O timeout padrão do pacote app deveria ser 30 segundos, como diz o README, "
            "mas está errado em algum arquivo. Encontre e corrija."
        ),
        "check": "from app.main import run\nassert run() == 30, run()\nfrom app.settings import RETRIES\nassert RETRIES == 2\n",
    },
    {
        "name": "criar_arquivo",
        "files": {"README.md": "# Utilidades de texto\n"},
        "prompt": (
            "Crie o arquivo slugify.py com a função slugify(texto) que converte para minúsculas, "
            "remove acentos e troca espaços e qualquer caractere não alfanumérico por um único hífen, "
            "sem hífens nas pontas. Exemplo: slugify('  Olá, Mundo! ') == 'ola-mundo'."
        ),
        "check": (
            "from slugify import slugify\n"
            "assert slugify('  Olá, Mundo! ') == 'ola-mundo', slugify('  Olá, Mundo! ')\n"
            "assert slugify('Ação   Rápida') == 'acao-rapida'\n"
            "assert slugify('a--b') == 'a-b'\n"
        ),
    },
    {
        "name": "fazer_testes_passarem",
        "files": {
            "stack.py": (
                "class Stack:\n"
                "    def __init__(self):\n"
                "        self._items = []\n"
                "\n"
                "    def push(self, item):\n"
                "        self._items.insert(0, item)\n"
                "\n"
                "    def pop(self):\n"
                "        return self._items.pop()\n"
                "\n"
                "    def peek(self):\n"
                "        return self._items[0]\n"
                "\n"
                "    def is_empty(self):\n"
                "        return len(self._items) == 0\n"
            ),
            "test_stack.py": (
                "from stack import Stack\n\n\n"
                "def test_lifo():\n"
                "    s = Stack()\n    s.push(1)\n    s.push(2)\n"
                "    assert s.pop() == 2\n    assert s.pop() == 1\n\n\n"
                "def test_peek():\n"
                "    s = Stack()\n    s.push('a')\n    s.push('b')\n"
                "    assert s.peek() == 'b'\n    assert not s.is_empty()\n"
            ),
        },
        "prompt": "Os testes em test_stack.py estão falhando. Rode-os com pytest e corrija stack.py até passarem.",
        "check": (
            "from stack import Stack\n"
            "s = Stack()\nfor i in range(3):\n    s.push(i)\n"
            "assert s.peek() == 2\nassert [s.pop(), s.pop(), s.pop()] == [2, 1, 0]\nassert s.is_empty()\n"
        ),
    },
    {
        "name": "editar_json",
        "files": {
            "config.json": '{\n  "name": "servico",\n  "debug": true,\n  "workers": 4\n}\n',
        },
        "prompt": "Em config.json, desligue o debug e adicione a chave port com o valor 8080. Mantenha o resto.",
        "check": (
            "import json\n"
            "c = json.load(open('config.json'))\n"
            "assert c == {'name': 'servico', 'debug': False, 'workers': 4, 'port': 8080}, c\n"
        ),
    },
    {
        "name": "renomear_funcao",
        "files": {
            "users.py": "def get_user(user_id):\n    return {'id': user_id}\n",
            "api.py": "from users import get_user\n\n\ndef handler(user_id):\n    return get_user(user_id)\n",
            "jobs.py": "import users\n\n\ndef nightly():\n    return [users.get_user(i) for i in range(2)]\n",
        },
        "prompt": "Renomeie a função get_user para fetch_user em todo o projeto, incluindo todos os usos.",
        "check": (
            "import pathlib\n"
            "for f in ['users.py', 'api.py', 'jobs.py']:\n"
            "    assert 'get_user' not in pathlib.Path(f).read_text(), f\n"
            "import api, jobs\n"
            "assert api.handler(7) == {'id': 7}\nassert len(jobs.nightly()) == 2\n"
        ),
    },
    {
        "name": "projeto_extenso",
        "files": {"README.md": "# Tarefas\n"},
        "prompt": (
            "Crie um projeto Python de gerenciador de tarefas em linha de comando, no pacote src/tarefas. "
            "1) armazenamento.py: carregar(caminho) e salvar(caminho, tarefas) em JSON; "
            "se o arquivo não existir, carregar retorna lista vazia. "
            "2) nucleo.py: adicionar(tarefas, titulo) acrescenta e retorna "
            "{'id': <inteiro sequencial começando em 1>, 'titulo': titulo, 'feita': False}; "
            "concluir(tarefas, id) marca feita=True e gera ValueError se o id não existir; "
            "pendentes(tarefas) retorna só as não feitas. "
            "3) __main__.py: comandos add <titulo>, done <id> e list, usando tarefas.json no diretório atual; "
            "list mostra uma linha por tarefa com o id e o título. "
            "4) Testes em tests/ que passem com python -m pytest."
        ),
        "check": (
            "import json, os, subprocess, sys, tempfile, pathlib\n"
            "sys.path.insert(0, 'src')\n"
            "from tarefas.armazenamento import carregar, salvar\n"
            "from tarefas.nucleo import adicionar, concluir, pendentes\n"
            "t = []\n"
            "a = adicionar(t, 'comprar pão'); b = adicionar(t, 'estudar')\n"
            "assert a == {'id': 1, 'titulo': 'comprar pão', 'feita': False}, a\n"
            "assert b['id'] == 2 and len(t) == 2\n"
            "concluir(t, 1)\n"
            "assert [x['id'] for x in pendentes(t)] == [2]\n"
            "try:\n    concluir(t, 99)\n    raise SystemExit('concluir sem ValueError')\nexcept ValueError:\n    pass\n"
            "d = pathlib.Path(tempfile.mkdtemp())\n"
            "assert carregar(d / 'nao_existe.json') == []\n"
            "salvar(d / 'x.json', t)\nassert carregar(d / 'x.json') == t\n"
            "env = {**os.environ, 'PYTHONPATH': str(pathlib.Path('src').resolve())}\n"
            "run = lambda *a: subprocess.run([sys.executable, '-m', 'tarefas', *a], cwd=d, env=env, capture_output=True, text=True, timeout=30)\n"
            "assert run('add', 'lavar louça').returncode == 0\n"
            "assert run('add', 'pagar conta').returncode == 0\n"
            "assert run('done', '1').returncode == 0\n"
            "out = run('list').stdout\n"
            "assert 'lavar louça' in out and 'pagar conta' in out, out\n"
            "assert json.loads((d / 'tarefas.json').read_text())[0]['feita'] is True\n"
            "assert list(pathlib.Path('tests').glob('test_*.py')), 'sem testes'\n"
            "r = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests'], env=env, capture_output=True, text=True, timeout=120)\n"
            "assert r.returncode == 0, r.stdout[-500:]\n"
        ),
    },
]
