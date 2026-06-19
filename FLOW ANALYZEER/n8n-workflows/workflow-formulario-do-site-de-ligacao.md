# Workflow: `formulario_do_site_de_ligacao`

> **Status n8n**: Ativo
> **Trigger**: Webhook (POST)
> **ID n8n**: `dTJ064gXJnhWsDYq74tQ2`
> **Tag**: Mindflow
> **Última execução analisada**: `489669` em `2026-05-09T12:52:24Z` (success)

---

## Descrição Geral

Workflow acionado pelo formulario institucional do site Mindflow (`https://mindflow-phvz9o6j.manus.space`). Recebe um lead (nome, numero, email, segmento, tamanho de equipe) via webhook POST, usa um Information Extractor (LLM GPT-4.1-mini) para normalizar o telefone no padrao brasileiro `+55DD9XXXXXXXX` e extrair os demais campos estruturados, monta o payload Retell e dispara uma ligacao via Retell AI (agent fixo do "Agente Mindflow (Formulário)"). Diferente do workflow `formulario` (DyXxa31k5jr2a8bqZhZR5), que apenas grava leads em Google Sheets, este aciona a ligacao em tempo real.

## Diagrama de Fluxo

```mermaid
flowchart TD
    A["Webhook POST (site)"] --> B["Information Extractor (LLM normaliza telefone)"]
    C["OpenAI Chat Model gpt-4.1-mini"] -. ai_languageModel .-> B
    B --> D["Edit Fields2 (mapeia output → vars)"]
    D --> E["Code in JS (monta body Retell)"]
    E --> F["HTTP POST api.retellai.com/v2/create-phone-call"]
```

Legenda: trigger / LLM (sub-no) / transform / output externo.

## Comunicacao com Outros Workflows

| Direcao | Workflow/Sistema | Endpoint | Metodo | Dados Passados |
|---------|------------------|----------|--------|----------------|
| Recebe de | Site institucional Mindflow (frontend `mindflow-phvz9o6j.manus.space`) | `/webhook/1c15b8f3-e21d-4211-86bc-8df091df8e82` | POST | `nome, numero, email, segmento, equipe` |
| Envia para | Retell AI (externo) | `https://api.retellai.com/v2/create-phone-call` | POST | `from_number, to_number, override_agent_id, retell_llm_dynamic_variables` |
| Indireto | OpenAI (sub-no LangChain) | `https://api.openai.com/v1` | POST | texto do lead para extracao estruturada |

Nao existe chamada para outros workflows internos da Mindflow. E um workflow "folha" terminal: recebe do site, dispara a Retell.

### Dados de Rastreabilidade

| Campo | Valor/Origem | Obrigatorio | Observacao |
|-------|--------------|-------------|------------|
| `execution_id` | Nao propagado | Faltando | Workflow nao gera nem persiste execution_id |
| `from_workflow` | Nao enviado | Faltando | Site nao passa origem; workflow nao seta |
| `workflow_id` | Nao enviado | Faltando | Nao ha registro em `workflow_executions` |
| `call_id` | Resposta da Retell | OK (so na resposta HTTP) | Nao e persistido em lugar nenhum |

> Lacuna critica de rastreabilidade: nenhum dado e gravado em Supabase. A execucao so existe no log interno do n8n.

## Exemplo de Payload Real (anonimizado)

**Trigger input** (execucao `489669`):
```json
{
  "headers": {
    "host": "n8n-mcp-n8n.bkpxmb.easypanel.host",
    "origin": "https://mindflow-phvz9o6j.manus.space",
    "referer": "https://mindflow-phvz9o6j.manus.space/",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 ..."
  },
  "body": {
    "nome": "<NOME>",
    "numero": "49999700200",
    "email": "<EMAIL>",
    "segmento": "marketing",
    "equipe": "6-20"
  }
}
```

**Apos Information Extractor (LLM)**:
```json
{
  "output": {
    "Numero": "+55XX9XXXXXXXX",
    "Nome": "<NOME>",
    "Segmento": "marketing",
    "equipe": "6-20",
    "email": "<EMAIL>"
  }
}
```

