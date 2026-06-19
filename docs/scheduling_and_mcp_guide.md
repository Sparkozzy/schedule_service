# Guia de Agendamento de Reuniões e Servidores MCP — Mindflow

Este documento fornece uma análise técnica detalhada do ecossistema de agendamento de reuniões e dos servidores MCP (Model Context Protocol) da Mindflow, mapeados a partir dos workflows n8n documentados na pasta `FLOW ANALYZEER/n8n-workflows`. 

Além de descrever o funcionamento atual, este guia aponta as lacunas técnicas em relação às convenções de desenvolvimento orientado a eventos (EDW) da organização (definidas em [conventions.md](file:///home/ryanf/Schedule_service/docs/conventions.md)) e fornece especificações de alto nível para a migração para Python.

---

## 1. Visão Geral do Fluxo de Agendamento

O agendamento de reuniões na Mindflow é um processo dinâmico e interativo, normalmente liderado por um agente de voz de Inteligência Artificial (retido no **Retell AI**) ou por um chatbot de atendimento. Durante a conversa com o lead, o agente executa tarefas em tempo real para verificar dias úteis, consultar feriados, checar disponibilidade de horários e, por fim, consolidar a reunião na agenda do profissional.

Esse fluxo é mediado por um **Servidor MCP (Model Context Protocol)**, que expõe uma série de ferramentas (tools) estruturadas para o modelo de linguagem (LLM) que controla o agente de voz.

```mermaid
flowchart TD
    subgraph LLM["Agente de Voz / LLM (Retell AI)"]
        A["Interface de Voz / Chat"]
    end

    subgraph MCP["Servidor MCP n8n (mcp)"]
        B["MCP Trigger Webhook"]
        
        B -.->|"Tool: verifica_dia_da_semana"| T1["verifica_dia_da_semana"]
        B -.->|"Tool: verifica_feriado"| T2["verifica_feriado"]
        B -.->|"Tool: verifica_agenda"| T3["verifica_agenda"]
        B -.->|"Tool: agendar_reuniao"| T4["agendar_reuniao"]
    end

    subgraph SUB["Sub-workflows & Integrações"]
        T1 -->|"executeWorkflow"| SW1["verifica_dia_da_semana (n8n)<br/>(Subtrai 1 dia & nome do dia)"]
        T2 -->|"Google Calendar API"| GC1["Feriados Nacionais (Google Calendar)"]
        
        T3 -->|"executeWorkflow"| SW2["verifica_agenda_mindflow (n8n)<br/>(Fatiamento ≤ 1h / > 1h)"]
        SW2 -->|"freeBusy"| GC2["Diagnóstico Mindflow (Google Calendar)"]
        
        T4 -->|"executeWorkflow"| SW3["agenda_reuniao_mindflow (n8n)<br/>(Efetiva o slot)"]
        SW3 -->|"Criar Evento + Meet"| GC2
        SW3 -->|"Insert row"| SB["Leads_Mindflow (Supabase)"]
        SW3 -->|"POST send-text"| ZAPI["Z-API (WhatsApp Group Notification)"]
    end

    subgraph LLM_WA["Agente Whatsapp (Retell/Z-API)"]
        A2["Interface WhatsApp"]
    end

    subgraph MCP_WA["Servidor MCP Whatsapp (mcp_ligawhats)"]
        B2["MCP Trigger Webhook (f3260c85...)"]
        B2 -.->|"Tool: Mensagem_lead"| T5["Mensagem_lead"]
        T5 -->|"POST send-text"| ZAPI_LEAD["Z-API (WhatsApp Lead Direct Notification)"]
    end

    A -.->|Chamadas de Tool (SSE/HTTP)| B
    A2 -.->|Chamadas de Tool| B2
```

---

## 2. O Servidor MCP Principal (`mcp`)

O workflow principal de mediação é o [workflow-mcp.md](file:///home/ryanf/Schedule_service/FLOW%20ANALYZEER/n8n-workflows/workflow-mcp.md) (ID `d1Rj8b4TmPpIaZIVd116T`). Ele atua como um endpoint de recepção de chamadas MCP do agente de voz Retell e encaminha as requisições para ferramentas específicas.

*   **Trigger**: Inicia através de um `mcpTrigger` (LangChain) no endpoint público `/mcp/c9259be0-6d0a-4859-81a5-00f058f09a36`.
*   **Autenticação**: Configurada atualmente como **nenhuma** (`authentication: "none"`), o que expõe o endpoint de controle da agenda a chamadas externas não autenticadas (uma lacuna de segurança crítica).
*   **Encaminhamento**: Roteia dinamicamente os parâmetros gerados pelo LLM (`$fromAI`) para quatro ferramentas integradas ou sub-workflows.

---

## 3. Detalhamento Técnico das Ferramentas (Tools)

### 3.1. Tool `verifica_dia_da_semana`
*   **Objetivo**: Validar qual é o dia da semana de uma data específica para evitar que o agente tente propor ou agendar reuniões em finais de semana.
*   **Workflow Delegado**: [workflow-verifica-dia-da-semana.md](file:///home/ryanf/Schedule_service/FLOW%20ANALYZEER/n8n-workflows/workflow-verifica-dia-da-semana.md) (ID `TsLWZutNGAU6g3S4OEvfJ`).
*   **Dados de Entrada**: 
    *   `dia` (string) — Data formatada em `YYYY-MM-DD`.
*   **Funcionamento Técnico**: 
    1.  Recebe a data e a carrega em um objeto `Date` no JavaScript do n8n.
    2.  **Atenção (Lógica Especial)**: O script JS **subtrai 1 dia** da data de entrada (`data.setDate(data.getDate() - 1)`).
    3.  Formata o dia anterior como `YYYY-MM-DD` e resolve o nome do dia em português ("segunda-feira", "terça-feira", etc.) mapeando o índice retornado por `.getDay()`.
    4.  Retorna `{ dia, diaSemana }` do dia anterior calculado.
*   **Pontos de Atenção**:
    *   **Lógica de Subtração**: A subtração de 1 dia é provavelmente utilizada pelo disparador de outbound para checar se "ontem foi um dia útil", mas pode causar confusão se o agente de voz chamar essa tool esperando o dia da semana da data que ele enviou.
    *   **Timezone Shift**: Lidar com `new Date("YYYY-MM-DD")` no runtime JS sem especificar fuso horário pode causar desvios de fuso (off-by-one) dependendo de onde o container do n8n está hospedado.

---

### 3.2. Tool `verifica_feriado`
*   **Objetivo**: Detectar se uma determinada data cai em feriado nacional brasileiro.
*   **Workflow Delegado**: Executado diretamente na branch do workflow `mcp` utilizando o nó `googleCalendarTool`.
*   **Dados de Entrada**:
    *   `Before` (string ISO 8601) — Janela de tempo de consulta fornecida pelo LLM.
*   **Funcionamento Técnico**:
    1.  Consome a API oficial do Google Calendar usando credenciais OAuth2 integradas no n8n.
    2.  Realiza a operação `event.getAll` apontando para o calendário público de feriados do Brasil: `pt-br.brazilian#holiday@group.v.calendar.google.com`.
    3.  Se a chamada retornar eventos de feriado na janela, o LLM recebe o nome do feriado e pode sugerir outro horário ao lead.
*   **Pontos de Atenção**:
    *   **Configuração Incorreta no n8n**: O campo `timeMin` no nó n8n está configurado com a string estática `"Data final"`, o que representa um provável erro de parametrização. Na prática, a consulta deve ser feita usando a data de início da janela.

---

### 3.3. Tool `verifica_agenda`
*   **Objetivo**: Consultar os horários livres na agenda de diagnóstico do profissional antes de sugerir ou confirmar horários com o lead.
*   **Workflow Delegado**: [workflow-verifica-agenda-mindflow.md](file:///home/ryanf/Schedule_service/FLOW%20ANALYZEER/n8n-workflows/workflow-verifica-agenda-mindflow.md) (ID `N2_TreHsY95DtigohLy3i`).
*   **Dados de Entrada**:
    *   `Data inicial` (string ISO 8601 com fuso horário).
    *   `Data final` (string ISO 8601 com fuso horário).
*   **Funcionamento Técnico**:
    1.  **Cálculo da Duração**: Um nó de código JavaScript calcula se a diferença entre o início e o fim é maior do que 1 hora (`intervaloMaiorQueUmaHora`).
    2.  **Ramo ≤ 1h (Slot Único)**: Se o intervalo for menor ou igual a uma hora, chama diretamente a API do Google Calendar (`freebusy/availability`) para o ID de calendário da Mindflow. Retorna `{ available: boolean }`.
    3.  **Ramo > 1h (Múltiplos Slots)**: Se o intervalo for de várias horas (ex: das 09h às 19h):
        *   Um script JavaScript fatia a janela em sub-intervalos (slots) de 1 hora.
        *   Usa um loop interno n8n (`SplitInBatches` com tamanho de lote = 1) para consultar a disponibilidade do calendário para cada slot sequencialmente.
        *   Recombina as saídas em uma lista contendo a situação de cada horário (`[{ Data, available }]`).
*   **Pontos de Atenção**:
    *   **Latência por Loop Sequencial**: O n8n executa a verificação de cada slot de forma serial (um após o outro). Se o LLM pedir para checar o dia inteiro (10 slots de 1h), serão feitas 10 requisições sequenciais à API do Google Calendar, gerando alta latência na ligação de voz.

---

### 3.4. Tool `agendar_reuniao`
*   **Objetivo**: Efetivar o agendamento no Google Calendar, notificar a equipe e marcar o status no Supabase.
*   **Workflow Delegado**: [workflow-agenda-reuniao-mindflow.md](file:///home/ryanf/Schedule_service/FLOW%20ANALYZEER/n8n-workflows/workflow-agenda-reuniao-mindflow.md) (ID `ELqE1Mbt9DLmAb6wc5M3e`).
*   **Dados de Entrada**:
    *   `Numero` (string) — Telefone do lead (formato E.164).
    *   `Data/hora` (string ISO 8601) — Slot de início escolhido.
    *   `Email` (string) — E-mail do lead.
    *   `Resumo ` (string, nota-se o espaço no nome do campo no n8n) — Resumo dos desafios do lead anotados pelo agente.
    *   `Titulo` (string) — Nome para o evento (Ex: "Atendimento - Nome do Lead").
*   **Funcionamento Técnico**:
    1.  **Tratamento de Timezone**: O nó de código JS converte o input de data/hora e aplica um offset manual de Brasília (-3h).
    2.  **Criação do Evento (Google Calendar)**: Cria um evento no calendário de ID `c_0c05c1269e9b...` ("Diagnóstico Mindflow"). O evento dura 1 hora. Adiciona automaticamente uma videoconferência do Google Meet (`hangoutsMeet`) e inclui convidados internos fixos (Gabriel, Renato e equipe de marketing), além do e-mail do lead.
    3.  **Registro no Banco (Supabase)**: Efetua um `INSERT` na tabela `Leads_Mindflow` registrando a data e hora do agendamento e definindo a coluna `Etapa CRM` como `"Reunião marcada"`.
    4.  **Notificação WhatsApp (Z-API)**: Envia uma requisição POST assíncrona para a API da Z-API enviando os detalhes da reunião e o link do Meet para o grupo interno do time (ID `120363424280785137-group`).
*   **Pontos de Atenção**:
    *   **Inconsistência de Timezone**: Há um duplo ajuste de timezone (um nó JS subtrai 3h e depois o Calendar cria o evento adicionando 3h/4h por cima com fuso configurado para `America/New_York` em algumas execuções). Isso é uma fonte de falhas críticas de fuso.
    *   **Duplicação de Registros (Supabase)**: O nó do Supabase executa um `INSERT` direto. Se o lead já existir na tabela, o agendamento criará um registro duplicado em vez de atualizar a linha existente do lead.
    *   **Exposição de Secrets**: Credenciais de API da Z-API (`INSTANCE_ID` e tokens) e o ID do grupo do WhatsApp estão embutidos diretamente em texto plano no JSON do workflow n8n.
    *   **Disparo Paralelo sem Confirmação**: O envio de notificação pelo WhatsApp ocorre em paralelo com a criação do calendário. Se a API do Google Calendar falhar (como visto nas execuções recentes de erro), o WhatsApp do grupo é notificado de qualquer maneira.

---

## 4. O Servidor MCP WhatsApp Helper (`mcp_ligawhats`)

Existe um segundo servidor MCP documentado em [workflow-mcp-ligawhats.md](file:///home/ryanf/Schedule_service/FLOW%20ANALYZEER/n8n-workflows/workflow-mcp-ligawhats.md) (ID `zSZlwlPC8SJy62CgLs3Nq`).

*   **Trigger**: Inicia em `/mcp/f3260c85-fe8f-4ddb-9969-6b29e5136273`.
*   **Tool Exposta**: `Mensagem_lead`.
*   **Objetivo**: Enviar uma mensagem de texto direta para o WhatsApp do lead via Z-API se ele demonstrar interesse em fechar o pedido durante a ligação.
*   **Parâmetros**: Recebe `phone` (telefone formatado) e `message` (mensagem do agente).
*   **Divergência**: Também possui secrets hardcoded no JSON e opera sem autenticação no gatilho MCP. A normalização de telefone é delegada ao prompt do LLM em vez de validação de código determinístico.

---

## 5. Lacunas Críticas e Recomendações para Migração EDW (Python)

A migração de todo esse cluster de agendamento do n8n para o ecossistema Python sob a convenção EDW (definida em [conventions.md](file:///home/ryanf/Schedule_service/docs/conventions.md)) apresenta excelentes oportunidades de otimização de latência, segurança e manutenibilidade.

### 5.1. Rastreabilidade Obrigatória
Os fluxos n8n não possuem propagação dos campos `execution_id`, `from_workflow` e `workflow_id`.
*   **Ação**: Na reimplementação com FastAPI/FastMCP, as assinaturas e schemas Pydantic de entrada **devem exigir** esses metadados. Cada operação executada pelo worker ou servidor MCP deve registrar o seu estado mestre em `workflow_executions` e passos individuais em `workflow_step_executions` via `run_step_with_retry`.

### 5.2. Segurança dos Webhooks e Servidores MCP
*   **Ação**: Implementar autenticação via Bearer token (verificado via middleware FastAPI) no servidor FastMCP. Mudar a configuração de `authentication: none` para chave obrigatória. Todos os secrets de tokens do Z-API e chaves de acesso devem ser movidos obrigatoriamente para variáveis de ambiente `.env` expostas via Easypanel.

### 5.3. Otimização de Concorrência (Slots de Horário)
*   **Ação**: Substituir o loop sequencial (`SplitInBatches`) da ferramenta `verifica_agenda` por chamadas assíncronas concorrentes utilizando `asyncio.gather` no Python. Se precisarmos consultar 10 slots diferentes de 1h, o Python disparará as 10 requisições HTTP paralelas via `httpx.AsyncClient()`, reduzindo o tempo de espera do agente Retell de segundos para milissegundos.

### 5.4. Normalização Determinística de Datas e Telefones
*   **Ação**:
    *   Remover scripts manuais de timezone em JS que somam/subtraem horas secas. Utilizar a biblioteca `zoneinfo` do Python e as funções padrão do projeto (`parse_iso_to_br`, `get_br_now`) para normalizar consistentemente no fuso de Brasília (`America/Sao_Paulo`). Rejeitar qualquer data naive com `400 Bad Request`.
    *   Remover o cálculo do dia de semana feito no n8n. Transformar o workflow `verifica_dia_da_semana` em uma **função auxiliar pura (helper)** síncrona em Python (`utils/datetime_helpers.py`), evitando a criação de endpoints HTTP adicionais para uma conversão matemática simples de data.
    *   Substituir a formatação de telefone delegada ao prompt do LLM no Z-API por expressões regulares determinísticas (`re`) em Python antes de submeter ao gateway.

### 5.5. Lógica de Upsert de CRM
*   **Ação**: No step de inserção de status no banco de dados (`agenda_reuniao_mindflow_upsert_lead_status`), utilizar o método `upsert` do SDK do Supabase baseado na chave única do lead (`Email` ou `Numero`), prevenindo registros duplicados na tabela `Leads_Mindflow`.

### 5.6. Acoplamento de Notificações
*   **Ação**: No worker ARQ da migração, orquestrar a notificação WhatsApp como um passo posterior ao sucesso da criação do evento na API do Google Calendar. Em caso de falha no Calendar, o workflow principal falha e a equipe não recebe uma notificação falsa de sucesso no WhatsApp.

---

## 6. Proposta de Schemas Pydantic para a Migração

Abaixo estão os contratos de dados recomendados para os futuros endpoints/ferramentas em Python:

```python
# schemas.py
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from uuid import UUID
from typing import Optional, List

class TraceableBase(BaseModel):
    workflow_id: str = Field(..., description="ID fixo do workflow")
    from_workflow: str = Field(..., description="Nome do workflow chamador")
    execution_id: UUID = Field(..., description="UUID único da execução")

# Input para a ferramenta de verificar disponibilidade de agenda
class VerificaAgendaInput(TraceableBase):
    data_inicial: datetime = Field(..., description="ISO 8601 com timezone offset")
    data_final: datetime = Field(..., description="ISO 8601 com timezone offset")

class SlotDisponibilidade(BaseModel):
    data: datetime
    available: bool

class VerificaAgendaOutput(BaseModel):
    disponivel: bool
    slots: List[SlotDisponibilidade]

# Input para a ferramenta de agendar reunião efetivamente
class AgendarReuniaoInput(TraceableBase):
    numero: str = Field(..., description="Telefone do lead no formato E.164")
    data_hora: datetime = Field(..., description="Data/hora inicial com timezone offset")
    email: EmailStr = Field(..., description="E-mail do lead")
    resumo: str = Field(..., description="Anotações dos desafios do lead")
    titulo: str = Field(..., description="Título do evento da reunião")

class AgendarReuniaoOutput(BaseModel):
    event_id: str
    meet_link: str
    status: str  # "scheduled" ou "failed"
```
