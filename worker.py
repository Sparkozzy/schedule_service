import asyncio
import httpx
from datetime import timedelta
from typing import Any, Dict
from arq.connections import RedisSettings

from config import settings, get_client_config, get_supabase_client, get_google_calendar_service
from utils.datetime_helpers import parse_iso_to_br
from utils.tracing import update_workflow_status, run_step_with_retry
from utils.crm import send_crm_event

async def schedule_appointment_job(ctx: Dict[str, Any], client_id: str, execution_id: str, appointment_data: Dict[str, Any]) -> str:
    """
    Job do worker ARQ para processamento em background de um agendamento.
    Executa os passos sequencialmente com rastreabilidade EDW individualizada no banco do cliente.
    """
    import uuid
    exec_uuid = uuid.UUID(execution_id)
    
    # 1. Obter cliente Supabase do Cliente
    try:
        supabase_client = get_supabase_client(client_id)
    except Exception as e:
        print(f"Erro ao instanciar o cliente Supabase para '{client_id}': {e}")
        return f"Falha na inicialização do Supabase do cliente: {e}"

    # Marcar status do workflow mestre como RUNNING no Supabase do cliente
    await update_workflow_status(
        supabase_client=supabase_client,
        execution_id=exec_uuid,
        status="RUNNING"
    )

    try:
        # Passo 1: Validar e obter configurações do cliente no Master
        async def validate_client_step():
            return get_client_config(client_id)
            
        config = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="scheduling_workflow_validate_client",
            worker_func=validate_client_step,
            input_data={"client_id": client_id}
        )

        calendar_id = config["google_calendar_id"]
        
        # Passo 2: Criar evento no Google Calendar
        data_hora_dt = parse_iso_to_br(appointment_data["data_agendamento"])
        end_time_dt = data_hora_dt + timedelta(hours=1)
        
        event_body = {
            "summary": appointment_data.get("titulo") or f"Atendimento - {appointment_data['nome']}",
            "description": appointment_data.get("resumo") or "Agendamento realizado via canal de voz/chat.",
            "start": {
                "dateTime": data_hora_dt.isoformat(),
                "timeZone": "America/Sao_Paulo"
            },
            "end": {
                "dateTime": end_time_dt.isoformat(),
                "timeZone": "America/Sao_Paulo"
            },
            "attendees": [
                {"email": appointment_data["email"]}
            ],
            "conferenceData": {
                "createRequest": {
                    "requestId": str(exec_uuid),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"}
                }
            }
        }
        
        async def create_event_step():
            calendar_service = get_google_calendar_service()
            loop = asyncio.get_running_loop()
            
            # Executa a chamada síncrona no executor para não bloquear o loop de eventos
            event_result = await loop.run_in_executor(
                None,
                lambda: calendar_service.events().insert(
                    calendarId=calendar_id,
                    body=event_body,
                    conferenceDataVersion=1
                ).execute()
            )
            return event_result

        event = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="scheduling_workflow_create_calendar_event",
            worker_func=create_event_step,
            input_data=event_body
        )
        
        google_event_id = event["id"]
        meet_link = event.get("hangoutLink", "")

        # Passo 3: Registrar agendamento na tabela 'agendamentos' do cliente
        appointment_record = {
            "nome": appointment_data["nome"],
            "email": appointment_data["email"],
            "numero": appointment_data["numero"],
            "canal": appointment_data["canal"],
            "data_agendamento": data_hora_dt.isoformat(),
            "status": "agendado",
            "detalhes": appointment_data.get("resumo"),
            "google_event_id": google_event_id,
            "calendar_id": calendar_id,
            "execution_id": str(exec_uuid),
            "agent_id": appointment_data.get("agent_id")
        }
        
        async def upsert_appointment_step():
            # Inserção do registro de agendamento no Supabase do cliente
            res = supabase_client.table("agendamentos").insert(appointment_record).execute()
            return res.data[0]

        appointment = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="scheduling_workflow_upsert_lead_appointment",
            worker_func=upsert_appointment_step,
            input_data=appointment_record
        )

        # Passo 4: Notificação no WhatsApp do Time (via Z-API se configurado)
        zapi_instance = config.get("zapi_instance_id")
        zapi_token = config.get("zapi_client_token")
        zapi_group = config.get("zapi_group_id")
        
        if zapi_instance and zapi_token and zapi_group:
            message_text = (
                f"📅 *Novo Agendamento Confirmado!*\n\n"
                f"👤 *Lead:* {appointment_data['nome']}\n"
                f"📧 *Email:* {appointment_data['email']}\n"
                f"📞 *Telefone:* {appointment_data['numero']}\n"
                f"⏱️ *Horário:* {data_hora_dt.strftime('%d/%m/%Y às %H:%M')}\n"
                f"💬 *Canal:* {appointment_data['canal']}\n"
                f"🔗 *Link do Meet:* {meet_link}\n"
            )
            zapi_url = f"https://api.z-api.io/instances/{zapi_instance}/token/{zapi_token}/send-messages"
            zapi_payload = {
                "phone": zapi_group,
                "message": message_text
            }
            
            async def notify_whatsapp_step():
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(zapi_url, json=zapi_payload)
                    res.raise_for_status()
                    return res.json()
                    
            await run_step_with_retry(
                supabase_client=supabase_client,
                execution_id=exec_uuid,
                step_name="scheduling_workflow_notify_whatsapp",
                worker_func=notify_whatsapp_step,
                input_data=zapi_payload
            )

        # Passo 5: Envio de evento de agendamento para o CRM (Webhook) se configurado
        crm_config = config.get("crm_config")
        crm_appointment_data = {
            **appointment_record,
            "meet_link": meet_link,
            "appointment_id": appointment.get("id")
        }
        
        async def send_to_crm_step():
            return await send_crm_event(
                client_id=client_id,
                appointment_data=crm_appointment_data,
                crm_config=crm_config
            )
            
        crm_input_log = {
            "client_id": client_id,
            "crm_config": {
                "crm_type": crm_config.get("crm_type") if crm_config else None,
                "webhook_url": crm_config.get("webhook_url") if crm_config else None
            }
        }
        
        crm_result = await run_step_with_retry(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            step_name="scheduling_workflow_send_to_crm",
            worker_func=send_to_crm_step,
            input_data=crm_input_log
        )

        # Atualizar status mestre para SUCCESS
        output_data = {
            "google_event_id": google_event_id,
            "meet_link": meet_link,
            "appointment_id": appointment.get("id"),
            "crm_integration": crm_result,
            "status": "scheduled_successfully"
        }
        await update_workflow_status(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            status="SUCCESS",
            output_data=output_data
        )
        return "Scheduled successfully"
        
    except Exception as err:
        # Registrar falha no status mestre do workflow
        await update_workflow_status(
            supabase_client=supabase_client,
            execution_id=exec_uuid,
            status="FAILED",
            error_details=str(err)
        )
        raise err

# Configurações do Worker para execução do ARQ
class WorkerSettings:
    functions = [schedule_appointment_job]
    # Substituir '#' por '%23' por compatibilidade com Easypanel
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL.replace("#", "%23"))
