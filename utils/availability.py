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
    
    # 1. Consulta a agenda do cliente no Google Calendar de forma global para todo o intervalo
    body = {
        "timeMin": data_inicial_br.isoformat(),
        "timeMax": data_final_br.isoformat(),
        "items": [{"id": calendar_id}]
    }
    
    loop = asyncio.get_running_loop()
    try:
        fb_response = await loop.run_in_executor(
            None,
            lambda: calendar_service.freebusy().query(body=body).execute()
        )
        busy_list = fb_response.get("calendars", {}).get(calendar_id, {}).get("busy", [])
        
        # Converte os intervalos ocupados do Google Calendar para datetime com fuso de Brasília
        busy_intervals = []
        for event in busy_list:
            b_start = parse_iso_to_br(datetime.fromisoformat(event["start"]))
            b_end = parse_iso_to_br(datetime.fromisoformat(event["end"]))
            busy_intervals.append((b_start, b_end))
    except Exception as e:
        print(f"Erro ao consultar FreeBusy global para {client_id}: {e}")
        busy_intervals = None

    slots_results = []
    for start, end in slots:
        # 1. Verifica se é fim de semana
        if not is_dia_util(start):
            dia_nome = get_dia_semana_pt(start)
            slots_results.append(SlotDisponibilidade(
                data=start,
                available=False,
                reason=f"fim de semana ({dia_nome})"
            ))
            continue
            
        # 2. Verifica se é feriado
        day_str = start.strftime("%Y-%m-%d")
        if day_str in holidays:
            feriado_nome = holidays[day_str]
            slots_results.append(SlotDisponibilidade(
                data=start,
                available=False,
                reason=f"feriado: {feriado_nome}"
            ))
            continue
            
        # 3. Se deu erro na API da agenda, marca como indisponível por erro
        if busy_intervals is None:
            slots_results.append(SlotDisponibilidade(
                data=start,
                available=False,
                reason="erro na consulta da agenda"
            ))
            continue
            
        # 4. Verifica se o slot de 1h se sobrepõe a qualquer período ocupado
        is_available = True
        for b_start, b_end in busy_intervals:
            if start < b_end and end > b_start:
                is_available = False
                break
                
        reason = None if is_available else "ocupado"
        slots_results.append(SlotDisponibilidade(data=start, available=is_available, reason=reason))

    any_available = any(s.available for s in slots_results)
    
    return VerificaAgendaResponse(
        client_id=client_id,
        disponivel=any_available,
        slots=slots_results
    )
