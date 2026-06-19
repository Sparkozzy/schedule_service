# API Reference - Call Predict Workflow

Este documento detalha a interface de integração para o consumo do workflow `call_predict`. Este workflow é responsável por avaliar a qualidade de um lead e determinar o melhor momento para realizar uma chamada telefônica.

---

## Endpoint: `call_predict`

O workflow é disparado através de um webhook que recebe os dados básicos do lead e inicia o processamento assíncrono.

- **URL:** `https://call-predict-github.bkpxmb.easypanel.host/webhook/predict`
- **Método:** `POST`
- **Autenticação:** Header `X-API-Key` (verificar disponibilidade no ambiente)
- **Content-Type:** `application/json`

### Payload de Entrada (JSON)

Todos os campos abaixo são **obrigatórios**.

```json
{
  "numero": "+55DDXXXXXXXXX",
  "agent_id": "agent_1e4cfa23e3910c557d82167949",
  "nome": "João Silva",
  "email": "joao@example.com",
  "Prompt_id": "24"
}
```

#### Descrição dos Campos:
| Campo | Tipo | Descrição | Exemplo |
|---|---|---|---|
| `numero` | `string` | Número do telefone em formato internacional. | `+5548996027108` |
| `agent_id` | `string` | ID do agente configurado na plataforma Retell AI. | `agent_123456789` |
| `nome` | `string` | Nome completo do lead para personalização da chamada. | `João da Silva` |
| `email` | `string` | Endereço de e-mail do lead. | `lead@email.com` |
| `Prompt_id` | `string` | Identificador do prompt dinâmico que será utilizado na ligação. | `24` |

---

### Respostas da API

| Código HTTP | Descrição | Exemplo de Resposta |
|---|---|---|
| **202 Accepted** | Sucesso. O lead foi validado e enfileirado para processamento. | `{"status": "Accepted", "execution_id": "uuid-...", "message": "Lead enfileirado para predição"}` |
| **400 Bad Request** | Erro de validação no formato dos dados (ex: número sem `+`). | `{"detail": "O número de telefone deve estar no formato internacional (+55...)"}` |
| **401 Unauthorized** | Chave de API inválida ou ausente. | `{"detail": "Could not validate credentials"}` |
| **422 Unprocessable Entity** | Payload malformado ou campos obrigatórios ausentes. | `{"detail": [{"loc": ["body", "nome"], "msg": "field required", ...}]}` |
| **500 Internal Server Error** | Falha interna ao processar o enfileiramento. | `{"detail": "Erro interno ao processar webhook"}` |

---

## Fluxo de Processamento (Assíncrono)

Após o recebimento (`202 Accepted`), o sistema executa os seguintes passos internamente:

1. **Rastreabilidade**: Cria um registro em `workflow_executions` com o `execution_id` fornecido.
2. **Avaliação (Lead Scoring)**:
   - Se o lead tiver histórico, calcula a probabilidade de conversão utilizando modelos de Machine Learning.
   - Leads abaixo do threshold definido (`LS_THRESHOLD`) são descartados automaticamente.
3. **Predição de Horário (Timing Predict)**:
   - Determina a melhor janela de horário (fora do período de descanso 23h-06h) para maximizar a conversão.
4. **Encaminhamento**:
   - Envia o payload final para o workflow de execução de chamadas (`pre_call_processing`).

### Monitoramento
Você pode acompanhar o status da execução consultando a tabela `workflow_executions` no Supabase utilizando o `execution_id` retornado pela API.

---

## Regras Críticas de Negócio

1. **Formato do Número**: O número deve obrigatoriamente começar com `+` seguido do código do país.
2. **Exploration Rate**: Aproximadamente 5% dos leads são enviados imediatamente (grupo de controle) para alimentar o aprendizado contínuo dos modelos.
3. **Blackout Period**: Nenhuma ligação será agendada entre as **23:00** e as **07:00** (Horário de Brasília).
