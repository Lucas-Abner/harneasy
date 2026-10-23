# Harneasy

Um agente de programação para **modelos locais pequenos** (3B a 9B parâmetros) rodando no Ollama ou em qualquer servidor compatível com a API da OpenAI.

A ideia é ser "20% do Claude Code, otimizado para modelos pequenos": o modelo só escolhe a próxima ação, e o harness faz o resto. Ele executa as ferramentas, aplica as permissões, corrige chamadas malformadas, confere se o trabalho terminou de verdade e mantém o histórico dentro de um contexto curto.

## Requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/)
- Ollama ou outro servidor compatível com a API de Chat Completions
- Opcional, no Linux: [bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) para isolar os comandos de shell

## Instalação

```bash
uv sync --frozen
cp .env.example .env
```

No Windows PowerShell, troque o `cp` por `Copy-Item .env.example .env`.

Edite o `.env` com o endereço e o nome do modelo que o seu servidor oferece. Para o Ollama local:

```dotenv
OPENAI_API_BASE=http://localhost:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=granite4.1:3b
HARNEASY_CONTEXT_WINDOW=10000
```

Confirme que o modelo está baixado (`ollama list`) e que o Ollama está rodando. Depois:

```bash
uv run agent-harness
```

Não execute `src/agent_harness/agent.py` diretamente, porque o código usa imports relativos. Se precisar chamar pelo módulo, use `uv run python -m agent_harness.agent`.

> **OneDrive:** se o `uv` falhar ao criar hard links, o projeto já usa cópias (`link-mode = "copy"`). Para consertar um ambiente incompleto, rode `uv sync --frozen --link-mode=copy`.

## Uso

| Comando | O que faz |
|---|---|
| `uv run agent-harness` | Modo interativo |
| `uv run agent-harness -p "tarefa"` | Executa um pedido e encerra (código de saída 0 se concluiu). Ações que pediriam aprovação são negadas |
| `uv run agent-harness -p "tarefa" --yes` | Igual, mas aprova essas ações. Comandos bloqueados continuam bloqueados |

No modo interativo existem os comandos:
- `/help`
- `/status`
- `/clear`
- `/undo`, que desfaz a última edição de arquivo feita pelo agente
- `/exit`

`Ctrl+C` cancela só o pedido atual.

### Usar em outro projeto

O agente trabalha na **pasta de onde ele é chamado**. Para usá-lo em outro projeto, entre na pasta dele e aponte o `uv` para o Harneasy:

```bash
cd ~/meu-projeto
uv run --project ~/caminho/para/harneasy agent-harness
```

O `.env` é lido da pasta onde você está, não da pasta do Harneasy. Copie o `.env` para o projeto, ou exporte as variáveis no terminal. Sem isso, o modelo e o endereço voltam aos valores padrão.

`HARNEASY_PROJECT_ROOT` troca a pasta de trabalho sem precisar fazer `cd`.

### Instruções do projeto

- **`AGENTS.md`** na raiz do projeto entra no prompt como instruções do projeto (até 4000 caracteres). Use para dizer onde fica cada coisa e o que o agente não deve ler. Para um modelo pequeno, isso evita muita exploração.
- **`PLANO.md`** guarda as etapas de um projeto grande. Ele sobrevive à compactação do histórico, e o lembrete de cada turno mostra a próxima etapa dele.

## Como o harness ajuda o modelo pequeno

### Chamadas de ferramenta
- Chamadas escritas como texto (`<tool_call>`, bloco JSON) viram chamadas reais, mas só para ferramentas que existem.
- JSON quebrado nos argumentos é reparado: cercas de código, vírgulas finais, aspas simples, JSON truncado ou codificado duas vezes.
- Nomes e tipos de argumentos são corrigidos (`file_path` → `path`, `"10"` → `10`). Argumentos desconhecidos são ignorados com um aviso.
- Caminhos como `/app/x.py`, que não existem fora do projeto, são lidos como relativos ao projeto.