**Body enviado para Retell** (saida do `Code in JavaScript1`):
```json
{
  "from_number": "iatizeia",
  "to_number": "+55XX9XXXXXXXX",
  "override_agent_id": "agent_2117bcaaf68e8b7cc8e0d160f7",
  "metadata": {},
  "retell_llm_dynamic_variables": {
    "customer_name": "<NOME>",
    "prompt": ".",
    "now": "2026-05-09T12:52:29.626Z",
    "contexto": ". ",
    "email": "<EMAIL>",
    "numero_do_lead": "+55XX9XXXXXXXX"
  },
  "custom_sip_headers": { "X-Custom-Header": "Custom Value" }
}
```

**Resposta Retell** (output final):
```json
{
  "call_id": "call_b7559010ef20eb3a8e72252a524",
  "call_type": "phone_call",
  "agent_id": "agent_2117bcaaf68e8b7cc8e0d160f7",
  "agent_name": "Agente Mindflow (Formulário) ",
  "call_status": "registered",
  "from_number": "iatizeia",
  "to_number": "+55XX9XXXXXXXX",
  "direction": "outbound"
}
```

## Detalhamento dos Nos

### 1. `Webhook` (Trigger)
- Tipo n8n: `n8n-nodes-base.webhook` (v2.1).
- Path: `1c15b8f3-e21d-4211-86bc-8df091df8e82`, metodo POST, sem autenticacao (`authentication: none`).
- ResponseMode: `onReceived` — responde 200 imediatamente, antes mesmo da Retell.
- Body esperado: `{ nome, numero, email, segmento, equipe }`.
- Saida: para `Information Extractor`.

### 2. `Information Extractor` (LLM / Transform)
- Tipo n8n: `@n8n/n8n-nodes-langchain.informationExtractor` (v1.2).
- Texto de entrada: concatenacao bruta de `nome, numero, segmento, equipe, email` em linhas.
- Schema de extracao: campos `Numero` (obrigatorio, com prompt embutido de normalizacao para `+55DD9XXXXXXXX`, inclui inserir 9o digito se faltar), `Nome` (obrigatorio), `Segmento`, `equipe`, `email`.
- O LLM faz simultaneamente normalizacao de telefone e estruturacao do payload — ha sub-call do `OpenAI Chat Model`. Na execucao observada foram necessarias 2 chamadas (a primeira teve `OUTPUT_PARSING_FAILURE` e foi recuperada por retry interno do LangChain).

### 3. `OpenAI Chat Model` (sub-no AI)
- Tipo n8n: `@n8n/n8n-nodes-langchain.lmChatOpenAi` (v1.3).
- Modelo: `gpt-4.1-mini`.
- Credencial: `OpenAi account` (`Z2Wx2mpVaJdfm52V`).
- Anexado ao Information Extractor via porta `ai_languageModel`.

### 4. `Edit Fields2` (Transform)
- Tipo n8n: `n8n-nodes-base.set` (v3.4).
- Mapeia `output.*` para variaveis nominais: `prompt='.', numero, nome, contexto='. ', email, segmento, equipe`.
- `prompt` e `contexto` sao placeholders fixos (`.` e `. `) — o workflow nao gera prompt dinamico aqui.

### 5. `Code in JavaScript1` (Transform)
- Tipo n8n: `n8n-nodes-base.code` (v2), `runOnceForAllItems`.
- Sanitiza `prompt` (remove quebras, markdown `, *, _, ~, #, >`, troca `"` por `'`).
- Monta o `body` no formato Retell `create-phone-call`: `from_number='iatizeia'` (number alias), `to_number=numero normalizado`, `override_agent_id='agent_2117bcaaf68e8b7cc8e0d160f7'` (hardcoded — agente Mindflow Formulario), `retell_llm_dynamic_variables` com `customer_name, prompt, now=new Date().toISOString(), contexto, email, numero_do_lead`, e `custom_sip_headers: { 'X-Custom-Header': 'Custom Value' }` (placeholder).

### 6. `HTTP Request2` (Output externo)
- Tipo n8n: `n8n-nodes-base.httpRequest` (v4.2).
- POST `https://api.retellai.com/v2/create-phone-call`.
- Header `Authorization: Bearer key_540f92099b59f815c67870d0aba3` **hardcoded no parametro do no** (nao usa credencial n8n nem env var).
- `onError: continueRegularOutput`, `alwaysOutputData: true` — falha da Retell nao quebra o workflow nem retorna erro ao site (que ja recebeu 200).
- Saida: resposta da Retell com `call_id`, `call_status`, etc. (nao e persistida).

## Variaveis de Ambiente Utilizadas

Nenhuma variavel de ambiente do n8n e referenciada explicitamente. Todos os segredos estao hardcoded:

