# Guia de Configuração e Onboarding de Novo Cliente (Multi-Tenant)

Este documento descreve o processo completo para o onboarding de novos clientes na plataforma de agendamento multi-tenant da Mindflow. Ele serve como referência para obter e configurar as credenciais no banco de dados **Supabase Master** e estruturar o ambiente dedicado (**Supabase do Cliente**).

---

## 1. Mapeamento das Configurações do Cliente (Master)

Para integrar o novo cliente no fluxo de execução, insira um registro na tabela `client_configurations` do **Supabase Master**. Abaixo estão detalhadas todas as colunas necessárias:

| Coluna | Tipo | Obrigatório | O que é? | Onde/Como obter? |
| :--- | :--- | :--- | :--- | :--- |
| **`client_id`** *(PK)* | `TEXT` | **Sim** | Identificador único amigável do cliente (usado na API e logs). | Defina um padrão curto em minúsculas e separado por hífen. Exemplo: `cliente-a`, `empresa-exemplo`. |
| **`client_name`** | `TEXT` | **Sim** | Nome legível corporativo do cliente. | Razão social ou nome fantasia fornecido pelo cliente. Exemplo: `Empresa Exemplo S.A.`. |
| **`supabase_url`** | `TEXT` | **Sim** | URL de API do projeto Supabase dedicado do cliente. | **Painel do Supabase do Cliente:** Vá em *Project Settings* > *API* > *Project URL*. |
| **`supabase_service_key`** | `TEXT` | **Sim** | Chave privada administrativa (`service_role`) para escrita e leitura sem barreiras de RLS pelo backend. | **Painel do Supabase do Cliente:** Vá em *Project Settings* > *API* > *Project API Keys* > Copie o token de **`service_role`** (oculto por padrão). |
| **`supabase_anon_key`** | `TEXT` | **Sim** | Chave pública (`anon`) para acesso restrito. | **Painel do Supabase do Cliente:** Vá em *Project Settings* > *API* > *Project API Keys* > Copie o token de **`anon` / `public`**. |
| **`google_calendar_id`** | `TEXT` | **Sim** | ID da agenda do Google Calendar onde as reuniões serão agendadas. | **Google Calendar do Cliente:** Vá nas configurações da agenda em *Configurações e Compartilhamento* > *Integrar Agenda* > Copie o **ID da agenda** (pode ser o e-mail do cliente ou um hash como `xyz@group.calendar.google.com`). |
| **`zapi_instance_id`** | `TEXT` | Não (Opcional) | ID da instância do WhatsApp contratada na Z-API para notificações. | **Painel da Z-API:** ID da instância configurada para disparos de WhatsApp do cliente. |
| **`zapi_client_token`** | `TEXT` | Não (Opcional) | Token de autenticação da instância Z-API (usado na URL). | **Painel da Z-API:** Token de segurança gerado para a instância correspondente. |
| **`zapi_security_token`** | `TEXT` | Não (Opcional) | Token de segurança da instância Z-API (enviado via header). | **Painel da Z-API:** Token de segurança/client-token gerado pela Z-API. |
| **`zapi_group_id`** | `TEXT` | Não (Opcional) | ID do grupo do WhatsApp onde as notificações internas de agendamento serão enviadas. | Obtido executando um fetch de grupos via Z-API ou coletando o ID do grupo criado para o time. |

---

## 2. Passo a Passo do Setup no Supabase do Cliente

Cada cliente possui seu próprio Supabase com ambiente isolado. Siga estes passos para configurá-lo:

