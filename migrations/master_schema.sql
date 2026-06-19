-- DDL para o Banco Master (Mindflow)
CREATE TABLE IF NOT EXISTS client_configurations (
    client_id TEXT PRIMARY KEY,
    client_name TEXT NOT NULL,
    supabase_url TEXT NOT NULL,
    supabase_service_key TEXT NOT NULL,
    supabase_anon_key TEXT NOT NULL,
    google_calendar_id TEXT NOT NULL,
    zapi_instance_id TEXT,
    zapi_client_token TEXT,
    zapi_group_id TEXT,
    crm_config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ativar RLS no banco Master
ALTER TABLE client_configurations ENABLE ROW LEVEL SECURITY;

-- Como o backend lê essa tabela usando a service_role key, 
-- não são necessárias políticas adicionais públicas para leitura direta do backend.
-- Se for necessário expor para visualização ou edição de administradores:
CREATE POLICY "Acesso total para service_role no Master" ON client_configurations
    USING (true) WITH CHECK (true);
