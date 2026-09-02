import os
import uuid
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from arq import create_pool
from arq.connections import RedisSettings

from config import settings, get_client_config, get_supabase_client, get_google_calendar_service
from schemas import (
    AgendarReuniaoRequest,
    WebhookResponse,
    VerificaAgendaRequest,
    VerificaAgendaResponse,
    SlotDisponibilidade,
    SendVideoRequest,
    SendVideoResponse
)
from utils.tracing import start_workflow_execution
from utils.availability import check_availability_internal

app = FastAPI(
    title="Mindflow Scheduling Service",
    description="Multi-tenant scheduling and availability service integrated with Google Calendar and Supabase",
    version="1.0.0"
)

# Configuração de Segurança (Bearer Token)
security_scheme = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security_scheme)):
    if credentials.credentials != settings.API_BEARER_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou não fornecido."
        )
    return credentials.credentials

# Inicialização do Pool do Redis para o ARQ
redis_pool = None

@app.on_event("startup")
async def startup_event():
    global redis_pool
    # Tratamento especial do Easypanel para caracteres no Redis URL (substituir # por %23 se houver)
    redis_url = settings.REDIS_URL.replace("#", "%23")
    redis_settings = RedisSettings.from_dsn(redis_url)
    redis_pool = await create_pool(redis_settings)

@app.on_event("shutdown")
async def shutdown_event():
    global redis_pool
    if redis_pool:
        await redis_pool.close()

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok", "service": "scheduling-service"}

@app.post(
    "/webhook/schedule",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_token)]
)
async def schedule_appointment(payload: AgendarReuniaoRequest):
    """
    Webhook para solicitar agendamento de consulta.
    Valida o cliente, cria o registro de rastreabilidade (PENDING) no Supabase dele,
    enfileira o job no Redis (ARQ) e responde 202 Accepted imediatamente.
    """
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
        
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao registrar execução de rastreabilidade no cliente: {str(e)}"
        )
        
    # 4. Enfileira o processamento pesado no ARQ
    if redis_pool:
        await redis_pool.enqueue_job(
            "schedule_appointment_job",
            client_id=payload.client_id,
            execution_id=str(execution_id),
            appointment_data=input_data
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fila Redis de segundo plano (ARQ) indisponível."
        )

    return WebhookResponse(
        status="Accepted",
        execution_id=execution_id,
        message="Agendamento recebido e enviado para processamento em background."
    )

@app.post(
    "/webhook/check-availability",
    response_model=VerificaAgendaResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_token)]
)
async def check_availability(payload: VerificaAgendaRequest):
    """
    Consulta de forma síncrona e concorrente a disponibilidade 
    de slots na agenda compartilhada do cliente, aplicando filtros de feriados e fins de semana.
    """
    try:
        return await check_availability_internal(payload.client_id, payload.data_inicial, payload.data_final)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao consultar disponibilidade: {str(e)}"
        )

@app.post(
    "/webhook/send-video",
    response_model=SendVideoResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_token)]
)
async def send_video(payload: SendVideoRequest):
    """
    Webhook para envio de vídeo via URL pública ou Base64 com legenda/descrição para contato do WhatsApp via Z-API.
    """
    from mcp_server import send_whatsapp_video
    exec_id = uuid.uuid4()
    raw_res = await send_whatsapp_video(
        client_id=payload.client_id,
        phone=payload.phone,
        video=payload.video,
        caption=payload.caption,
        view_once=payload.viewOnce,
        message_id=payload.messageId,
        delay_message=payload.delayMessage,
        async_mode=payload.async_mode,
        execution_id=str(exec_id),
        agent_id=payload.agent_id
    )
    import json
    data = json.loads(raw_res)
    if "error" in data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=data["error"]
        )
    return SendVideoResponse(
        zaapId=data.get("zaapId"),
        messageId=data.get("messageId"),
        id=data.get("id"),
        execution_id=exec_id
    )

