import os
import uuid
import json
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from arq import create_pool
from arq.connections import RedisSettings
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings

from config import settings, get_client_config, get_supabase_client
from schemas import AgendarReuniaoRequest
from utils.tracing import start_workflow_execution
from utils.availability import check_availability_internal

# 1. Middleware de Autenticação para proteger os endpoints MCP externos
class MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Valida o token apenas nas rotas do protocolo MCP
        if request.url.path in ("/sse", "/messages"):
            auth_header = request.headers.get("Authorization")
            token = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
            if not token:
                token = request.query_params.get("token")
                
            if not token or token != settings.API_BEARER_TOKEN:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Não autorizado. Token MCP inválido ou ausente."}
                )
        return await call_next(request)

# 2. Gerenciador de ciclo de vida (lifespan) do FastMCP para instanciar o pool do Redis/ARQ
@asynccontextmanager
async def mcp_lifespan(mcp_instance: FastMCP):
    # Substituir '#' por '%23' por compatibilidade com Easypanel
    redis_url = settings.REDIS_URL.replace("#", "%23")
    redis_settings = RedisSettings.from_dsn(redis_url)
    redis_pool = None
    try:
        redis_pool = await create_pool(redis_settings)
    except Exception as e:
        print(f"Aviso: Não foi possível conectar ao Redis ({e}). A tool 'schedule_appointment' não estará totalmente operacional.")
    
    yield {"redis_pool": redis_pool}
    
    if redis_pool:
        await redis_pool.close()


# 3. Inicialização do FastMCP
mcp = FastMCP(
    "scheduling_mcp",
    lifespan=mcp_lifespan,
    instructions="Serviço de agendamento multi-tenant integrado com Google Calendar e Supabase.",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
)

# 4. Ferramentas (Tools) do MCP
@mcp.tool(
    name="check_availability",
    annotations={
        "title": "Verificar Disponibilidade de Agenda",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True
    }
)
async def check_availability(
    client_id: str,
    data_inicial: datetime,
    data_final: datetime
) -> str:
    """
    Verifica se existem slots de 1 hora disponíveis na agenda do cliente no período informado.
    Antes de consultar o Google Calendar do cliente, verifica se cai em finais de semana ou feriados nacionais do Brasil.
    
    Args:
        client_id: ID do cliente cadastrado no Supabase Master (ex: 'cliente-a').
        data_inicial: Data/hora de início da janela de busca (ISO 8601 com fuso horário).
        data_final: Data/hora de fim da janela de busca (ISO 8601 com fuso horário).
        
    Returns:
        JSON string contendo o status de disponibilidade geral e a lista detalhada de slots.
    """
    try:
        res = await check_availability_internal(client_id, data_inicial, data_final)
        return res.model_dump_json(indent=2)
    except ValueError as ve:
        return json.dumps({"error": str(ve)}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Erro interno ao consultar disponibilidade: {str(e)}"}, indent=2)


@mcp.tool(
    name="schedule_appointment",
    annotations={
        "title": "Agendar Reunião",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False
    }
)
async def schedule_appointment(
    client_id: str,
    nome: str,
    email: str,
    numero: str,
    canal: str,
    data_agendamento: datetime,
    titulo: Optional[str] = None,
    resumo: Optional[str] = None,
    agent_id: Optional[str] = None,
    ctx: Context = None
) -> str:
    """
    Registra uma solicitação de agendamento de reunião de forma assíncrona.
    Valida as informações, inicia o fluxo de rastreabilidade (PENDING) no Supabase do cliente
    e envia o processamento pesado de agendamento (Google Calendar, WhatsApp) para a fila Redis.
    
    Args:
        client_id: ID do cliente cadastrado no Supabase Master (ex: 'cliente-a').
        nome: Nome completo do lead.
        email: E-mail do lead.
        numero: Telefone de contato no formato internacional E.164 (ex: '+5548996027108').
        canal: Canal de origem do contato (deve ser 'whats' ou 'ligacao').
        data_agendamento: Data e hora desejadas para o agendamento (ISO 8601 com fuso horário).
        titulo: Título opcional para o evento do calendário.
        resumo: Resumo opcional dos desafios discutidos com o lead.
        agent_id: ID opcional do agente de IA que originou o agendamento.
        
    Returns:
        JSON string contendo os detalhes do status do agendamento aceito e o ID da execução para rastreio.
    """
    if not ctx:
        return json.dumps({"error": "Contexto do MCP inválido ou não fornecido."}, indent=2)
        
    redis_pool = ctx.request_context.lifespan_context.get("redis_pool")
    if not redis_pool:
        return json.dumps({"error": "Fila Redis de segundo plano (ARQ) indisponível."}, indent=2)
        
    # Reutiliza o validador Pydantic do request do webhook para normalização
    try:
        payload = AgendarReuniaoRequest(
            client_id=client_id,
            nome=nome,
            email=email,
            numero=numero,
            canal=canal,
            data_agendamento=data_agendamento,
            resumo=resumo,
            titulo=titulo,
            agent_id=agent_id
        )
    except Exception as ve:
        return json.dumps({"error": f"Dados de agendamento inválidos: {str(ve)}"}, indent=2)
        
    execution_id = uuid.uuid4()
    
    try:
        # 1. Valida se o cliente existe no Supabase Master
        get_client_config(payload.client_id)
        
        # 2. Conecta ao Supabase do Cliente correspondente
        client_supabase = get_supabase_client(payload.client_id)
        
        # 3. Cria registro mestre de rastreabilidade na tabela workflow_executions do cliente
        input_data = payload.model_dump()
        input_data["data_agendamento"] = payload.data_agendamento.isoformat()
        
        await start_workflow_execution(
            supabase_client=client_supabase,
            workflow_name="scheduling_workflow",
            input_data=input_data,
            execution_id=execution_id
        )
        
        # 4. Enfileira o processamento pesado no ARQ
        await redis_pool.enqueue_job(
            "schedule_appointment_job",
            client_id=payload.client_id,
            execution_id=str(execution_id),
            appointment_data=input_data
        )
        
        return json.dumps({
            "status": "Accepted",
            "execution_id": str(execution_id),
            "message": "Agendamento recebido e enviado para processamento em background."
        }, indent=2)
        
    except ValueError as ve:
        return json.dumps({"error": str(ve)}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Falha interna ao iniciar agendamento: {str(e)}"}, indent=2)

# 5. Aplicação FastAPI principal que protege e expõe os endpoints do FastMCP
app = FastAPI(
    title="Mindflow Secure MCP Service",
    description="Interface Model Context Protocol protegida para agentes externos de IA",
    version="1.0.0"
)

# Adiciona o middleware de proteção
app.add_middleware(MCPAuthMiddleware)

@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    return {"status": "ok", "service": "secure-mcp-server"}

# Monta a aplicação Starlette interna do FastMCP na raiz
app.mount("/", mcp.sse_app())

if __name__ == "__main__":
    # Se executado diretamente via linha de comando, roda em modo stdio (padrão)
    # permitindo testes locais e depuração com o MCP Inspector:
    # npx @modelcontextprotocol/inspector python mcp_server.py
    mcp.run()

