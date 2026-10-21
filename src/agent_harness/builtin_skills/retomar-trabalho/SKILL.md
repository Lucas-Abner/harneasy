---
name: "retomar-trabalho"
description: "Início de sessão, contexto resumido ou 'continue': retomar pelo PLANO.md"
triggers:
  - "continue"
  - "continuar"
  - "retome"
  - "retomar"
  - "onde paramos"
---
# Retomar o trabalho

Use quando a conversa começar no meio de um projeto, quando o histórico tiver
sido resumido ou quando o usuário disser "continue".

## Passos
1. `read_file` em `PLANO.md`. Se não existir, leia a skill `planejar-projeto`.
2. Veja o estado real do código (não confie na memória):
   - `bash`: `git status` e `git log --oneline -5` (se for um repositório git)
   - `bash`: rode os testes do projeto, como `python -m pytest -q`
3. Encontre a primeira etapa `- [ ]` do plano. Essa é a próxima.
4. Se os testes falham numa etapa marcada `[x]`, corrija isso antes de seguir
   (leia a skill `corrigir-bug`).
5. Leia somente os arquivos ligados à próxima etapa. Não releia o projeto inteiro.
6. Continue o ciclo da skill `planejar-projeto`: uma etapa, verificar, marcar `[x]`.
