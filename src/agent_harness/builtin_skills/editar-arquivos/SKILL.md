---
name: "editar-arquivos"
description: "Como usar str_replace e write_file sem errar"
---
# Editar arquivos

## str_replace (arquivos existentes)
1. Leia o arquivo antes com `read_file`. Sem leitura, a edição é recusada.
2. Copie `old_str` EXATAMENTE do resultado do read_file, com a mesma indentação.
3. Inclua 2-3 linhas de contexto para o trecho ser único no arquivo.
4. Faça edições pequenas. Para mudar 3 funções, faça 3 chamadas.
5. Leia o resultado: ele mostra o diff e avisos de sintaxe. Se houver aviso, corrija já.

## Se o str_replace falhar
- "texto não encontrado": use o trecho parecido mostrado no erro, ou releia as linhas.
- "aparece N vezes": inclua mais linhas de contexto.
- "mudou desde a última leitura": leia o arquivo de novo.

## write_file
- Use para arquivos NOVOS ou muito pequenos (até ~80 linhas).
- Para arquivos maiores, leia a skill `escrever-arquivo-grande`.
- Pastas são criadas sozinhas: não precisa de `mkdir`.

## Limitações do ambiente
- Não é possível apagar arquivos (`rm` é bloqueado). Peça ao usuário se precisar.
- Não há acesso à rede: `pip install` e `npm install` falham. Use a biblioteca padrão.
