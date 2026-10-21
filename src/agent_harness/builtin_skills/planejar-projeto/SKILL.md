---
name: "planejar-projeto"
description: "Projeto grande ou com vários arquivos: criar PLANO.md e dividir em etapas pequenas"
triggers:
  - "crie um projeto"
  - "criar um projeto"
  - "novo projeto"
  - "crie um sistema"
  - "crie uma aplicacao"
  - "crie um app"
  - "do zero"
---
# Planejar um projeto grande

Seu contexto é curto e será resumido. O PLANO.md é a sua memória: tudo que
importa precisa estar nele, não só na conversa.

## Passos
1. Entenda o pedido. Se o projeto já existe, leia antes a skill `explorar-codigo`.
2. Crie `PLANO.md` na raiz com `write_file`, neste formato:

```markdown
# Plano: <nome do projeto>

## Objetivo
<2-3 frases com o que o usuário pediu>

## Decisões
- Linguagem/estrutura: ...
- Como rodar os testes: `python -m pytest -q`

## Etapas
- [ ] 1. Estrutura inicial e um teste que passa
- [ ] 2. <funcionalidade pequena e testável>
- [ ] 3. ...

## Notas
- <descobertas, problemas e caminhos importantes>
```

3. Regras para as etapas:
   - Cada etapa cabe em 1-3 arquivos e termina com algo verificável (teste ou comando).
   - Ordem: primeiro o núcleo que funciona de ponta a ponta, depois os extras.
   - Entre 5 e 15 etapas. Se uma etapa parecer grande, divida-a.
4. Execute UMA etapa por vez:
   - Use `update_todos` só com os passos da etapa atual.
   - Implemente, rode o teste e só então marque a etapa com `[x]` usando `str_replace`.
   - Registre em "Notas" qualquer decisão ou descoberta que você precisará depois.
5. Ao terminar todas as etapas, leia a skill `revisar-antes-de-concluir`.

## Nunca
- Nunca escreva o projeto inteiro de uma vez.
- Nunca marque uma etapa como feita sem ter rodado a verificação dela.