### Edição de arquivos
- É preciso ler o arquivo antes de editá-lo. Se o modelo esquecer, a edição não é aplicada e o conteúdo atual volta junto com o erro.
- O `write_file` só reescreve arquivos de até 30 linhas. Arquivos maiores precisam de `str_replace`, para o modelo não reescrever tudo e perder partes.
- O `str_replace` é tolerante: se o texto exato não existir, tenta de novo ignorando os espaços no fim da linha e depois a indentação. Se ainda falhar, mostra o trecho mais parecido.
- Cada edição devolve um diff curto e avisa sobre:
  - erros de sintaxe em Python, JSON, YAML e TOML;
  - módulos da biblioteca padrão usados sem `import`;
  - módulos que não estão instalados;
  - edições que só mudaram comentários ou espaços.

### Busca
- `grep`, `glob` e `list_dir` buscam sem passar pelo shell.
- `search_code` ranqueia funções, classes e seções por assunto (BM25, com um dicionário curto de termos de português para inglês). Com `HARNEASY_EMBED_MODEL`, também ranqueia por significado.
- `code_map` lista os arquivos do projeto com suas classes e funções.
- Ler de novo um trecho que não mudou devolve um aviso curto em vez do conteúdo.

### Contexto e determinismo
- Temperatura 0 e semente fixa, para as respostas serem repetíveis.
- O lembrete de cada turno mostra:
  - o orçamento (`turno 4 de 30`);
  - se a rede está ligada;
  - a lista de arquivos do projeto, quando ela é curta;
  - a próxima etapa do `PLANO.md`.
- O histórico é compactado antes de estourar o contexto, sem separar uma chamada de ferramenta do seu resultado.
- Com Ollama, o harness detecta o contexto que o servidor alocou de verdade e se ajusta a ele.

### Skills
O harness escolhe a skill pelo texto do pedido e a coloca junto com ele, para o modelo não precisar lembrar de ler. Cada skill tem `triggers` no frontmatter (trechos como `renome` ou `crie um projeto`).

Skills incluídas:
- `corrigir-bug`
- `refatorar`
- `implementar-funcionalidade`
- `escrever-testes`
- `explorar-codigo`
- `planejar-projeto`
- `iniciar-projeto-python`
- `iniciar-projeto-web`
- `retomar-trabalho`
- `checkpoint-git`
- `editar-arquivos`
- `escrever-arquivo-grande`
- `revisar-antes-de-concluir`

Para criar as suas, coloque uma pasta com um `SKILL.md` em `~/.agents/skills/` ou em `.agents/skills/` dentro do projeto. A skill do projeto tem prioridade sobre a do usuário, e a do usuário sobre a embutida.

### O harness confere o "terminei"
Quando o modelo diz que acabou, o harness confere, nesta ordem:

1. Arquivos editados com erro de sintaxe ou módulo não instalado, e arquivos citados no pedido que não existem.
2. Testes rodados pelo modelo que falharam e não foram rodados de novo.
3. A última busca (`grep`) do modelo, rodada de novo: se ela ainda encontra resultados depois das edições (por exemplo, um nome que devia ter sido renomeado), o modelo é avisado.
4. Os testes do projeto (`HARNEASY_VERIFY_COMMAND`).
5. Uma revisão final, com o pedido, o diff real e o conteúdo atual dos arquivos editados.

Se algo falhar, o modelo continua trabalhando. Cada conferência tem um limite de insistências, para não virar um loop.

### Quando o modelo se perde
- A mesma chamada repetida várias vezes recebe um aviso de estagnação.
- Muitas ações seguidas sem editar nada geram um aviso com a lista dos arquivos já lidos (`HARNEASY_IDLE_LIMIT`). Ler um arquivo novo não conta. Se continuar sem progresso, o pedido é parado com o status `stuck`.
- Resposta vazia ou com tarefas abertas recebe um lembrete para continuar.

## Configuração

Todas as variáveis podem ir no `.env`.

