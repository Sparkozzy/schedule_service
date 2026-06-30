# Arquitetura do Serviço de Agendamento Multi-Tenant

Este documento descreve a arquitetura técnica do serviço de agendamento multi-tenant da Mindflow.

## 1. Visão Geral da Arquitetura

O sistema é baseado em **Event-Driven Workflows (EDW)** em Python, utilizando **FastAPI** para a interface de API e **ARQ** (Redis Queue) para o processamento assíncrono e agendamentos futuros. O isolamento de clientes (multi-tenant) é realizado por meio de conexões dinâmicas a diferentes projetos Supabase, mantendo a facilidade de integração do Google Calendar através de uma conta principal de consolidação (`ryanferrari@iatize-ia.com`).

```
                              ┌────────────────────────┐
                              │     Google Calendar    │
                              │ (ryanferrari@iatize)   │
                              └───────────▲────────────┘
                                          │
                                          │ OAuth / Shared Calendar ID
┌───────────────┐                  ┌──────┴──────┐                  ┌─────────────────────────┐
│  API (FastAPI)│ ──[ Enfileira ]─►│ Worker (ARQ)│ ──[ Registra ]──►│ Supabase do Cliente (N) │
└───────▲───────┘                  └──────┬──────┘                  └─────────────────────────┘
        │                                 │
        │ Webhook                         │ Notifica
        │                                 ▼
┌───────┴───────┐                  ┌─────────────┐
│ Agente Retell │                  │ Z-API (WA)  │
└───────────────┘                  └─────────────┘
```

---

## 2. Estrutura de Banco de Dados

### 2.1 Supabase Master (Mindflow)

Contém as configurações de integração e chaves de acesso para cada cliente.

#### Tabela: `client_configurations`
- `client_id` (TEXT, PK): Identificador amigável do cliente (ex: `cliente-a`).
- `client_name` (TEXT): Nome legível do cliente.
- `supabase_url` (TEXT): Endpoint do Supabase do cliente.
- `supabase_service_key` (TEXT): Chave service_role (criptografada em trânsito) para operações de escrita administrativa.
- `supabase_anon_key` (TEXT): Chave anônima para acessos públicos.
- `google_calendar_id` (TEXT): ID da agenda compartilhada do cliente (e-mail ou ID do calendar).
- `zapi_instance_id` (TEXT, Opcional): ID da instância do WhatsApp (Z-API).
- `zapi_client_token` (TEXT, Opcional): Token do cliente da Z-API.
- `zapi_group_id` (TEXT, Opcional): ID do grupo de notificação interna do time.

---

### 2.2 Supabase do Cliente (Ambientes Isolados)

Cada cliente possui seu próprio Supabase com a mesma estrutura de tabelas.

#### Tabela: `agendamentos`
Registra os agendamentos efetuados. Possui RLS habilitado para inserção pública por usuários `anon`.
- `id` (UUID, PK): Gerado automaticamente pelo Postgres.
- `created_at` (TIMESTAMPTZ): Data de registro do agendamento (UTC).
- `nome` (TEXT): Nome do lead.
- `email` (TEXT): E-mail do lead.
- `numero` (TEXT): Telefone no formato E.164 (`+55...`).
- `canal` (TEXT): Canal de origem (`whats` ou `ligacao`).
- `data_agendamento` (TIMESTAMPTZ): Data e hora da reunião (UTC).
- `status` (TEXT): Estado do agendamento (`agendado`, `cancelado`, `realizado`).
- `detalhes` (TEXT): Resumo ou anotações geradas pelo agente.
- `google_event_id` (TEXT): ID do evento no Google Calendar.
- `calendar_id` (TEXT): ID da agenda utilizada.
- `execution_id` (UUID): ID da execução do workflow para rastreabilidade.
- `agent_id` (TEXT): ID do agente AI (ex: Retell Agent ID ou bot do WhatsApp) que efetuou o agendamento.

#### Tabelas de Rastreabilidade EDW
Em conformidade com [conventions.md](file:///home/ryanf/Schedule_service/docs/conventions.md), cada Supabase de cliente terá:
- `workflow_executions`: Armazena o cabeçalho e estado de cada execução de fluxo.
- `workflow_step_executions`: Armazena os passos individuais (`verifica_disponibilidade`, `agendar_evento`, etc.).

---

## 3. Gestão de Conexões e Singleton

- O cliente do Supabase Master é instanciado como um **Singleton** na inicialização do serviço.
- As conexões com os Supabases dos clientes são instanciadas dinamicamente usando uma estratégia de cache em memória:
  ```python
  client_cache = {} # Mapeia client_id -> SupabaseClient
  ```
- O Google Calendar API Client é configurado uma única vez usando as credenciais de `ryanferrari@iatize-ia.com`, permitindo acesso de leitura/escrita a qualquer `calendar_id` configurado e compartilhado nas tabelas de clientes.

---

## 4. Servidor MCP (Model Context Protocol)

Para permitir a integração direta com agentes de inteligência artificial externos ao ambiente local, o projeto expõe uma interface MCP implementada com **FastMCP** no arquivo [mcp_server.py](file:///home/ryanf/Schedule_service/mcp_server.py).

### 4.1 Segurança e Transporte
- **Transporte SSE (Server-Sent Events):** O servidor FastMCP é montado sobre uma aplicação FastAPI e exposto via protocolo HTTP/SSE nos endpoints `/sse` e `/messages/`.
- **Autenticação:** O middleware `MCPAuthMiddleware` protege as rotas MCP, validando o token configurado em `API_BEARER_TOKEN` (tanto via cabeçalho `Authorization: Bearer <token>` quanto via query parameter `?token=...`).

### 4.2 Ferramentas Expostas (Tools)
- `check_availability`: Wrapper de `check_availability_internal`. Avalia se um slot de 1 hora cai em fim de semana ou feriado antes de consultar a agenda do Google Calendar, fornecendo um motivo detalhado em caso de indisponibilidade.
- `schedule_appointment`: Valida o tenant, registra o status da execução (EDW) no banco Supabase do cliente e insere a solicitação de agendamento na fila do Redis para ser processada assincronamente pelo worker.
- `send_whatsapp_message`: Normaliza o número de telefone em Python, obtém as credenciais Z-API no Supabase Master e efetua o envio da mensagem de texto de follow-up diretamente para o lead via Z-API, com rastreabilidade EDW sob o workflow `mcp_ligawhats`.


