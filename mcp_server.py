import os
import uuid
import json
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from arq import create_pool
from arq.connections import RedisSettings
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings

from config import settings, get_client_config, get_supabase_client
from schemas import AgendarReuniaoRequest
from utils.tracing import start_workflow_execution, update_workflow_status, run_step_with_retry
from utils.availability import check_availability_internal
from utils.phone import normalize_phone_to_12_digits

# 1. Middleware de Autenticação para proteger os endpoints MCP externos (usando ASGI puro para evitar bug de StreamingResponse do BaseHTTPMiddleware)
from urllib.parse import parse_qs

class MCPAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        normalized_path = path.rstrip("/")
        if normalized_path in ("/sse", "/messages", "/mcp"):
            # Obter cabeçalhos
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8")
            token = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
            
            if not token:
                # Obter parâmetros de consulta (query parameters)
                query_string = scope.get("query_string", b"").decode("utf-8")
                params = parse_qs(query_string)
                token_list = params.get("token")
                if token_list:
                    token = token_list[0]

            if not token or token != settings.API_BEARER_TOKEN:
                # Retorna 401 Unauthorized diretamente
                response_body = b'{"detail": "N\xc3\xa3o autorizado. Token MCP inv\xc3\xa1lido ou ausente."}'
                await send({
                    "type": "http.response.start",
                    "status": status.HTTP_401_UNAUTHORIZED,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode("utf-8"))
                    ]
                })
                await send({
                    "type": "http.response.body",
                    "body": response_body,
                    "more_body": False
                })
                return

        await self.app(scope, receive, send)


# 2. Gerenciador de ciclo de vida (lifespan) do FastMCP para instanciar o pool do Redis/ARQ
@asynccontextmanager
async def mcp_lifespan(mcp_instance: FastMCP):
    # Substituir '#' por '%23' por compatibilidade com Easypanel
    redis_url = settings.REDIS_URL.replace("#", "%23")
    redis_settings = RedisSettings.from_dsn(redis_url)
    redis_pool = None
    try:
        redis_pool = await create_pool(redis_settings)
        # Sincroniza o pool do Redis com o módulo main para funcionamento dos webhooks
        import main
        main.redis_pool = redis_pool
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

