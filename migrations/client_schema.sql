-- DDL para o Banco do Cliente (Cada ambiente isolado)

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

-- Índice obrigatório na chave estrangeira (conforme práticas recomendadas do Supabase)
CREATE INDEX IF NOT EXISTS idx_workflow_step_executions_execution_id ON workflow_step_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_workflow_step_executions_step_name ON workflow_step_executions(step_name);

-- 4. Políticas de Segurança (Row-Level Security)
ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_step_executions ENABLE ROW LEVEL SECURITY;

-- Políticas de acesso público 'anon' na tabela de Agendamentos (conforme decisão do usuário)
CREATE POLICY "Permitir inserções públicas anon em agendamentos" ON agendamentos
    FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY "Permitir leituras públicas anon em agendamentos" ON agendamentos
    FOR SELECT TO anon USING (true);

CREATE POLICY "Permitir atualizações públicas anon em agendamentos" ON agendamentos
    FOR UPDATE TO anon USING (true) WITH CHECK (true);

-- Políticas para Rastreabilidade (apenas service_role do backend edita, anon pode ler para checagem se necessário)
CREATE POLICY "Leitura anon das execuções" ON workflow_executions
    FOR SELECT TO anon USING (true);

CREATE POLICY "Acesso total de administrador em workflow_executions" ON workflow_executions
    TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Acesso total de administrador em workflow_step_executions" ON workflow_step_executions
    TO service_role USING (true) WITH CHECK (true);