| Segredo | Onde aparece | Acao recomendada |
|---------|--------------|------------------|
| `key_540f92099b59f815c67870d0aba3` (Retell Bearer) | Header inline em `HTTP Request2` | Mover para env `RETELL_API_KEY` |
| `agent_2117bcaaf68e8b7cc8e0d160f7` (Retell agent) | Inline em `Code in JavaScript1` | Env `RETELL_AGENT_FORMULARIO_SITE` |
| `from_number = 'iatizeia'` | Inline em `Code in JavaScript1` | Env `RETELL_FROM_NUMBER_DEFAULT` |
| OpenAI API key | Credencial n8n `OpenAi account` | Env `OPENAI_API_KEY` |

## Credenciais n8n Utilizadas

| Nome da Credencial | Tipo | Nos que Usam |
|--------------------|------|--------------|
| `OpenAi account` (id `Z2Wx2mpVaJdfm52V`) | `openAiApi` | `OpenAI Chat Model` |

> O no `HTTP Request2` nao usa credencial gerenciada — Bearer Retell esta hardcoded.

---

## Migration Brief — Antigravity / Python

> Especificacao para o agente do Antigravity reimplementar este workflow em Python conforme `Usefull_Skills/docs/conventions.md` (EDW).

### Camada API (FastAPI)

- **Endpoint sugerido**: `POST /webhook/formulario-site-ligacao` (path expoe origem; pode tambem manter o UUID `1c15b8f3-e21d-4211-86bc-8df091df8e82` para nao quebrar o site).
- **Schema Pydantic de entrada** (`schemas.py`):

```python
class FormularioSiteLigacaoInput(BaseModel):
    nome: str
    numero: str  # cru, pode vir sem +55 e sem 9 — normalizar no worker
    email: Optional[EmailStr] = None
    segmento: Optional[str] = None
    equipe: Optional[str] = None  # faixa textual ex "6-20"
```

- **Resposta**: `202 Accepted` + `{ "execution_id": "<uuid>" }`.
- **Validacoes obrigatorias**: `nome` nao vazio; `numero` contem ao menos 8 digitos numericos apos `re.sub(r"\D", "", numero)`. Demais sao opcionais.
- **Acoes da API**: cria registro mestre em `workflow_executions` (status `PENDING`), enfileira job ARQ, retorna 202.

### Camada Worker (ARQ)

Mapa no n8n -> step EDW (cada step executa via `run_step_with_retry`):

| # | n8n node | Step EDW (`formulario_do_site_de_ligacao_<oqf>`) | I/O | Lib Python | Retries | Async |
|---|----------|--------------------------------------------------|-----|------------|---------|-------|
| 1 | Webhook | (na API, cria master execution) | in: payload; out: execution_id | FastAPI | 0 | sim |
| 2 | Information Extractor + OpenAI | `formulario_do_site_de_ligacao_normaliza_telefone` | in: numero cru; out: `+55DD9XXXXXXXX` | `re` puro (ou `httpx` p/ OpenAI se LLM ainda for necessario) | 3 | sim |
| 3 | Edit Fields2 | (absorvido no proximo step) | — | — | — | — |
| 4 | Code in JavaScript1 | `formulario_do_site_de_ligacao_monta_payload_retell` | in: dados normalizados; out: body Retell | puro Python | 0 | sim |
| 5 | HTTP Request2 | `formulario_do_site_de_ligacao_create_retell_call` | in: body; out: call_id, call_status | `httpx.AsyncClient` | 3 | sim |
| 6 | (faltante hoje) | `formulario_do_site_de_ligacao_persiste_resultado` | in: call_id; out: registro atualizado | `supabase` singleton | 3 | sim |

> Recomendacao forte: substituir o LLM por **regex puro** no step `normaliza_telefone` (o prompt do Information Extractor descreve regras determinsticas — `re.sub(r"\D","")` + correcao de 9o digito + prefixo `+55`). Economiza ~5s/exec, ~917 tokens OpenAI por chamada e elimina o ponto de falha `OUTPUT_PARSING_FAILURE` observado na execucao `489669`. Se quiser manter LLM como fallback, usar `httpx.AsyncClient` chamando OpenAI direto, nao via langchain.

### Comunicacao Externa (Saidas)

