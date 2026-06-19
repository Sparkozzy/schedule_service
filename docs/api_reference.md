# API Reference - Mindflow Scheduling Service

Este documento detalha a interface de integração para o consumo do serviço de agendamentos (`scheduling_workflow`). Este serviço é responsável por consultar a disponibilidade de agendas (Google Calendar) e realizar agendamentos integrados multi-tenant com persistência no Supabase.

---

## URL de Produção (Easypanel)
As requisições em ambiente de produção devem ser enviadas para:
* **Base URL:** `https://schedule-service-github.bkpxmb.easypanel.host`

---

## Autenticação

Todas as rotas de webhook requerem autenticação por token portador (Bearer Token).
* **Header:** `Authorization: Bearer <API_BEARER_TOKEN>`
* **Exemplo:** `Authorization: Bearer mf_sk_2026_pre_call_xK9v3Qm7bR4wT1nZ`

---

## Endpoints da API

### 1. Health Check
Verifica se a API está online e respondendo adequadamente.

* **Método:** `GET`
* **Rota:** `/health`
* **Autenticação:** Não requer.
* **Exemplo de Resposta (200 OK):**
  ```json
  {
    "status": "ok",
    "service": "scheduling-service"
  }
  ```

---

### 2. Agendamento de Reunião (`/webhook/schedule`)
Dispara o fluxo de agendamento de forma assíncrona. A API realiza validações básicas, registra a execução no Supabase Master e do Cliente, enfileira o job na fila do Redis (ARQ) e responde imediatamente com status `202 Accepted`.

* **Método:** `POST`
* **Rota:** `/webhook/schedule`
* **Headers:**
  - `Authorization: Bearer <TOKEN>`
  - `Content-Type: application/json`

#### Payload de Entrada (JSON)

| Campo | Tipo | Obrigatório | Descrição | Exemplo |
| :--- | :--- | :--- | :--- | :--- |
| `client_id` | `string` | Sim | Identificador exclusivo do cliente configurado no banco Master. | `"cliente_teste"` |
| `nome` | `string` | Sim | Nome completo do lead para o evento na agenda. | `"João da Silva"` |
| `email` | `string` | Sim | E-mail do lead (deve ser um e-mail válido). | `"joao@example.com"` |
| `numero` | `string` | Sim | Telefone do lead em formato internacional (E.164, iniciando com `+`). | `"+5548996027108"` |
| `canal` | `string` | Sim | Canal de origem do agendamento. Valores aceitos: `"whats"` ou `"ligacao"`. | `"whats"` |
| `data_agendamento` | `string` | Sim | Data e hora em formato ISO 8601 com offset de timezone. | `"2026-06-25T14:00:00-03:00"` |
| `resumo` | `string` | Não | Resumo opcional sobre os desafios/dores do lead. | `"Procura automações de CRM"` |
| `titulo` | `string` | Não | Título do evento no Google Calendar. | `"Reunião Inicial - Mindflow"` |
| `agent_id` | `string` | Não | ID do agente de IA (ex: Retell agent_id ou bot do whatsapp) que marcou a reunião. | `"agent_123"` |

#### Exemplo de Payload:
```json
{
  "client_id": "cliente_teste",
  "nome": "João da Silva",
  "email": "joao@example.com",
  "numero": "+5548996027108",
  "canal": "whats",
  "data_agendamento": "2026-06-25T14:00:00-03:00",
  "resumo": "Interesse em automações de vendas.",
  "titulo": "Reunião de Alinhamento Comercial",
  "agent_id": "agent_comercial_123"
}
```

#### Respostas da API:

* **202 Accepted:** O agendamento foi validado com sucesso e enfileirado para processamento.
  ```json
  {
    "status": "Accepted",
    "execution_id": "c9a64e1c-5d2f-48d0-99eb-03bcf5a23077",
    "message": "Agendamento recebido e enviado para processamento em background."
  }
  ```
* **401 Unauthorized:** Token de autenticação Bearer ausente ou inválido.
  ```json
  {
    "detail": "Token inválido ou não fornecido."
  }
  ```
* **404 Not Found:** Cliente (`client_id`) não localizado no banco Master.
  ```json
  {
    "detail": "Configuração para o cliente 'cliente_inexistente' não encontrada."
  }
  ```
* **422 Unprocessable Entity:** Payload incorreto ou campos inválidos (ex: número sem `+` ou canal inválido).
  ```json
  {
    "detail": [
      {
        "loc": ["body", "numero"],
        "msg": "Value error, O número de telefone deve começar com '+' e estar no formato internacional E.164.",
        "type": "value_error"
      }
    ]
  }
  ```

---

### 3. Verificar Disponibilidade de Agenda (`/webhook/check-availability`)
Verifica concorrentemente no Google Calendar se existem slots livres no intervalo solicitado. Divide o intervalo em slots de 1 hora e retorna a lista de disponibilidades.

* **Método:** `POST`
* **Rota:** `/webhook/check-availability`
* **Headers:**
  - `Authorization: Bearer <TOKEN>`
  - `Content-Type: application/json`

#### Payload de Entrada (JSON)

| Campo | Tipo | Obrigatório | Descrição | Exemplo |
| :--- | :--- | :--- | :--- | :--- |
| `client_id` | `string` | Sim | Identificador exclusivo do cliente configurado no banco Master. | `"cliente_teste"` |
| `data_inicial` | `string` | Sim | Início do período a pesquisar em formato ISO 8601 com offset. | `"2026-06-25T09:00:00-03:00"` |
| `data_final` | `string` | Sim | Fim do período a pesquisar em formato ISO 8601 com offset. | `"2026-06-25T18:00:00-03:00"` |

#### Exemplo de Payload:
```json
{
  "client_id": "cliente_teste",
  "data_inicial": "2026-06-25T09:00:00-03:00",
  "data_final": "2026-06-25T18:00:00-03:00"
}
```

#### Exemplo de Resposta (200 OK):
```json
{
  "client_id": "cliente_teste",
  "disponivel": true,
  "slots": [
    {
      "data": "2026-06-25T09:00:00-03:00",
      "available": true
    },
    {
      "data": "2026-06-25T10:00:00-03:00",
      "available": false
    },
    {
      "data": "2026-06-25T11:00:00-03:00",
      "available": true
    }
  ]
}
```

---

## Regras de Negócio e Validações

1. **Formato de Telefone:** Deve seguir estritamente o formato E.164 internacional (ex: `+5548996027108`).
2. **Canais Suportados:** Apenas `"whats"` e `"ligacao"` são valores permitidos.
3. **Timezones:** Datas de entrada e saída devem especificar fuso horário explicitamente (ex: `-03:00` ou `Z`). Internamente, todas as transações são salvas em UTC no banco de dados e processadas considerando o horário de Brasília (`America/Sao_Paulo`).
4. **Finais de Semana:** Slots de finais de semana são automaticamente considerados indisponíveis (`available: false`).
