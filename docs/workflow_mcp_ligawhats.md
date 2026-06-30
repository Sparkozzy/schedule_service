# Workflow: `mcp_ligawhats` (WhatsApp Lead Follow-up)

Este documento detalha o fluxo de trabalho para envio de mensagens de WhatsApp aos leads quando demonstram interesse na venda.

---

## 1. Alvo do Workflow
Automatizar o envio de mensagens de texto de follow-up/fechamento via WhatsApp usando a gateway Z-API de forma multi-tenant, persistindo o estado da execução para auditoria EDW.

---

## 2. Passos do Workflow (Steps)

### 2.1 `mcp_ligawhats_normalize_phone`
- **O que faz**: Sanitiza e normaliza o número do lead recebido em Python de forma determinística, garantindo o padrão de 12 dígitos (`55DDXXXXXXXX`) sem o nono dígito extra e sem `+`.
- **Input**:
  - `phone`: `str`
- **Output**:
  - `phone_normalizado`: `str` (ex: `554195252559`)

### 2.2 `mcp_ligawhats_get_config`
- **O que faz**: Puxa as configurações Z-API do cliente correspondente no Supabase Master (`client_configurations`).
- **Input**:
  - `client_id`: `str`
- **Output**:
  - `zapi_instance_id`: `str`
  - `zapi_client_token`: `str`

### 2.3 `mcp_ligawhats_send_whatsapp`
- **O que faz**: Envia o POST request assíncrono para a URL da Z-API (`https://api.z-api.io/instances/{zapi_instance_id}/token/{zapi_client_token}/send-text`) contendo a mensagem e o header `Client-Token` (lido do `.env`).
- **Input**:
  - `phone`: `str`
  - `message`: `str`
- **Output**:
  - Resposta do Z-API contendo `zaapId` e status.

---

## 3. Rastreabilidade EDW
- **Workflow Name**: `mcp_ligawhats`
- **Execução**: Registrado em `workflow_executions` com status `PENDING` -> `RUNNING` -> `SUCCESS` / `FAILED`.
- **Passos**: Cada um dos 3 passos acima é logado individualmente em `workflow_step_executions` vinculados ao `execution_id`.
