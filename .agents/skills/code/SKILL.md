---
name: "code"
description: "Padrão de qualidade ao escrever código: simples, legível e com erros tratados"
---
# Escrever código de qualidade

Escreva código que um programador júnior entenda na primeira leitura.
Simples e correto vale mais que esperto e genérico.

## Antes de escrever
1. Leia o código vizinho e siga o estilo dele: nomes, idioma dos comentários,
   formato de imports e de erros. Consistência vale mais que preferência.
2. Procure algo pronto antes de criar: `grep` pelo nome da função ou da ideia.

## Nomes
- Nomes que dizem o que a coisa é: `tarefas_pendentes`, não `lista2` nem `tp`.
- Funções começam com um verbo: `carregar_config`, `calcular_total`.
- Booleanos parecem perguntas: `esta_vazio`, `tem_permissao`.
- Constantes em MAIÚSCULAS no topo do arquivo: `MAX_TENTATIVAS = 3`.

## Funções
- Uma função faz uma coisa. Se precisar de "e" para descrevê-la, divida.
- Até ~30 linhas. Mais que isso, extraia partes com nomes claros.
- Retorne cedo para evitar `if` aninhado:

```python
def desconto(cliente):
    if cliente is None:
        return 0
    if not cliente.ativo:
        return 0
    return 10 if cliente.vip else 5
```

- Em Python, use type hints nos parâmetros e no retorno: `def total(itens: list[float]) -> float:`

## Erros
- Valide as entradas na borda (CLI, API, leitura de arquivo), não em toda função.
- Gere erros com mensagem útil: `raise ValueError(f"id {id} não existe")`.
- Capture só a exceção esperada e só quando souber o que fazer com ela:
  `except FileNotFoundError:`, nunca `except:` ou `except Exception: pass`.

## Simplicidade
- Não crie classe, interface ou configuração "para o futuro". Resolva o pedido de hoje.
- Prefira a biblioteca padrão a escrever do zero (`pathlib`, `json`, `collections`, `itertools`).
- Sem números mágicos: dê nome a valores como `TIMEOUT_SEGUNDOS = 30`.
- Não duplique: se o mesmo trecho aparece 3 vezes, vira uma função.

## Comentários
- Comente o PORQUÊ, não o quê: `# A API devolve centavos, então dividimos por 100.`
- Docstring de uma linha em funções públicas.
- Não deixe código comentado nem prints de depuração.

## Antes de entregar
Rode os testes e confira o diff. Para o checklist completo, leia a skill
`revisar-antes-de-concluir`.
