---
name: "iniciar-projeto-python"
description: "Criar projeto Python do zero: estrutura, testes e execução"
triggers:
  - "projeto python"
  - "pacote python"
  - "cli em python"
  - "script python"
  - "pyproject"
---
# Iniciar um projeto Python

Sem rede: use apenas a biblioteca padrão. Só use um pacote externo se ele já
estiver instalado.

## Estrutura
```
pyproject.toml
README.md
src/nome_projeto/__init__.py
src/nome_projeto/__main__.py     # ponto de entrada: python -m nome_projeto
src/nome_projeto/<modulos>.py
tests/test_<modulo>.py
```

## pyproject.toml mínimo
```toml
[project]
name = "nome-projeto"
version = "0.1.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

## Passos
1. Se o projeto tiver mais de 3 arquivos, leia antes a skill `planejar-projeto`.
2. Crie os arquivos acima com `write_file` (as pastas são criadas sozinhas).
3. Primeiro marco: um teste simples passando com `python -m pytest -q`.
4. CLI: use `argparse` em `__main__.py` e deixe a lógica em outros módulos,
   para que ela possa ser testada sem a linha de comando.
5. Dados: `json` para arquivos simples, `sqlite3` para dados com consultas.
6. Escreva no README como rodar e como testar.
