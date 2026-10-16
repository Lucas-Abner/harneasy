from .llm import client
import json
import os

SYSTEM_PROMPT = """
Você está sintetizando a transcrição de uma sessão de programação. A sessão excedeu a janela de contexto. Escreva uma nota de transição que permita a um novo agente retomar o trabalho sem precisar reler nada.

Utilize as seções a seguir, nesta ordem. Omita qualquer seção que ficaria vazia.

## Objetivo
O que o usuário solicitou. Cite o usuário quando a formulação exata for importante.

## O que aconteceu
Decisões tomadas e a justificativa por trás delas. Inclua abordagens que foram testadas e descartadas, explicando o motivo — essas são as lições custosas; sem esse conhecimento, um novo agente poderia acabar seguindo o mesmo caminho sem saída.

## Arquivos
Todos os arquivos alterados: caminho e o que foi modificado em cada um.

## Estado atual
O que está funcionando, o que apresenta falhas e o que ficou inacabado.

## Próximos passos
A próxima etapa imediata.

Regras:
- Seja específico. Use caminhos reais, nomes de funções, mensagens de erro e comandos exatos.
- Mantenha tudo o que o usuário solicitou explicitamente, corrigiu ou rejeitou.
- Nunca invente progresso. Se algo não foi concluído, declare claramente que não foi.
- Não utilize preâmbulos nem despedidas. Comece diretamente pelo primeiro cabeçalho.
"""

HANDOFF = """<summary>
Todo o conteúdo anterior a este ponto foi sintetizado e removido da janela de contexto para liberar espaço. Este é o registro do que foi feito — considere-o como sua própria memória do trabalho realizado até agora, e não como algo que o usuário lhe informou.

{summary}
</summary>"""

CONTEXT_WINDOWS = 4200
COMPACT_TOTAL = 0.85
COMPACT_AT = 0.55

def needed(usage):
    return usage['prompt_tokens'] >= CONTEXT_WINDOWS * COMPACT_TOTAL

ROLES = {"user": "USER", "assistant": "ASSISTANT", "tool": "TOOL RESULT"}


def render(messages):
    lines = []

    for message in messages:
        if message['role'] == 'system':
            continue

        content = message.get('content', '')

        for call in message.get('tool_calls', []):
            function = call['function']
            content += f"\n[called {function['name']}: {function['arguments']}]"

        lines.append(f'{ROLES.get(message['role'], message['role'])}: {content}')

    return '\n\n'.join(lines)

def summarize(messages):
    result = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "ornith-1.5:9b"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render(messages)},
        ],
    )

    return result.choices[0].message.content


def safe_boundary(messages, start):
    boundary = max(start, 1)
    if (
        boundary < len(messages)
        and messages[boundary]["role"] == "tool"
        and boundary > 1
        and messages[boundary - 1].get("tool_calls")
    ):
        boundary -= 1
    return boundary

def estimate(messages):
    # JSON characters are only an approximation, so use a conservative ratio.
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 3

def tail_start(messages, budget):
    total = 0
    for index in range(len(messages) - 1, 0, -1):
        message_size = estimate([messages[index]])
        if total + message_size > budget:
            return safe_boundary(messages, index)
        total += message_size
    return safe_boundary(messages, 1)

def compact(messages):
    cut = tail_start(messages, CONTEXT_WINDOWS * COMPACT_AT)
    if cut <= 1:
        return messages

    summary = summarize(messages[1:cut])
    kept = [
        messages[0],
        {'role':'user', 'content': HANDOFF.format(summary=summary)},
        *messages[cut:],
    ]
    return kept