| Variável | Padrão | Função |
|---|---:|---|
| `OPENAI_API_BASE` | `http://localhost:11434/v1` | Endpoint compatível com OpenAI (`OPENAI_BASE_URL` também funciona) |
| `OPENAI_API_KEY` | `ollama` | Chave enviada ao endpoint |
| `OPENAI_MODEL` | `ornith-1.5:9b` | Nome do modelo servido pelo endpoint |
| `HARNEASY_PROJECT_ROOT` | pasta atual | Pasta do projeto onde o agente trabalha |
| `HARNEASY_CONTEXT_WINDOW` | detectado | Tamanho do contexto em tokens. Com Ollama, é ajustado ao contexto alocado de verdade |
| `HARNEASY_COMPACT_TOTAL` | `0.85` | Fração do contexto que dispara a compactação |
| `HARNEASY_COMPACT_AT` | `0.55` | Fração do contexto reservada ao histórico recente |
| `HARNEASY_MAX_TOOL_OUTPUT_CHARS` | `6000` | Tamanho máximo da saída de ferramenta mostrada ao modelo |
| `HARNEASY_LLM_MAX_RETRIES` | `3` | Novas tentativas em erro de conexão, 429 ou 5xx |
| `HARNEASY_LLM_TIMEOUT` | `600` | Tempo máximo, em segundos, de cada chamada ao modelo |
| `HARNEASY_COMMAND_TIMEOUT` | `60` | Tempo máximo, em segundos, de cada comando (instalações têm 300) |
| `HARNEASY_MAX_TURNS_PER_REQUEST` | `30` | Máximo de turnos do modelo por pedido |
| `HARNEASY_MAX_TOOL_CALLS_PER_TURN` | `8` | Máximo de chamadas executadas por turno |
| `HARNEASY_REPEAT_TOOL_LIMIT` | `3` | Repetições idênticas antes do aviso de estagnação |
| `HARNEASY_IDLE_LIMIT` | `6` | Ações sem progresso antes do aviso; o dobro disso para o pedido |
| `HARNEASY_MAX_NUDGES` | `2` | Insistências por pedido quando o modelo para cedo |
| `HARNEASY_SUBAGENT_MAX_TURNS` | `10` | Limite de turnos do subagente (ferramenta `task`) |
| `HARNEASY_SUBAGENT_MAX_TOOL_CALLS_PER_TURN` | `5` | Limite de chamadas por turno do subagente |
| `HARNEASY_TEMPERATURE` | `0` | Temperatura do modelo |
| `HARNEASY_SEED` | `42` | Semente enviada ao modelo; vazio desativa |
| `HARNEASY_STREAM` | `1` | Mostra a resposta enquanto é gerada; `0` desativa |
| `HARNEASY_VERIFY_COMMAND` | automático | Comando rodado quando o agente diz que terminou. Sem valor, usa `python -m pytest -q` em projetos com testes; `off` desliga |
| `HARNEASY_MAX_VERIFY` | `2` | Máximo de verificações automáticas por pedido |
| `HARNEASY_FINAL_REVIEW` | `1` | Revisão final do pedido contra o diff; `0` desliga |
| `HARNEASY_AUTO_SKILLS` | `1` | Escolha automática de skill pelo pedido; `0` desliga |
| `HARNEASY_DISABLED_TOOLS` | — | Ferramentas a esconder do modelo, ex. `task,read_skill` |
| `HARNEASY_EMBED_MODEL` | — | Modelo de embedding para a busca por significado em `search_code` |
| `HARNEASY_CACHE_DIR` | `~/.cache/harneasy` | Onde guardar os embeddings já calculados |
| `HARNEASY_SANDBOX_NETWORK` | `0` | Libera a rede nos comandos (necessário para `npm install`, `uv add`, `pip install`) |
| `HARNEASY_REQUIRE_SANDBOX` | `0` | Bloqueia comandos quando não há isolamento do sistema operacional |
| `HARNEASY_DEBUG_LOG` | — | Arquivo `.jsonl` onde gravar as respostas cruas do modelo |

