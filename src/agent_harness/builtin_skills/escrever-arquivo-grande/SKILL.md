---
name: "escrever-arquivo-grande"
description: "Criar arquivo com mais de ~80 linhas sem cortar o código"
---
# Escrever um arquivo grande

Respostas muito longas podem ser cortadas no meio. Construa o arquivo em partes.

## Passos
1. Crie um esqueleto com `write_file`: imports, classes e funções com
   assinatura, docstring de uma linha e corpo `raise NotImplementedError`.

```python
"""Gerenciador de tarefas."""
import json
from pathlib import Path


def carregar(caminho: Path) -> list[dict]:
    """Lê as tarefas do arquivo JSON."""
    raise NotImplementedError


def salvar(caminho: Path, tarefas: list[dict]) -> None:
    """Grava as tarefas no arquivo JSON."""
    raise NotImplementedError
```

2. Implemente UMA função por vez com `str_replace`. Inclua no `old_str` a
   linha `def` e a docstring, para o trecho ser único, e troque o
   `raise NotImplementedError` daquela função pelo corpo real.
3. Depois de cada 1-2 funções, rode um teste ou `python -m pytest -q`.
4. Ao final, procure sobras: `grep` pattern=`NotImplementedError`.

## Se o arquivo passar de ~300 linhas
Divida em módulos menores (por exemplo `modelos.py`, `armazenamento.py`,
`cli.py`). Arquivos menores são mais fáceis de ler e editar com contexto curto.