**Retell AI — Criar ligacao**
- URL: `POST https://api.retellai.com/v2/create-phone-call`
- Headers: `Authorization: Bearer ${RETELL_API_KEY}`, `Content-Type: application/json`
- Body:
```json
{
  "from_number": "${RETELL_FROM_NUMBER_DEFAULT}",
  "to_number": "<E.164>",
  "override_agent_id": "${RETELL_AGENT_FORMULARIO_SITE}",
  "metadata": { "execution_id": "<uuid>", "from_workflow": "formulario_do_site_de_ligacao" },
  "retell_llm_dynamic_variables": {
    "customer_name": "<nome>",
    "prompt": ".",
    "now": "<ISO8601 UTC>",
    "contexto": ". ",
    "email": "<email>",
    "numero_do_lead": "<E.164>",
    "segmento": "<segmento>",
    "equipe": "<equipe>"
  }
}
```
- Retorno: `{ call_id, call_status, agent_id, to_number, ... }` — persistir `call_id` no master execution.

### Variaveis de Ambiente Necessarias (.env)

| Variavel | Origem n8n | Uso no Python |
|----------|------------|---------------|
| `RETELL_API_KEY` | Bearer hardcoded no HTTP Request2 | Header `Authorization` |
| `RETELL_AGENT_FORMULARIO_SITE` | `override_agent_id` hardcoded no Code | Body `override_agent_id` |
| `RETELL_FROM_NUMBER_DEFAULT` | `from_number = 'iatizeia'` no Code | Body `from_number` |
| `OPENAI_API_KEY` | credencial `OpenAi account` | (opcional, so se manter LLM) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | nao existia | Cliente singleton para persistir execucao |
| `REDIS_URL` | nao existia | ARQ (`RedisSettings.from_dsn`) |

### Rastreabilidade Obrigatoria (conventions.md)

- `workflow_id`: `formulario_do_site_de_ligacao_v1` (constante fixa).
- `from_workflow`: `formulario_do_site_de_ligacao` (este workflow e a origem; campo se propaga no `metadata` da Retell).
- `execution_id`: UUID gerado pela API no recebimento.
- Persistir em: `workflow_executions` (master, com `input_data`, `output_data={call_id, call_status}`) + `workflow_step_executions` (detail por step, via `run_step_with_retry`).

### Pontos de Atencao / Divergencias do EDW

- **Sem persistencia**: hoje o workflow NAO grava nada em Supabase — incluir master execution + step executions e ganho puro.
- **Bearer Retell hardcoded no JSON do workflow**: vazamento de credencial; trocar por env var na migracao (e rotacionar a key apos migrar).
- **LLM para normalizar telefone**: regras sao deterministas, viavel substituir por regex no step `normaliza_telefone`. Mantem-se o LLM apenas se quiser tolerancia a `nome`/`segmento` mal preenchidos (mas hoje nem isso e validado).
- **`responseMode: onReceived`**: ja se comporta como `202 Accepted` — coerente com EDW (API responde rapido, worker faz o trabalho).
- **`onError: continueRegularOutput` no HTTP Retell**: falha silenciosa. Em Python, registrar `FAILED` em `workflow_step_executions` com `error_details` da resposta Retell, e atualizar master para `FAILED`.
- **Sem `prompt`/`contexto` reais**: hoje sao `.` e `. ` — o agente Retell ignora ou usa default. Confirmar com o time se isso e intencional ou se faltava enriquecimento (ex: chamar Supabase para buscar prompt por `agent_id`/`segmento`).
- **Checkbox EDW**: o agente do Antigravity deve conferir conventions:
  - [ ] FastAPI + Pydantic
  - [ ] `httpx.AsyncClient` (nao `requests`)
  - [ ] `arq` para fila (sem `BackgroundTasks`/`time.sleep`/`APScheduler`)
  - [ ] `run_step_with_retry` com exponential backoff + jitter (cap 30s)
  - [ ] `supabase` singleton module-level
  - [ ] Steps nomeados `formulario_do_site_de_ligacao_<oqf>`
  - [ ] `workflow_executions` master + `workflow_step_executions` detail
  - [ ] Rastreabilidade `workflow_id` / `from_workflow` / `execution_id`
  - [ ] Anonimizacao mantida nos logs
  - [ ] Credenciais via env var, nao hardcoded

### Status de Migracao

- [x] Documentado
- [ ] Schemas Pydantic definidos
- [ ] API endpoint implementado
- [ ] Worker steps implementados
- [ ] Validado em ambiente de teste
- [ ] Migrado em producao

> **Sem Python implementado.** Esta doc e apenas spec — a implementacao ocorre no Antigravity.
