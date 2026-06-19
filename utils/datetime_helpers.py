from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Union

BR_TIMEZONE = ZoneInfo("America/Sao_Paulo")

def get_utc_now() -> str:
    """Retorna o timestamp atual no formato ISO 8601 UTC/Z para persistência."""
    return datetime.now(timezone.utc).isoformat()

def get_br_now() -> datetime:
    """Retorna o datetime atual localizado no fuso horário de Brasília."""
    return datetime.now(BR_TIMEZONE)

def parse_iso_to_br(iso_date: Union[str, datetime]) -> datetime:
    """Converte um ISO 8601 ou datetime de qualquer fuso para o fuso de Brasília."""
    if isinstance(iso_date, str):
        # Trata possíveis sufixos 'Z' substituindo por +00:00 para fromisoformat
        if iso_date.endswith("Z"):
            iso_date = iso_date[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_date)
    else:
        dt = iso_date
    
    if dt.tzinfo is None:
        # Assumir UTC caso esteja naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BR_TIMEZONE)

def is_dia_util(dt: datetime) -> bool:
    """Verifica se o dia fornecido é útil (segunda a sexta)."""
    # 0 = segunda, 5 = sábado, 6 = domingo
    return dt.weekday() < 5

def get_dia_semana_pt(dt: datetime) -> str:
    """Retorna o nome do dia da semana em português."""
    dias = {
        0: "segunda-feira",
        1: "terça-feira",
        2: "quarta-feira",
        3: "quinta-feira",
        4: "sexta-feira",
        5: "sábado",
        6: "domingo"
    }
    return dias.get(dt.weekday(), "")
