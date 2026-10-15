
import json
from llm import call_llm
from tools import TOOLS

SYSTEM_PROMPT = """Você é um agente de codificação.
Use comandos PowerShell, pois o sistema operacional é Windows.
Para ler arquivos, use Get-Content.
"""

user_input = input("Digite sua solicitação> ")

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": user_input}
]

while True:
    message, usage, _, _ = call_llm(messages)

    messages.append(message.model_dump(exclude_none=True))

    if message.content:
        print(f"Agente: {message.content} \n")

    if not message.tool_calls:
        break

    for tool_call in message.tool_calls:
        args = json.loads(tool_call.function.arguments)
        result = TOOLS[tool_call.function.name](**args)

        print(
            f"Tool: {tool_call.function.name}, "
            f"{args} -> {result}\n"
        )

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        })
