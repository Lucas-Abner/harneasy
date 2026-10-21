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
| `HARNEASY_CONTEXT_WINDOW` | `4200` | Janela usada pela compactação; com Ollama, é reduzida ao contexto realmente alocado |
| `HARNEASY_LLM_MAX_RETRIES` | `3` | Novas tentativas em erro de conexão, 429 ou 5xx |
| `HARNEASY_LLM_TIMEOUT` | `600` | Tempo máximo, em segundos, de cada chamada ao modelo |
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
| `HARNEASY_TEMPERATURE` | `0` | Temperatura do modelo; 0 deixa as respostas repetíveis |
| `HARNEASY_SEED` | `42` | Semente enviada ao modelo; vazio desativa |
| `HARNEASY_VERIFY_COMMAND` | automático | Comando que o harness roda quando o agente diz que terminou após editar; se falhar, o agente continua. Sem valor, usa `python -m pytest -q` em projetos com `tests/` ou `test_*.py`; `off` desliga |
| `HARNEASY_FINAL_REVIEW` | `1` | Antes de aceitar o fim, mostra ao agente o pedido e o diff real uma vez; `0` desliga |
| `HARNEASY_AUTO_SKILLS` | `1` | O harness escolhe a skill pelo texto do pedido e a injeta; `0` desliga |
| `HARNEASY_MAX_VERIFY` | `2` | Máximo de verificações automáticas por solicitação |
| `HARNEASY_DISABLED_TOOLS` | não definido | Ferramentas a esconder do modelo, ex. `task,read_skill` |
| `HARNEASY_EMBED_MODEL` | não definido | Modelo de embedding do servidor para a busca por significado em `search_code` |
| `HARNEASY_CACHE_DIR` | `~/.cache/harneasy` | Onde guardar os embeddings já calculados |
| `HARNEASY_STREAM` | `1` | Mostra a resposta enquanto é gerada; `0` desativa |
| `HARNEASY_MAX_NUDGES` | `2` | Lembretes por solicitação quando o modelo para cedo (resposta vazia ou tarefas abertas) |
| `HARNEASY_DEBUG_LOG` | não definido | Arquivo `.jsonl` onde gravar as respostas cruas do modelo |

A contagem de tokens é uma estimativa quando o servidor local não informa uso. Ajuste `HARNEASY_CONTEXT_WINDOW` para o limite efetivamente configurado no modelo.

## Uso

| Comando | Função |
|---|---|
| `uv run agent-harness` | Modo interativo |
| `uv run agent-harness -p "tarefa"` | Executa uma única solicitação e encerra (código de saída 0 se concluiu). Ações que pediriam aprovação são negadas |
| `uv run agent-harness -p "tarefa" --yes` | Igual, mas aprova essas ações. Comandos bloqueados continuam bloqueados |

No modo interativo: `/help`, `/status`, `/clear`, `/undo` (desfaz a última edição de arquivo do agente) e `/exit`. `Ctrl+C` cancela só a solicitação atual.

Se existir um `AGENTS.md` na raiz do projeto, ele é incluído no prompt como instruções do projeto (até 4000 caracteres).

## Robustez para modelos pequenos

- **Chamadas de ferramenta escritas como texto** (`<tool_call>`, bloco JSON) são convertidas em chamadas reais, apenas para ferramentas existentes.
- **JSON quebrado nos argumentos** é reparado: cercas de código, vírgulas finais, aspas simples, JSON truncado ou codificado duas vezes.
- **Nomes e tipos de argumentos** são corrigidos: `file_path` → `path`, `"10"` → `10`; argumentos desconhecidos são ignorados com aviso.
- **`str_replace` tolerante**: se o texto exato não existir, tenta ignorando espaços finais e depois indentação; se falhar, mostra o trecho mais parecido.
- **Edições seguras**: é preciso ler o arquivo antes de editá-lo; cada edição retorna um diff curto e avisa sobre erros de sintaxe em Python, JSON, YAML e TOML.
- **Busca sem shell**: ferramentas `grep`, `glob` e `list_dir`.
- **Busca por assunto**: `search_code` ranqueia funções, classes e seções por relevância (BM25, com um dicionário curto de termos português → inglês). Com `HARNEASY_EMBED_MODEL`, também ranqueia por significado e combina os dois rankings. `code_map` lista os arquivos com suas classes e funções.
- **Determinismo**: temperatura 0 e semente fixa; o lembrete de cada turno mostra o orçamento (`turno 4 de 30`) e, se houver `PLANO.md`, a próxima etapa.
- **O harness confere o "terminei"**, nesta ordem: (1) arquivos editados com erro de sintaxe ou módulo não instalado, e arquivos citados no pedido que não existem; (2) os testes do projeto; (3) uma revisão do pedido contra o diff real. Se algo falhar, o agente continua.
- **Skills escolhidas pelo harness**: cada skill tem `triggers` no frontmatter (trechos como `renome` ou `crie um projeto`). Se o pedido contém um deles, a skill entra junto com o pedido; o modelo não precisa lembrar de lê-la.
- **Sem releituras inúteis**: ler de novo um arquivo que não mudou devolve um aviso curto em vez do conteúdo.
- **Insistência**: se a resposta vier vazia ou terminar com tarefas abertas, o harness lembra o modelo e deixa que continue.

## Benchmark

`bench/` mede a taxa de sucesso do agente em tarefas pequenas. Cada tarefa roda numa pasta temporária, e a verificação só é criada depois que o agente termina.

```bash
uv run python bench/run.py --model granite4.1:3b --runs 3
uv run python bench/run.py --only criar_arquivo renomear_funcao
```

Os resultados e o log de cada execução ficam em `bench/results/`. Para adicionar uma tarefa, copie um item de `bench/tasks.py`.

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
