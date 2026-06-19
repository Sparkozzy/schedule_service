import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
from config import get_client_config, get_google_calendar_service
from utils.datetime_helpers import parse_iso_to_br, is_dia_util, get_dia_semana_pt
from schemas import SlotDisponibilidade, VerificaAgendaResponse

async def fetch_brazilian_holidays(start_dt: datetime, end_dt: datetime) -> dict:
    """
    Busca feriados nacionais do Brasil no Google Calendar público.
    Retorna um dicionário mapeando datas YYYY-MM-DD para os nomes dos feriados.
    """
    calendar_service = get_google_calendar_service()
    loop = asyncio.get_running_loop()
    
    # Ajusta as datas para o início/fim do dia para garantir cobertura completa
    time_min = start_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    time_max = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    
    def _fetch():
        try:
            return calendar_service.events().list(
                calendarId="pt-br.brazilian#holiday@group.v.calendar.google.com",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True
            ).execute()
        except Exception as e:
            print(f"Erro ao buscar feriados no Google Calendar: {e}")
            return {}
            
    res = await loop.run_in_executor(None, _fetch)
    events = res.get("items", [])
    
    holidays = {}
    for event in events:
        summary = event.get("summary")
        start = event.get("start", {})
        # Feriados públicos do Google Calendar costumam ser de dia inteiro ('date' ex: '2026-01-01')
        date_str = start.get("date")
        if not date_str and start.get("dateTime"):
            date_str = start.get("dateTime").split("T")[0]
        if date_str and summary:
            holidays[date_str] = summary
            
    return holidays

async def check_availability_internal(client_id: str, data_inicial: datetime, data_final: datetime) -> VerificaAgendaResponse:
    """
    Verifica a disponibilidade de slots de 1 hora no intervalo fornecido.
    Antes de consultar o Google Calendar do cliente, valida se é fim de semana ou feriado nacional.
    """
    try:
        config = get_client_config(client_id)
        calendar_id = config["google_calendar_id"]
    except ValueError as ve:
        raise ve
        
    data_inicial_br = parse_iso_to_br(data_inicial)
    data_final_br = parse_iso_to_br(data_final)
    
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
            client_id=client_id,
            disponivel=False,
            slots=[]
        )

    # Busca os feriados para todo o intervalo de uma vez só
    holidays = await fetch_brazilian_holidays(data_inicial_br, data_final_br)
    calendar_service = get_google_calendar_service()
    
    async def query_slot(start: datetime, end: datetime) -> SlotDisponibilidade:
        # 1. Verifica se é fim de semana
        if not is_dia_util(start):
            dia_nome = get_dia_semana_pt(start)
            return SlotDisponibilidade(
                data=start,
                available=False,
                reason=f"fim de semana ({dia_nome})"
            )
            
        # 2. Verifica se é feriado
        day_str = start.strftime("%Y-%m-%d")
        if day_str in holidays:
            feriado_nome = holidays[day_str]
            return SlotDisponibilidade(
                data=start,
                available=False,
                reason=f"feriado: {feriado_nome}"
            )
            
        # 3. Se for dia útil e não for feriado, consulta a agenda do cliente no Google Calendar
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": calendar_id}]
        }
        
        loop = asyncio.get_running_loop()
        try:
            fb_response = await loop.run_in_executor(
                None,
                lambda: calendar_service.freebusy().query(body=body).execute()
            )
            busy_events = fb_response.get("calendars", {}).get(calendar_id, {}).get("busy", [])
            is_available = len(busy_events) == 0
            reason = None if is_available else "ocupado"
            return SlotDisponibilidade(data=start, available=is_available, reason=reason)
        except Exception as e:
            print(f"Erro ao consultar FreeBusy para slot {start}: {e}")
            return SlotDisponibilidade(data=start, available=False, reason="erro na consulta da agenda")

    # Execução concorrente de todos os slots (asyncio.gather) para otimização de latência
    slots_results = await asyncio.gather(*(query_slot(s, e) for s, e in slots))
    any_available = any(s.available for s in slots_results)
    
    return VerificaAgendaResponse(
        client_id=client_id,
        disponivel=any_available,
        slots=slots_results
    )
