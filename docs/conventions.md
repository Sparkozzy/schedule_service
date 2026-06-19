# Convenções de Código - Python Workflow (EDW)

Este documento define as diretrizes obrigatórias para o desenvolvimento de fluxos de trabalho orientados a eventos (Event-Driven Workflows) neste projeto.

## 🕒 Gestão de Tempo e Datas

- **Banco de Dados**: O campo `created_at` (e similares que vão para a persistência) deve usar o formato **ISO 8601 em UTC/Z**.
- **Lógica de Código**: Datas manipuladas internamente devem seguir o formato ISO 8601, mas convertidas para o fuso horário de Brasília (**America/Sao_Paulo**).
- **Funções padrão:**
  - `get_utc_now()` → ISO 8601 UTC para persistência.
  - `get_br_now()` → datetime com fuso `America/Sao_Paulo` para lógica interna.
  - `parse_iso_to_br(iso_date)` → Converte ISO 8601 de qualquer fuso para Brasília.
- **Validação de Webhook**: O campo `quando_ligar` deve obrigatoriamente conter timezone offset (ex: `-03:00` ou `Z`). Payloads sem fuso são rejeitados com `400 Bad Request`.

## 🔗 Comunicação entre Workflows

Ao acionar ou transitar entre fluxos, os seguintes metadados de rastreabilidade são **obrigatórios**:
- `workflow_id`: Identificador fixo do tipo de workflow.
- `from_workflow`: Nome do workflow de origem.
- `execution_id`: Identificador único da execução atual (UUID).

## 🧩 Definição de Nós (Nodes)

- Um **Nó** é a **mínima ação rastreável** dentro de um workflow.
- **Regra de Ouro**: Nunca mescle ações distintas. Busca de dados, transformação e envio externo devem ser nós separados.
- Exemplo de sequência atual (workflow `pre_call_processing`):
  1. `agendamento_redis` — Decisão de timing (imediato vs futuro via Redis `_defer_until`).
  2. `fetch_prompt` — Busca dados no Supabase (async).
  3. `format_payload` — Transformação de dados e substituição de variáveis.
  4. `create_retell_call` — Envio assíncrono (httpx) para API externa (Retell AI).

### Executor Genérico (`run_step_with_retry`)

Todos os nós devem ser executados via `run_step_with_retry()`. Esta função garante:
- Registro automático de cada tentativa em `workflow_step_executions` (sucesso e falha).
- Retry configurável por nó (`max_retries`) com **exponential backoff + jitter** (`2^attempt + random(0,1)`, cap 30s).
- Recebe um `worker_func` opcional (async) com a lógica real; sem ele, executa simulação (fallback).
- Todas as chamadas internas usam `await` (non-blocking).

## 🏗️ Stack Tecnológica

- **Backend**: Sempre usar **Python**.
- **Frameworks**: Usar **FastAPI** ou **FastMCP**.
- **Proibido**: Nunca utilizar Flask, `requests` (bloqueante), `time.sleep()`, `BackgroundTasks` (FastAPI), ou `APScheduler`.
- **HTTP Requests**: Usar `httpx.AsyncClient()` para chamadas assíncronas a APIs externas (ex: Retell AI).
- **Filas e Agendamento**: Usar `arq` (Async Redis Queue) para processamento em background e agendamento de tarefas futuras.

## 📛 Convenção de Nomenclatura

- **Workflows**: Nomes únicos e descritivos em `snake_case` (ex: `pre_call_processing`).
- **Steps (Passos)**: Devem seguir o padrão `{{workflow_name}}_{{OQF}}`, onde OQF é "O Que Faz" (ex: `pre_call_processing_fetch_prompt`).


## ⏰ Agendamento e Resiliência (Redis + ARQ)

Para fluxos que exigem execução futura, seguimos o padrão de **Agendamento Persistente via Redis**:

1.  **Imediata**: Se a data agendada for passada ou atual, a execução segue para o próximo nó imediatamente.
2.  **Futuro**: Se a data for futura, utilizamos o `arq` com `_defer_until` para agendar o job no Redis de forma **persistente**.
3.  **Rastreabilidade de Agendamento**: O ato de agendar é um **Nó (Step)** (`agendamento_redis`). Deve ser registrado em `workflow_step_executions` como `SUCCESS`, contendo no `output_data` a confirmação do horário agendado.
4.  **Resposta do Webhook**: O webhook deve retornar `202 Accepted` imediatamente após criar o registro mestre e enfileirar no Redis.
5.  **Persistência**: Jobs agendados vivem no Redis. Restarts do servidor **não perdem** jobs pendentes (desde que o Redis esteja ativo).

## 📊 Estrutura de Monitoramento (Mestre-Detalhe)

