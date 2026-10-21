---
name: "explorar-codigo"
description: "Entender um repositório desconhecido antes de alterar algo"
triggers:
  - "como funciona"
  - "onde fica"
  - "onde esta"
  - "explique o codigo"
  - "entender o projeto"
  - "o que esse projeto"
  - "o que este projeto"
---
# Explorar um repositório

Objetivo: descobrir onde mexer lendo o mínimo possível.

## Passos
1. `list_dir` na raiz. Procure README, pyproject.toml, package.json, Makefile.
2. Leia o README e o arquivo de configuração do projeto: eles dizem como rodar e testar.
3. Veja a estrutura com `code_map` (arquivos com suas classes e funções).
   Em projetos grandes, passe uma pasta: `code_map` path=`src/app`.
4. Para achar onde algo acontece:
   - Por assunto: `search_code` query=`salvar pedido no banco`
   - Por texto exato (nome, mensagem de erro): `grep` pattern=`def nome_da_funcao` include=`*.py`
5. Leia só os trechos relevantes com `read_file`, usando o `start_line` que
   `search_code` ou `code_map` mostraram.
6. Para perguntas amplas ("como funciona a autenticação?"), delegue à ferramenta
   `task` com uma pergunta completa. Ela explora sem gastar o seu contexto.
7. Em projetos grandes, anote em `PLANO.md` (seção Notas) um mapa curto:
   `arquivo -> responsabilidade`.

## Dicas
- Prefira `search_code`, `code_map` e `grep` a abrir arquivos ao acaso.
- Leia os testes: eles mostram como o código deve ser usado.