### 2.1 Criar o Projeto no Supabase
1. Acesse o painel administrativo do [Supabase](https://supabase.com).
2. Clique em **"New Project"** e selecione a Organização correspondente.
3. Preencha os detalhes do projeto:
   - **Name:** Nome do cliente (ex: `Mindflow - Cliente A`).
   - **Database Password:** Gere uma senha forte e armazene-a em local seguro.
   - **Region:** Selecione a região mais próxima dos seus serviços (ex: `sa-east-1` São Paulo).
4. Clique em **"Create new project"** e aguarde alguns minutos até a inicialização ser concluída.

### 2.2 Configurar o Schema e Rodar as Migrações
O banco de dados do cliente precisa conter a estrutura de tabelas de agendamento e rastreabilidade EDW.

1. No menu lateral esquerdo do Supabase, clique em **"SQL Editor"** (ícone `>_`).
2. Clique em **"New Query"** para abrir uma aba em branco.
3. Copie e cole o DDL contido em [client_schema.sql](file:///home/ryanf/Schedule_service/migrations/client_schema.sql):

```sql
-- Habilitar a extensão uuid-ossp caso não esteja habilitada
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Tabela de Agendamentos
CREATE TABLE IF NOT EXISTS agendamentos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    nome TEXT NOT NULL,
    email TEXT NOT NULL,
    numero TEXT NOT NULL,
    canal TEXT NOT NULL CHECK (canal IN ('whats', 'ligacao')),
    data_agendamento TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'agendado' CHECK (status IN ('agendado', 'cancelado', 'realizado')),
    detalhes TEXT,
    google_event_id TEXT,
    calendar_id TEXT,
    execution_id UUID,
    agent_id TEXT
);

-- Índices para otimização de busca na tabela agendamentos
CREATE INDEX IF NOT EXISTS idx_agendamentos_numero ON agendamentos(numero);
CREATE INDEX IF NOT EXISTS idx_agendamentos_data_agendamento ON agendamentos(data_agendamento);
CREATE INDEX IF NOT EXISTS idx_agendamentos_agent_id ON agendamentos(agent_id);

-- 2. Tabela de Rastreabilidade EDW: workflow_executions
CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY,
    workflow_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED')),
    input_data JSONB,
    output_data JSONB,
    error_details TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_event_id VARCHAR
);

-- Índices para workflow_executions
CREATE INDEX IF NOT EXISTS idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_created_at ON workflow_executions(created_at);

-- 3. Tabela de Rastreabilidade EDW: workflow_step_executions
CREATE TABLE IF NOT EXISTS workflow_step_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    step_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
    attempt INT NOT NULL DEFAULT 1,
    input_data JSONB,
    output_data JSONB,
    error_details TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_step_executions_execution_id ON workflow_step_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_step_executions_step_name ON workflow_step_executions(step_name);

-- 4. Políticas de Segurança (Row-Level Security)
ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_step_executions ENABLE ROW LEVEL SECURITY;

-- Políticas de acesso público 'anon' na tabela de Agendamentos
CREATE POLICY "Permitir inserções públicas anon em agendamentos" ON agendamentos
    FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY "Permitir leituras públicas anon em agendamentos" ON agendamentos
    FOR SELECT TO anon USING (true);

CREATE POLICY "Permitir atualizações públicas anon em agendamentos" ON agendamentos
    FOR UPDATE TO anon USING (true) WITH CHECK (true);

-- Políticas para Rastreabilidade
CREATE POLICY "Leitura anon das execuções" ON workflow_executions
    FOR SELECT TO anon USING (true);

CREATE POLICY "Acesso total de administrador em workflow_executions" ON workflow_executions
    TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Acesso total de administrador em workflow_step_executions" ON workflow_step_executions
    TO service_role USING (true) WITH CHECK (true);
```

4. Clique em **"Run"** para executar as DDLs.
5. Verifique no menu lateral **"Table Editor"** se as tabelas e políticas de Row-Level Security (RLS) foram configuradas com sucesso.

---

## 3. Integração com a Agenda do Google Calendar

Para que o worker do ARQ possa consultar a disponibilidade de slots de horário e realizar os agendamentos automáticos na agenda do cliente, existem duas formas de configurar o Google Calendar. 

Isso ocorre porque, conforme o código em [config.py](file:///home/ryanf/Schedule_service/config.py#L75-L107), a API do Google Calendar é instanciada e autenticada **diretamente com as credenciais da conta centralizadora `ryanferrari@iatize-ia.com`**. Portanto, ela possui permissões totais sobre qualquer agenda criada nessa conta.

---

### Alternativa A: Criar a agenda diretamente na conta `ryanferrari@iatize-ia.com` (Recomendado se o cliente tiver restrições de TI)
Em vez de pedir para o cliente criar a agenda e compartilhar com você (o que pode falhar se as políticas de segurança do Google Workspace dele bloquearem compartilhamento externo), **você mesmo cria a agenda** dentro da conta centralizadora.

1. Acesse o [Google Calendar](https://calendar.google.com) usando a conta **`ryanferrari@iatize-ia.com`**.
2. No menu lateral esquerdo, ao lado de "Outras agendas", clique no botão **`+`** > **"Criar nova agenda"**.
3. Defina o nome como a empresa/nome do cliente (ex: `Agendamentos - Cliente X`) e clique em **"Criar agenda"**.
4. Nas configurações da agenda recém-criada, vá em **"Compartilhar com pessoas ou grupos específicos"** e adicione o e-mail do cliente, concedendo a permissão **"Ver todos os detalhes dos eventos"** (ou **"Fazer alterações em eventos"**, se ele precisar editar manualmente).
5. Vá na seção **"Integrar agenda"** e copie o **ID da agenda** (ex: `c_xxxxxxxxxxxxxxxxxxxxxxxxxx@group.calendar.google.com`). Este será o `google_calendar_id` que você salvará na tabela `client_configurations` do Master.

*Vantagem:* A API já terá acesso total automático à agenda por ser a proprietária dela, eliminando qualquer risco de erro de permissão (403 Forbidden ou 404 Not Found) ao criar os eventos.

---

### Alternativa B: O cliente cria a agenda e compartilha com você
Caso o cliente faça questão de usar uma agenda própria dentro do domínio corporativo dele:

1. Solicite que o cliente acesse o [Google Calendar](https://calendar.google.com) com a conta dele.
2. Nas configurações da agenda dele, acesse **"Compartilhar com pessoas ou grupos específicos"** > **"Adicionar pessoas"**.
3. Adicione o e-mail centralizador: **`ryanferrari@iatize-ia.com`**.
4. Configure as permissões como **"Fazer alterações e gerenciar compartilhamento"** (ou no mínimo **"Fazer alterações em eventos"**).
5. Peça para o cliente fornecer o **ID da agenda** localizado em **"Integrar agenda"** (se for a principal da conta, será o próprio e-mail dele).

> [!WARNING]
> Se o cliente utilizar uma conta corporativa (Google Workspace) e a opção de permissão de escrita para externos estiver desabilitada por políticas de TI organizacional, a Alternativa B falhará. Nesses casos, use obrigatoriamente a **Alternativa A**.

---

## 4. Configuração da Z-API (WhatsApp)

A Z-API é utilizada para enviar notificações automáticas de status de agendamentos para o time interno e mensagens transacionais via WhatsApp. Caso o cliente utilize essa funcionalidade, configure conforme abaixo:

### 4.1 Obter o `zapi_instance_id` e `zapi_client_token`
1. Acesse o painel administrativo da [Z-API](https://painel.z-api.io).
2. Na página principal ou na listagem de instâncias, localize a instância vinculada ao número de WhatsApp do cliente.
3. Copie o **ID da Instância** (uma string alfanumérica curta). Esse será o `zapi_instance_id`.
4. Na aba de credenciais ou diretamente no Dashboard da instância, localize e copie o **Client Token** (token de segurança). Esse será o `zapi_client_token`.

### 4.2 Como Obter o `zapi_group_id` (JID do Grupo)
Para que as notificações de agendamento sejam encaminhadas para o grupo interno correto do time comercial ou de operações, siga uma destas alternativas:

* **Alternativa A (Via Logs de Webhook - Recomendada):**
  1. Crie o grupo no WhatsApp e adicione o número conectado à instância da Z-API como administrador do grupo.
  2. Envie qualquer mensagem dentro desse grupo utilizando seu celular pessoal.
  3. No painel da Z-API, acesse a aba **"Webhooks"** ou o log de requisições recebidas da sua instância.
  4. Localize a mensagem que você enviou. No payload JSON do evento, o campo **`phone`** ou **`chatId`** conterá o ID do grupo (normalmente no formato `120363XXXXXXXXXXXX@g.us`). Copie esse valor completo.

* **Alternativa B (Via Chamada de API/REST):**
  1. Utilizando uma ferramenta de teste de requisições (como Postman ou curl), faça uma requisição `GET` para listar as conversas ativas da instância:
     ```bash
     curl -X GET "https://api.z-api.io/instances/SUA_INSTANCIA/token/SEU_TOKEN/chats"
     ```
  2. Procure na resposta pelo objeto correspondente ao nome do grupo que você criou. O campo contendo `@g.us` é o ID que você deve preencher na coluna `zapi_group_id`.

---

## 5. Registro no Banco Master (Exemplo SQL)

Execute este comando INSERT na tabela `client_configurations` do Supabase Master para concluir o cadastro:

```sql
INSERT INTO client_configurations (
    client_id,
    client_name,
    supabase_url,
    supabase_service_key,
    supabase_anon_key,
    google_calendar_id,
    zapi_instance_id,
    zapi_client_token,
    zapi_security_token,
    zapi_group_id
) VALUES (
    'nome-do-cliente',                     -- client_id (minúsculas, sem espaço)
    'Nome Oficial da Empresa',             -- client_name
    'https://project-id.supabase.co',      -- supabase_url
    'service-role-key-secreta',            -- supabase_service_key
    'anon-key-publica',                    -- supabase_anon_key
    'calendar-id@group.calendar.google.com',-- google_calendar_id
    'zapi-instance-id-opcional',           -- zapi_instance_id (opcional)
    'zapi-token-opcional',                 -- zapi_client_token (opcional)
    'zapi-security-token-opcional',        -- zapi_security_token (opcional)
    'group-id-opcional'                    -- zapi_group_id (opcional)
);
```

---

## 6. ⚠️ Validações Finais antes de rodar o Workflow

1. **Permissão do Calendar:** Confirme que a agenda do cliente de fato compartilhou o acesso de edição com `ryanferrari@iatize-ia.com`.
2. **Formato do `client_id`:** O ID deve ser idêntico ao valor enviado pelos webhooks nos payloads (ex: campo `client_id`). O sistema faz a busca exata em `get_client_config(client_id)`.
3. **Blacklists e Controles:** Se o novo cliente usar blacklist ou buffers customizados, certifique-se de preencher as chaves corretas e validar se o schema está sincronizado.

