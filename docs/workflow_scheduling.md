# Workflow de Agendamento: `scheduling_workflow`

Este documento detalha o fluxo de trabalho orientado a eventos para o agendamento de reuniões e consultas dos clientes.

## 1. Alvo do Workflow
Automatizar o agendamento de reuniões nas agendas integradas dos clientes, persistindo as informações em seus respectivos Supabases e notificando a equipe interna.

---

## 2. Passos do Workflow (Steps)

Abaixo estão os nós de processamento assíncrono que compõem o `scheduling_workflow`.

### 2.1 `scheduling_workflow_validate_client`
- **O que faz**: Recebe o `client_id` e busca as configurações ativas no banco de dados Master (`client_configurations`).
- **Input**:
  - `client_id`: `str`
- **Output**:
  - `supabase_url`: `str`
  - `supabase_service_key`: `str`
  - `google_calendar_id`: `str`
  - Configurações da Z-API.
- **Tratamento de erro**: Se o cliente não existir, aborta a execução e registra status `FAILED` em `workflow_executions`.

### 2.2 `scheduling_workflow_check_availability`
- **O que faz**: Consulta a disponibilidade do calendário do cliente. Se a janela consultada for maior do que 1 hora, fatia a janela em sub-intervalos e dispara requisições concorrentes com `asyncio.gather` para minimizar latência.
- **Input**:
  - `calendar_id`: `str`
  - `data_inicial`: `datetime` (UTC)
  - `data_final`: `datetime` (UTC)
- **Output**:
  - `available`: `bool`
  - `slots`: `List[Dict[str, Any]]`

### 2.3 `scheduling_workflow_create_calendar_event`
- **O que faz**: Cria o evento de 1 hora na agenda correspondente utilizando a credencial central de `ryanferrari@iatize-ia.com`. Adiciona videoconferência (Google Meet) e convidados.
- **Input**:
  - `calendar_id`: `str`
  - `data_hora`: `datetime` (UTC)
  - `email_lead`: `str`
  - `nome_lead`: `str`
  - `titulo_evento`: `str`
  - `resumo`: `str`
- **Output**:
  - `google_event_id`: `str`
  - `meet_link`: `str`

### 2.4 `scheduling_workflow_upsert_lead_appointment`
- **O que faz**: Insere ou atualiza o registro do agendamento na tabela `agendamentos` do Supabase do respectivo cliente.
- **Input**:
  - `nome`: `str`
  - `email`: `str`
  - `numero`: `str`
  - `canal`: `str` ('whats' | 'ligacao')
  - `data_agendamento`: `datetime` (UTC)
  - `google_event_id`: `str`
  - `calendar_id`: `str`
  - `execution_id`: `uuid`
  - `agent_id`: `str` (Opcional - ID do agente de IA que marcou a reunião)
- **Output**:
  - `appointment_id`: `uuid`

### 2.5 `scheduling_workflow_notify_whatsapp`
- **O que faz**: Dispara uma notificação para o grupo de WhatsApp interno configurado para o cliente via Z-API.
- **Input**:
  - `instance_id`: `str`
  - `client_token`: `str`
  - `group_id`: `str`
  - `mensagem`: `str`
- **Output**:
  - `zapi_message_id`: `str`

### 2.6 `scheduling_workflow_send_to_crm`
- **O que faz**: Se o cliente possuir configuração de CRM ativa (`crm_config`), envia um evento padronizado contendo dados do lead e da reunião para a URL configurada do Webhook.
- **Input**:
  - `client_id`: `str`
  - `crm_config`: `dict`
  - `appointment_data`: `dict`
- **Output**:
  - `status`: `str` ('success' | 'skipped')
  - `status_code`: `int` (opcional)
  - `response`: `dict` (opcional)

---

## 3. Tratamento de Timezone e Datas
- Todas as entradas e saídas de data via API usam strings formatadas sob a especificação ISO 8601 com fuso horário explícito.
- No banco de dados (`agendamentos`, `workflow_executions`, `workflow_step_executions`), as datas são salvas como `TIMESTAMPTZ` em **UTC**.
- Toda a lógica de verificação e restrição (ex: evitar agendamentos fora de horários comerciais ou feriados) converte a data para o fuso horário de Brasília (`America/Sao_Paulo`) usando `zoneinfo.ZoneInfo`.
