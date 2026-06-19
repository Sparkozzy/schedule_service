---
name: mindflow
description: Reference documentation for MindFlow workflows APIs. Use this skill when the user asks to integrate, build around, or read documentation about MindFlow workflows APIs, or specifically requests the MindFlow skill.
---

# MindFlow API Integrations

Essa skill documenta o acesso aos workflows da MindFlow via API.

## pre_call_processing

O workflow `pre_call_processing` dispara uma ligação na Retell AI baseado em metadados dinâmicos e prompts obtidos no banco de dados.

**Endpoint:** `POST https://call-github.bkpxmb.easypanel.host/webhook`
**Autenticação:** Header `X-API-Key` (a chave deve estar no ambiente do sistema que consome)

### Payload Obrigatório (JSON)

```json
{
  "workflow_name": "pre_call_processing",
  "execution_id": "<ID_DE_RASTREAMENTO_UNICO_DO_CLIENTE>",
  "numero": "+55DD9XXXXXXXX",
  "nome": "Primeiro Nome",
  "email": "email@example.com",
  "agent_id": "agent_1e4cfa23e3910c557d82167949",
  "Prompt_id": "24"
}
```

### Campos Opcionais
- `quando_ligar`: ISO 8601 com timezone offset (ex: `2026-04-21T15:00:00-03:00`). Sem isso a ligação será disparada imediatamente.
- `empresa`: Nome da empresa (String).
- `segmento`: Segmento de mercado (String).

### Regras do Número de Telefone
Deve sempre iniciar com `+` e código do país (ex: `+55`).
Celular precisa ter o 9 como nono dígito (total de 13 dígitos após `+`).

### Respostas Esperadas
- `202 Accepted`: Em caso de sucesso de recebimento. O processamento será assíncrono.
- `401 Unauthorized`: API Key inválida ou ausente.
- `400 Bad Request`: Falha na formatação de `numero` ou `quando_ligar`.
- `422 Unprocessable Entity`: Campos obrigatórios ausentes ou tipos errados.

## call_predict

O workflow `call_predict` avalia a qualidade do lead (Lead Scoring) e prediz o melhor horário para ligar (Timing Predict) antes de encaminhar para o processamento de chamadas.

**Endpoint:** `POST https://call-predict-github.bkpxmb.easypanel.host/webhook/predict`
**Autenticação:** Header `X-API-Key`

### Payload Obrigatório (JSON)

```json
{
  "numero": "+55DDXXXXXXXXX",
  "agent_id": "agent_1e4cfa23e3910c557d82167949",
  "nome": "João Silva",
  "email": "joao@example.com",
  "Prompt_id": "24"
}
```

### Respostas Esperadas
- `202 Accepted`: Lead enfileirado para predição. Retorna `execution_id`.
- `400 Bad Request`: Número fora do formato internacional.
- `401 Unauthorized`: API Key inválida.
- `422 Unprocessable Entity`: Campos obrigatórios ausentes.

