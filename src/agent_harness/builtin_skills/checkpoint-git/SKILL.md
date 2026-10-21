---
name: "checkpoint-git"
description: "Salvar progresso com git após cada etapa verificada"
triggers:
  - "commit"
  - "git "
---
# Checkpoints com git

Commits pequenos permitem voltar atrás quando algo quebra.

## Quando fazer
Depois de cada etapa do PLANO.md concluída e verificada (testes passando).

## Passos
1. `git status`. Se não for um repositório, pergunte ao usuário antes de `git init`.
2. `git diff`: revise o que mudou. Procure prints de depuração e arquivos que
   não deveriam entrar.
3. `git add` com os arquivos da etapa (evite `git add -A` se houver arquivos estranhos).
4. `git commit -m "Etapa 3: salvar tarefas em JSON"`, com uma mensagem que diga o que mudou.

`git add` e `git commit` pedem aprovação do usuário; isso é normal.

## Nunca
- `git push`, `git reset` e `git clean` são bloqueados. Não tente contornar.
- Não faça commit com testes falhando sem dizer isso na mensagem.
