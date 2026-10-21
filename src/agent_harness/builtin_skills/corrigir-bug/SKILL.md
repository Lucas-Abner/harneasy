---
name: "corrigir-bug"
description: "Erro, exceção, teste falhando ou comportamento errado"
triggers:
  - "bug"
  - "erro"
  - "falhando"
  - "falha"
  - "quebrado"
  - "nao funciona"
  - "corrij"
  - "corrigir"
  - "conserte"
  - "traceback"
  - "exception"
---
# Corrigir um bug

## Passos
1. **Reproduza.** Rode o comando ou teste que mostra o erro. Sem reproduzir,
   você não saberá se corrigiu.
2. **Leia o erro de baixo para cima.** Num traceback Python, a última linha diz
   o tipo do erro; as linhas acima mostram o caminho. Procure a linha mais
   baixa que pertence a um arquivo DO PROJETO (não da biblioteca).
3. **Leia o código** nessa linha com `read_file` (start_line uns 10 antes).
4. **Formule uma hipótese** em uma frase: "x é None porque...".
5. **Confirme a hipótese** se não for óbvia: leia quem chama a função, ou rode
   um teste menor.
6. **Corrija a causa**, não o sintoma. Evite `try/except` que só esconde o erro.
7. **Rode de novo** o mesmo comando do passo 1. Depois rode todos os testes.
8. Se fizer sentido, adicione um teste que falharia sem a correção.

## Se após 3 tentativas não resolver
- Pare de repetir a mesma ideia. Releia o erro completo.
- Liste o que você já sabe e o que já descartou.
- Explique o bloqueio ao usuário com o erro exato.

## Erros comuns em Python
- `ModuleNotFoundError`: rode a partir da raiz do projeto; verifique imports e `__init__.py`.
- `AttributeError: 'NoneType'`: alguma função retornou None; procure um `return` faltando.
- `IndentationError`: misturou espaços; leia as linhas indicadas e reescreva o bloco.
