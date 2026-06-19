import os
import uuid
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from arq import create_pool
from arq.connections import RedisSettings

from config import settings, get_client_config, get_supabase_client, get_google_calendar_service
from schemas import AgendarReuniaoRequest, WebhookResponse, VerificaAgendaRequest, VerificaAgendaResponse, SlotDisponibilidade
from utils.tracing import start_workflow_execution
from utils.datetime_helpers import parse_iso_to_br, is_dia_util, get_dia_semana_pt

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
    Consulta de forma síncrona e concorrente (asyncio.gather) a disponibilidade 
    de slots na agenda compartilhada do cliente.
    """
    try:
        config = get_client_config(payload.client_id)
        calendar_id = config["google_calendar_id"]
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
        
    calendar_service = get_google_calendar_service()
    
    # Validações iniciais de fuso
    data_inicial_br = parse_iso_to_br(payload.data_inicial)
    data_final_br = parse_iso_to_br(payload.data_final)
    
    # Fatia o intervalo em slots de 1 hora
    slots = []
    current_time = data_inicial_br
    while current_time < data_final_br:
        slot_end = current_time + timedelta(hours=1)
        if slot_end <= data_final_br:
            slots.append((current_time, slot_end))
        current_time = slot_end
        
    if not slots:
        return VerificaAgendaResponse(
            client_id=payload.client_id,
            disponivel=False,
            slots=[]
        )

    # Função assíncrona executora para consultar a API FreeBusy do Google Calendar para cada slot
    async def query_freebusy_slot(start: datetime, end: datetime) -> SlotDisponibilidade:
        # Converte para formato ISO 8601 exigido pela API do Google Calendar (com offset UTC)
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": calendar_id}]
        }
        
        # Como o google-api-python-client é síncrono e bloqueante, rodamos no threadpool
        loop = asyncio.get_running_loop()
        try:
            # Consulta a disponibilidade no calendar do Google
            fb_response = await loop.run_in_executor(
                None,
                lambda: calendar_service.freebusy().query(body=body).execute()
            )
            
            # Verifica se há conflito de compromissos no slot específico
            busy_events = fb_response.get("calendars", {}).get(calendar_id, {}).get("busy", [])
            # Slot livre = não há eventos ocupados no intervalo
            is_available = len(busy_events) == 0
            
            # Também verifica se não cai em final de semana
            if not is_dia_util(start):
                is_available = False
                
            return SlotDisponibilidade(data=start, available=is_available)
        except Exception as e:
            # Em caso de erro na API, consideramos indisponível por segurança
            print(f"Erro ao consultar FreeBusy para slot {start}: {e}")
            return SlotDisponibilidade(data=start, available=False)

    # Execução concorrente de todas as consultas (asyncio.gather) para otimização de latência
    slots_results = await asyncio.gather(*(query_freebusy_slot(s, e) for s, e in slots))
    
    any_available = any(s.available for s in slots_results)
    
    return VerificaAgendaResponse(
        client_id=payload.client_id,
        disponivel=any_available,
        slots=slots_results
    )
