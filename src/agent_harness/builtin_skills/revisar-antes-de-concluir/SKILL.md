---
name: "revisar-antes-de-concluir"
description: "Checklist final antes de dizer que a tarefa terminou"
triggers:
  - "revise"
  - "revisar"
  - "revisao"
---
# Revisar antes de concluir

## Checklist
1. Releia o pedido original. Cada parte foi feita? Liste o que ficou faltando.
2. Rode TODOS os testes: `python -m pytest -q` (ou o comando do projeto).
3. Rode o programa como o usuário rodaria (o comando do README), se possível.
4. `git diff` (ou releia os arquivos alterados) e procure:
   - prints ou código de depuração esquecidos
   - `NotImplementedError`, `TODO` ou funções vazias
   - imports sem uso
5. Se existir PLANO.md, todas as etapas devem estar `[x]`, ou explique por quê.

## Resposta final ao usuário
- O que foi feito (arquivos principais).
- Como foi verificado (comando e resultado).
- O que não foi feito ou não pôde ser verificado, com o motivo.
Seja honesto: se algo falhou, diga.
