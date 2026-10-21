---
name: "refatorar"
description: "Renomear, mover ou reorganizar código sem mudar o comportamento"
triggers:
  - "renome"
  - "refator"
  - "reorganiz"
  - "mova "
  - "mover "
  - "extraia"
  - "extrair"
---
# Refatorar

Refatorar = mudar a forma sem mudar o comportamento. Os testes provam isso.

## Passos
1. Rode os testes ANTES e anote o resultado. Se nenhum teste cobre o código,
   escreva alguns antes (skill `escrever-testes`).
2. Encontre TODOS os usos: `grep` pattern=`\bnome_antigo\b`.
3. Mude um arquivo por vez com `str_replace`: a definição primeiro, depois os usos.
4. Confirme que não sobrou nada: `grep` com o nome antigo deve dar
   "Nenhuma ocorrência".
5. Rode os testes de novo. O resultado deve ser igual ao do passo 1.

## Para mover código entre arquivos
1. Crie a função no arquivo novo.
2. Troque os imports de quem a usa.
3. Só então remova a versão antiga.
4. Teste após cada passo.

## Não misture
Não corrija bugs nem adicione funcionalidades durante uma refatoração.
Faça uma coisa de cada vez.