A contagem de tokens é uma estimativa quando o servidor não informa o uso. Para o Ollama usar um contexto maior, inicie-o com `OLLAMA_CONTEXT_LENGTH=<tokens>`, se a memória da GPU permitir.

## Segurança

- Todas as chamadas de ferramenta passam por `execute_tool`, inclusive as do subagente.
- Uma lista curta de comandos de leitura roda sem aprovação. Comandos desconhecidos pedem aprovação.
- Comandos destrutivos ou de rede conhecidos (`rm`, `curl`, `wget`, `git push`, `git reset`, `git clean`) são bloqueados.
- Comandos que não funcionariam no sandbox são recusados antes, com o motivo explicado ao modelo:
  - instalar pacotes com a rede desligada;
  - instalações globais;
  - processos em segundo plano (`nohup`, `&`);
  - `git clone` e `apt`.
- As ferramentas de arquivo só editam dentro do projeto. Leituras fora dele pedem aprovação.
- Saídas grandes são cortadas para proteger o contexto. A saída completa fica num arquivo temporário que o modelo pode ler por partes.
- O isolamento do sistema operacional é *best effort*:
  - **Linux:** usa `bubblewrap`, com o sistema só leitura, o projeto gravável, `/tmp` privado e `.git` só leitura.
  - **macOS:** usa `sandbox-exec`.
  - A rede fica desligada, a menos que `HARNEASY_SANDBOX_NETWORK=1`. Com a rede ligada, os caches `~/.npm` e `~/.cache` também ficam graváveis.
  - **Windows:** ainda não tem sandbox. Com `HARNEASY_REQUIRE_SANDBOX=1`, os comandos são bloqueados.

**Importante:** a política de comandos é uma camada de defesa, não uma garantia contra código malicioso. Use o harness num projeto versionado com git, revise as ações que pedem aprovação e não deixe credenciais no ambiente. Ligue a rede só quando precisar instalar algo.

## Benchmark

`bench/` mede a taxa de acerto do agente em tarefas pequenas, como corrigir um bug, editar um JSON, renomear uma função em vários arquivos ou criar um projeto. Cada tarefa roda numa pasta temporária, e a verificação só é criada depois que o agente termina.

```bash
uv run python bench/run.py --model granite4.1:3b --runs 3
uv run python bench/run.py --model granite4.1:3b --runs 5 --only corrigir_bug editar_json
```

O resultado e o log de cada execução ficam em `bench/results/<modelo>-<data>/`. Para adicionar uma tarefa, copie um item de `bench/tasks.py`.

O Ollama não é totalmente determinístico, então o resultado de uma tarefa pode variar entre execuções. Use `--runs 3` ou mais antes de concluir que uma mudança ajudou ou piorou.

## Testes

```bash
uv run python -m pytest -q
```

A suíte cobre, entre outros:
- permissões e sandbox;
- reparo de chamadas de ferramenta;
- edição e leitura de arquivos;
- compactação do histórico;
- escolha de skills;
- as conferências de fim de tarefa.

Ela não precisa de um modelo rodando: o modelo é simulado com respostas prontas.

## Estrutura

```
src/agent_harness/
  agent.py        prompt do sistema, AGENTS.md e linha de comando
  ui.py           loop do pedido e conferências de fim de tarefa
  tools.py        ferramentas e avisos depois de cada edição
  permissions.py  o que pode rodar, o que pede aprovação e o que é bloqueado
  sandbox.py      isolamento dos comandos (bubblewrap / seatbelt)
  repair.py       conserto de chamadas de ferramenta malformadas
  compact.py      compactação do histórico
  context.py      lembrete de cada turno, PLANO.md e comando de verificação
  skills.py       carregamento e escolha automática de skills
  subagents.py    ferramenta task (subagente só de leitura)
  codeindex.py    search_code e code_map
  llm.py          cliente do modelo
  builtin_skills/ skills embutidas
bench/            benchmark de tarefas
tests/            testes automatizados
```