Toda execução deve ser registrada no Supabase seguindo o padrão Mestre-Detalhe:

1. **Início do Fluxo**: Registrar entrada em `workflow_executions` (Master) com status `PENDING`.
2. **Início de Execução**: Atualizar status para `RUNNING` ao começar os nós.
3. **Cada Passo**: Registrar cada tentativa e resultado em `workflow_step_executions` (Detail).
4. **Finalização**: Atualizar registro mestre para `SUCCESS` (com `call_id`) ou `FAILED` (com `error_details`).

### Tabela: workflow_executions
- `status`: PENDING → RUNNING → SUCCESS | FAILED.
- `input_data` / `output_data`: JSONB.

### Tabela: workflow_step_executions
- `execution_id`: FK para a tabela mestre.
- `step_name`: Nome seguindo a convenção de nomenclatura.
- `attempt`: Contador de tentativas (inicia em 1).
- `status`: SUCCESS, FAILED, SKIPPED.

## 🤖 Machine Learning e Modelos (XGBoost)

- **Carregamento**: Modelos devem ser carregados **uma única vez** no hook `startup` do ARQ Worker, via padrão Singleton. Nunca carregar modelo dentro de uma função de task.
- **Injeção via Contexto**: Modelos ficam disponíveis para todas as tasks via `ctx["model_ls"]` e `ctx["model_tp"]`.
- **Formato de modelo**: Arquivos `.pkl` (Pickle format), salvos em `models/`.
- **Inferência**: Usar `xgboost.Booster.predict()` sobre `xgboost.DMatrix` construído com `pandas.DataFrame`.
- **Grupo de Controle**: 5% das inferências devem ser marcadas como `is_exploration=True` (random). Nesse caso, a lógica de ML é **ignorada** e a ligação é feita como se fosse LIGAR/horário padrão (fins de estudo).

## 📐 Schemas Pydantic

- **Todos os payloads** de entrada e saída de endpoints e tasks devem ser modelados com Pydantic.
- **Localização**: Schemas em `schemas.py` na raiz do projeto.
- **Campos opcionais**: Usar `Optional[T] = None`.
- **Payload mínimo de entrada** do `call_predict`: `numero` (str) e `agent_id` (str).

## 🔀 Separação Estrita API ↔ Worker

- **API (FastAPI)**: Recebe, valida payload (Pydantic), enfileira no Redis (ARQ), responde `202 Accepted`. Ponto final.
- **Worker (ARQ)**: Executa toda lógica pesada: ETL de features, inferência ML, rastreabilidade no Supabase, e eventualmente disparar a ligação.
- **Proibido**: A API nunca importa modelos XGBoost. O Worker nunca retorna respostas HTTP diretas.

## 📝 Scripts Exploratórios e Células

- **Regra da Primeira Célula**: TODO arquivo de experimentação ou script Python dividido em células interativas (usando `# %%`) **DEVE obrigatoriamente iniciar com `# %%` na linha 1**.
- Todos os `imports` e configurações de ambiente devem ficar encapsulados e restritos a essa primeira célula. Nunca insira um `import` solto ao longo ou topo do arquivo que não esteja dentro de uma marcação de célula.

## 🗄️ Conexões Singleton (Banco e Redis)

- **Supabase Client**: Instanciar o cliente `supabase` **uma única vez** por processo (module-level singleton). Nunca criar dentro de funções de task.
- **Redis**: Configurado via `RedisSettings` do ARQ; gerenciado pelo próprio ARQ.
- **Imports pesados**: `xgboost`, `pandas` devem ser importados apenas no worker, nunca no módulo da API.

## 🛠️ Infraestrutura e Deploy no Easypanel

1. **Conexões Redis (ARQ)**: NUNCA utilize variáveis separadas como `REDIS_HOST` e `REDIS_PORT`. O Easypanel injeta uma única string de conexão chamada `REDIS_URL`. Você DEVE sempre ler o `os.getenv("REDIS_URL")`, tratar caracteres especiais (como `#` substituído por `%23`) e inicializar o ARQ exclusivamente com `RedisSettings.from_dsn(REDIS_URL)`.
2. **Persistência de Modelos de ML**: Nossos modelos XGBoost são exportados no formato binário `.pkl`. O carregamento em memória (dentro do hook `startup` do ARQ) DEVE ser feito utilizando a biblioteca `joblib` (`joblib.load()`), e nunca via arquivos `.json`.
3. **Workers Desacoplados**: O Easypanel roda o Worker em um contêiner separado da API. Se o Worker tentar conectar no `localhost`, ele falhará. Ele sempre dependerá da `REDIS_URL` injetada via variável de ambiente para achar o contêiner vizinho.

---
*Este documento é a fonte da verdade para o desenvolvimento do ecossistema MindFlow.*
