# Harneasy

Um harness de programação para modelos locais e endpoints compatíveis com a API da OpenAI. A ideia é manter o runtime explícito e pequeno: o modelo escolhe ações, enquanto o harness controla ferramentas, permissões, limites e compactação do histórico.

## Melhorias desta versão

- Executor central para validar argumentos, aplicar permissões e executar ferramentas tanto no agente principal quanto no subagente.
- Política conservadora para comandos de shell, incluindo comandos compostos, wrappers comuns, comandos destrutivos conhecidos e caminhos fora do workspace.
- Saídas de ferramenta limitadas por tamanho, com arquivo temporário consultável por intervalos de linhas.
- Leitura de arquivos por janela de linhas sem carregar o arquivo inteiro na memória.
- Limites de turnos/chamadas, detecção de chamadas repetidas e recuperação de erros de ferramentas.
- Compactação de contexto com fallback determinístico e fronteiras que preservam blocos completos de chamadas e resultados de ferramentas.
- Endpoint local compatível com OpenAI configurado por padrão para Ollama, com nome do modelo e URL substituíveis por `.env`.
- Testes de regressão para permissões, schemas, saída limitada, leitura parcial, compactação e validação de tarefas.

## Requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/)
- Ollama ou outro servidor compatível com a API de Chat Completions

## Instalação

```bash
uv sync --frozen
cp .env.example .env
```

No Windows PowerShell:

```powershell
uv sync --frozen
Copy-Item .env.example .env
```

Se o projeto estiver em uma pasta sincronizada pelo OneDrive e o `uv` falhar
ao criar hard links, o projeto já está configurado para usar cópias de
arquivos (`link-mode = "copy"`). Para corrigir um ambiente que ficou
incompleto, execute:

```powershell
uv sync --frozen --link-mode=copy
```

Edite `.env` com o endereço e nome do modelo que seu servidor realmente oferece. Para Ollama local, a configuração padrão é:

```dotenv
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=ornith-1.5:9b
```

Confirme que o modelo está instalado e que o servidor Ollama está ativo antes de executar:

```bash
uv run agent-harness
```

Como o código usa imports relativos, não execute `src/agent_harness/agent.py`
diretamente. No PowerShell, também é possível iniciar pelo módulo:

```powershell
uv run python -m agent_harness.agent
```

## Configurações úteis

| Variável | Padrão | Função |
|---|---:|---|
| `OPENAI_API_BASE` | `http://localhost:11434/v1` | Endpoint compatível com OpenAI |
| `OPENAI_BASE_URL` | não definido | Alternativa para configurar o endpoint |
| `OPENAI_API_KEY` | `ollama` | Chave enviada ao endpoint |
| `OPENAI_MODEL` | `ornith-1.5:9b` | Nome do modelo servido pelo endpoint |
| `HARNEASY_CONTEXT_WINDOW` | `4200` | Estimativa de janela usada pela compactação |
| `HARNEASY_COMPACT_TOTAL` | `0.85` | Gatilho de compactação relativo à janela |
| `HARNEASY_COMPACT_AT` | `0.55` | Orçamento aproximado para o histórico recente |
| `HARNEASY_MAX_TOOL_OUTPUT_CHARS` | `6000` | Limite de saída de ferramenta enviada ao modelo |
| `HARNEASY_COMMAND_TIMEOUT` | `60` | Tempo máximo, em segundos, por comando |
| `HARNEASY_MAX_TURNS_PER_REQUEST` | `30` | Máximo de turnos do modelo por solicitação |
| `HARNEASY_MAX_TOOL_CALLS_PER_TURN` | `8` | Máximo de chamadas executadas por turno |
| `HARNEASY_REPEAT_TOOL_LIMIT` | `3` | Repetições idênticas antes de sinalizar estagnação |
| `HARNEASY_SUBAGENT_MAX_TURNS` | `10` | Limite de turnos do subagente |
| `HARNEASY_SUBAGENT_MAX_TOOL_CALLS_PER_TURN` | `5` | Limite de chamadas de ferramenta por turno do subagente |
| `HARNEASY_REQUIRE_SANDBOX` | `0` | Bloqueia comandos quando o isolamento de SO não está disponível |

A contagem de tokens é uma estimativa quando o servidor local não informa uso. Ajuste `HARNEASY_CONTEXT_WINDOW` para o limite efetivamente configurado no modelo.

## Segurança: comportamento e limitações

- Todas as chamadas de ferramenta passam por `execute_tool`, inclusive as chamadas do subagente.
- Comandos desconhecidos pedem aprovação. Uma lista curta de comandos de leitura pode executar sem aprovação.
- Comandos destrutivos/rede explicitamente conhecidos, como `rm`, `curl`, `wget`, `git push`, `git reset` e `git clean`, são bloqueados pela política.
- Edição por ferramentas de arquivo fica restrita ao workspace resolvido. Leituras fora dele pedem aprovação.
- Saídas extensas são reduzidas para proteger o contexto. A saída completa é guardada em arquivo temporário e o caminho é mostrado ao modelo.
- O isolamento do sistema operacional é *best effort*: Linux usa `bubblewrap` quando instalado; macOS usa `sandbox-exec` quando disponível. O modo estrito `HARNEASY_REQUIRE_SANDBOX=1` bloqueia a execução se o isolamento não estiver disponível. O executor PowerShell do Windows ainda não tem sandbox de sistema operacional e, nesse modo, bloqueia comandos.

**Importante:** a política de comandos é uma camada defensiva, não uma sandbox formal nem uma garantia contra comandos arbitrários ou código malicioso. Use o harness em um workspace descartável/ versionado, revise ações que pedem aprovação e não exponha credenciais no ambiente de execução.

## Testes

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

A suíte cobre permissões e comandos compostos, caminhos externos, schemas das ferramentas, limite de saída, leitura por intervalos, limites de compactação entre chamadas de ferramentas e validação da lista de tarefas. Testes integrados com o modelo exigem as dependências instaladas e um servidor de modelo acessível.
