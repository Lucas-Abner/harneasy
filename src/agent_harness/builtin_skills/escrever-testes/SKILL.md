---
name: "escrever-testes"
description: "Criar ou ampliar testes automatizados (pytest/unittest)"
triggers:
  - "escreva testes"
  - "escrever testes"
  - "crie testes"
  - "criar testes"
  - "adicione testes"
  - "testes para"
  - "cobertura de testes"
---
# Escrever testes

## Passos
1. Descubra o padrão do projeto: `glob` com `test_*.py` ou `*.test.js`, e leia um teste existente.
2. Sem padrão em Python, use pytest com arquivos `tests/test_<modulo>.py`.
3. Cada teste verifica UMA coisa e tem um nome que diz qual:

```python
import pytest

from calculadora import dividir


def test_dividir_numeros_inteiros():
    assert dividir(10, 2) == 5


def test_dividir_por_zero_gera_erro():
    with pytest.raises(ZeroDivisionError):
        dividir(1, 0)
```

4. Cubra: o caso normal, um caso limite (vazio, zero, negativo) e um caso de erro.
5. Rode só o arquivo novo primeiro: `python -m pytest -q tests/test_modulo.py`
6. Depois rode todos: `python -m pytest -q`

## Regras
- Um teste que nunca falhou não prova nada: confira que ele pegaria o bug.
- Não altere um teste só para ele passar, a menos que o teste esteja errado.
- Testes não usam rede nem arquivos fora de uma pasta temporária (`tmp_path` no pytest).
