---
name: "implementar-funcionalidade"
description: "Adicionar ou alterar comportamento em código existente"
triggers:
  - "adicione"
  - "adicionar"
  - "implemente"
  - "implementar"
  - "nova funcionalidade"
  - "suporte a"
---
# Implementar uma funcionalidade

## Passos
1. Escreva para si, em uma frase, o que deve funcionar quando terminar.
2. Ache o lugar certo (`grep`, `glob`) e leia o código ao redor com `read_file`.
3. Siga o estilo do arquivo: nomes, imports, formato de erros e comentários.
4. Faça a menor mudança que funcione:
   - Funções pequenas, com uma responsabilidade cada.
   - Reaproveite funções existentes antes de criar novas.
5. Edite com `str_replace` (leia a skill `editar-arquivos` se uma edição falhar).
6. Verifique logo depois de cada edição:
   - Rode os testes existentes: `python -m pytest -q`
   - Se não houver teste para o novo comportamento, crie um (skill `escrever-testes`).
7. Se algo quebrar, corrija antes de continuar. Não acumule erros.

## Para mudanças em vários arquivos
- Comece pela camada de dados ou pela função central, depois quem a usa.
- Teste após cada arquivo, não só no fim.