@mcp.tool(
    name="send_whatsapp_message",
    annotations={
        "title": "Enviar Mensagem de WhatsApp para Lead",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False
    }
)
async def send_whatsapp_message(
    client_id: str,
    phone: str,
    message: str,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Envia uma mensagem de texto (follow-up de fechamento do pedido) via WhatsApp usando a gateway Z-API.
    Executa a normalização do telefone e registra logs de auditoria no padrão EDW.
    
    Args:
        client_id: ID do cliente cadastrado no Supabase Master (ex: 'cliente-a').
        phone: Número do lead (ex: '+5541995252559' ou '554195252559').
        message: Texto da mensagem de confirmação para mandar para o lead.
        execution_id: ID único de execução opcional para rastreabilidade (UUID string).
        agent_id: ID opcional do agente de IA que originou o disparo.
        
    Returns:
        JSON string contendo o resultado do envio ou erro.
    """
    # 1. Gerar/validar o execution_id
    import uuid
    exec_uuid = None
    if execution_id:
        try:
            exec_uuid = uuid.UUID(execution_id)
        except ValueError:
            pass
    if not exec_uuid:
        exec_uuid = uuid.uuid4()
        
    try:
        # 2. Obter cliente Supabase do Cliente
        supabase_client = get_supabase_client(client_id)
    except Exception as e:
        return json.dumps({"error": f"Cliente '{client_id}' não configurado ou Supabase inválido: {str(e)}"}, indent=2)
        
    # 3. Registrar início da execução mestre no Supabase do cliente
    input_data = {
        "client_id": client_id,
        "phone": phone,
        "message": message,
        "agent_id": agent_id,
        "execution_id": str(exec_uuid)
    }
    
    try:
        await start_workflow_execution(
            supabase_client=supabase_client,
            workflow_name="mcp_ligawhats",
            input_data=input_data,
            execution_id=exec_uuid
        )
        
        await update_workflow_status(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            status="RUNNING"
        )
    except Exception as e:
        # Se falhar o log inicial, prossegue mas loga o aviso no stdout
        print(f"Aviso: Não foi possível registrar início do workflow EDW no Supabase ({e})")
        
    try:
        # Passo 1: Normalização do telefone em Python
        async def normalize_phone_step():
            return normalize_phone_to_12_digits(phone)
            
        normalized_phone = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="mcp_ligawhats_normalize_phone",
            worker_func=normalize_phone_step,
            input_data={"raw_phone": phone}
        )
        
        if len(normalized_phone) != 12 or not normalized_phone.isdigit():
            raise ValueError(f"Número normalizado inválido: '{normalized_phone}'. Deve ter exatamente 12 dígitos.")
            
        # Passo 2: Buscar configurações de Z-API no Supabase Master
        async def get_config_step():
            return get_client_config(client_id)
            
        config = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="mcp_ligawhats_get_config",
            worker_func=get_config_step,
            input_data={"client_id": client_id}
        )
        
        zapi_instance = config.get("zapi_instance_id")
        zapi_token = config.get("zapi_client_token")
        zapi_security_token = config.get("zapi_security_token")
        
        if not zapi_instance or not zapi_token:
            raise ValueError(f"Configurações da Z-API ausentes no Supabase Master para o cliente '{client_id}'.")
            
        # Passo 3: Envio de mensagem via Z-API (send-text)
        zapi_url = f"https://api.z-api.io/instances/{zapi_instance}/token/{zapi_token}/send-text"
        zapi_payload = {
            "phone": normalized_phone,
            "message": message
        }
        
        zapi_headers = {}
        if zapi_security_token:
            zapi_headers["Client-Token"] = zapi_security_token
            
        async def send_whatsapp_step():
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(zapi_url, json=zapi_payload, headers=zapi_headers)
                res.raise_for_status()
                return res.json()
                
        zapi_response = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="mcp_ligawhats_send_whatsapp",
            worker_func=send_whatsapp_step,
            input_data={
                "url": zapi_url,
                "payload": zapi_payload
            }
        )
        
        # 4. Finalizar o workflow com sucesso
        try:
            await update_workflow_status(
                supabase_client=supabase_client,
                execution_id=exec_uuid,
                status="SUCCESS",
                output_data=zapi_response
            )
        except Exception as e:
            print(f"Aviso: Não foi possível atualizar status do workflow para SUCCESS no Supabase ({e})")
            
        return json.dumps(zapi_response, indent=2)
        
    except Exception as err:
        try:
            await update_workflow_status(
                supabase_client=supabase_client,
                execution_id=exec_uuid,
                status="FAILED",
                error_details=str(err)
            )
        except Exception as e:
            print(f"Aviso: Não foi possível atualizar status do workflow para FAILED no Supabase ({e})")
            
        return json.dumps({"error": f"Falha na execução do workflow: {str(err)}"}, indent=2)

# 5. Aplicação FastAPI principal que protege e expõe os endpoints do FastMCP
from starlette.routing import Route

# Chamamos ambos para inicializar as rotas e o session manager
sse_subapp = mcp.sse_app()
http_subapp = mcp.streamable_http_app()

@asynccontextmanager
async def app_lifespan(app_instance: FastAPI):
    # Inicializa o pool do Redis
    redis_url = settings.REDIS_URL.replace("#", "%23")
    redis_settings = RedisSettings.from_dsn(redis_url)
    redis_pool = None
    try:
        redis_pool = await create_pool(redis_settings)
        import main
        main.redis_pool = redis_pool
    except Exception as e:
        print(f"Aviso: Não foi possível conectar ao Redis ({e}). A tool 'schedule_appointment' não estará totalmente operacional.")

    # Inicializa o session manager do Streamable HTTP
    async with mcp.session_manager.run():
        yield {"redis_pool": redis_pool}

    if redis_pool:
        await redis_pool.close()

app = FastAPI(
    title="Mindflow Secure MCP Service",
    description="Interface Model Context Protocol protegida para agentes externos de IA",
    version="1.0.0",
    lifespan=app_lifespan
)

# Adiciona o middleware de proteção
app.add_middleware(MCPAuthMiddleware)

@app.get("/health", status_code=status.HTTP_200_OK)
async def health():
    return {"status": "ok", "service": "secure-mcp-server"}

# Registra os webhooks clássicos de main.py
import main

app.post(
    "/webhook/schedule",
    response_model=main.WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(main.verify_token)]
)(main.schedule_appointment)

app.post(
    "/webhook/check-availability",
    response_model=main.VerificaAgendaResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(main.verify_token)]
)(main.check_availability)

# Adiciona as rotas de ambos os transportes ao FastAPI principal
app.routes.extend(sse_subapp.routes)
app.routes.extend(http_subapp.routes)

# Adiciona rota de fallback POST /sse apontando para o endpoint do Streamable HTTP
# para lidar com clientes (como Retell) que tentam enviar POST /sse diretamente
app.routes.append(
    Route("/sse", endpoint=http_subapp.routes[0].endpoint, methods=["POST"])
)

if __name__ == "__main__":
    # Se executado diretamente via linha de comando, roda em modo stdio (padrão)
    # permitindo testes locais e depuração com o MCP Inspector:
    # npx @modelcontextprotocol/inspector python mcp_server.py
    mcp.run()

