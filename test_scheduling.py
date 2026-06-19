import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

# Mock das variáveis de ambiente e dependências antes do import
with patch.dict("os.environ", {
    "SUPABASE_MASTER_URL": "https://master.supabase.co",
    "SUPABASE_MASTER_SERVICE_KEY": "master-key",
    "REDIS_URL": "redis://localhost:6379/0",
    "API_BEARER_TOKEN": "test-token"
}):
    # Importar sob contexto mockado
    from config import settings, get_supabase_client, get_client_config
    from main import app
    from utils.datetime_helpers import parse_iso_to_br, is_dia_util, get_dia_semana_pt
    from worker import schedule_appointment_job

client = TestClient(app)

# 1. Testes de Datetime Helpers
def test_timezone_conversion():
    # ISO 8601 em UTC
    utc_str = "2026-06-18T18:00:00Z"
    br_dt = parse_iso_to_br(utc_str)
    # UTC 18:00 é 15:00 em Brasília (UTC-3)
    assert br_dt.hour == 15
    assert br_dt.minute == 0
    assert str(br_dt.tzinfo) == "America/Sao_Paulo"

def test_dia_util():
    # 18/06/2026 é uma quinta-feira (dia útil)
    dt_util = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    assert is_dia_util(dt_util) is True
    assert get_dia_semana_pt(parse_iso_to_br(dt_util)) == "quinta-feira"
    
    # 21/06/2026 é um domingo (final de semana)
    dt_fim_semana = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    assert is_dia_util(dt_fim_semana) is False

# 2. Testes de Configuração e Cache Multi-Tenant
@patch("config.supabase_master")
def test_get_client_config(mock_master):
    # Simula resposta do Supabase Master
    mock_master.table().select().eq().maybe_single().execute.return_value = MagicMock(
        data={
            "client_id": "cliente-teste",
            "supabase_url": "https://teste.supabase.co",
            "supabase_service_key": "service-key",
            "supabase_anon_key": "anon-key",
            "google_calendar_id": "cal-id-123"
        }
    )
    
    config = get_client_config("cliente-teste")
    assert config["client_id"] == "cliente-teste"
    assert config["google_calendar_id"] == "cal-id-123"

# 3. Testes dos Endpoints FastAPI
@patch("main.get_client_config")
@patch("main.get_supabase_client")
@patch("main.redis_pool")
def test_schedule_endpoint_unauthorized(mock_redis, mock_sub, mock_config):
    response = client.post("/webhook/schedule", json={})
    assert response.status_code == 401

@patch("main.get_client_config")
@patch("main.get_supabase_client")
@patch("main.redis_pool")
def test_schedule_endpoint_authorized(mock_redis, mock_sub, mock_config):
    mock_config.return_value = {"google_calendar_id": "cal-id-123"}
    
    # Mock do cliente Supabase e da inserção de rastreabilidade
    mock_supabase_instance = MagicMock()
    mock_sub.return_value = mock_supabase_instance
    mock_supabase_instance.table().insert().execute.return_value = MagicMock(data=[{"id": str(uuid.uuid4())}])
    
    # Mock do enfileiramento ARQ
    mock_redis.enqueue_job = AsyncMock()

    payload = {
        "client_id": "cliente-teste",
        "nome": "João da Silva",
        "email": "joao@example.com",
        "numero": "+5548996027108",
        "canal": "whats",
        "data_agendamento": "2026-06-18T18:00:00-03:00",
        "resumo": "Desafios de automação",
        "titulo": "Reunião de Alinhamento",
        "agent_id": "agent_teste_123"
    }

    response = client.post(
        "/webhook/schedule",
        headers={"Authorization": "Bearer test-token"},
        json=payload
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "Accepted"
    assert "execution_id" in data
    mock_redis.enqueue_job.assert_called_once()

# 4. Testes de Disponibilidade (Finais de Semana e Feriados)
@patch("utils.availability.get_client_config")
@patch("utils.availability.get_google_calendar_service")
def test_check_availability_weekend(mock_calendar, mock_config):
    mock_config.return_value = {
        "google_calendar_id": "cal-id-123"
    }
    
    # 2026-06-21 é um domingo
    payload = {
        "client_id": "cliente-teste",
        "data_inicial": "2026-06-21T10:00:00-03:00",
        "data_final": "2026-06-21T11:00:00-03:00"
    }
    
    response = client.post(
        "/webhook/check-availability",
        headers={"Authorization": "Bearer test-token"},
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["disponivel"] is False
    assert len(data["slots"]) == 1
    assert data["slots"][0]["available"] is False
    assert "fim de semana" in data["slots"][0]["reason"]
    
    # Verifica que não chamou a API do Google Calendar para FreeBusy
    mock_calendar.return_value.freebusy.query.assert_not_called()

@patch("utils.availability.get_client_config")
@patch("utils.availability.get_google_calendar_service")
def test_check_availability_holiday(mock_calendar, mock_config):
    mock_config.return_value = {
        "google_calendar_id": "cal-id-123"
    }
    
    # Mock do retorno dos Feriados Nacionais (Google Calendar list events)
    mock_service = MagicMock()
    mock_calendar.return_value = mock_service
    mock_service.events().list().execute.return_value = {
        "items": [
            {
                "summary": "Dia de Teste Fictício",
                "start": {"date": "2026-06-18"}
            }
        ]
    }
    
    # 2026-06-18T10:00:00-03:00 (quinta-feira, mas mockamos como feriado)
    payload = {
        "client_id": "cliente-teste",
        "data_inicial": "2026-06-18T10:00:00-03:00",
        "data_final": "2026-06-18T11:00:00-03:00"
    }
    
    response = client.post(
        "/webhook/check-availability",
        headers={"Authorization": "Bearer test-token"},
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["disponivel"] is False
    assert len(data["slots"]) == 1
    assert data["slots"][0]["available"] is False
    assert "feriado" in data["slots"][0]["reason"]
    assert "Dia de Teste Fictício" in data["slots"][0]["reason"]
    
    # Verifica que não chamou FreeBusy porque foi bloqueado antes por ser feriado
    mock_service.freebusy.query.assert_not_called()

@patch("utils.availability.get_client_config")
@patch("utils.availability.get_google_calendar_service")
def test_check_availability_available(mock_calendar, mock_config):
    mock_config.return_value = {
        "google_calendar_id": "cal-id-123"
    }
    
    mock_service = MagicMock()
    mock_calendar.return_value = mock_service
    # Sem feriados no período
    mock_service.events().list().execute.return_value = {"items": []}
    # FreeBusy retorna ocupado vazio (significa que está livre)
    mock_service.freebusy().query().execute.return_value = {
        "calendars": {
            "cal-id-123": {
                "busy": []
            }
        }
    }
    
    # 2026-06-18T10:00:00-03:00 (quinta-feira, dia útil, sem feriado)
    payload = {
        "client_id": "cliente-teste",
        "data_inicial": "2026-06-18T10:00:00-03:00",
        "data_final": "2026-06-18T11:00:00-03:00"
    }
    
    response = client.post(
        "/webhook/check-availability",
        headers={"Authorization": "Bearer test-token"},
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["disponivel"] is True
    assert len(data["slots"]) == 1
    assert data["slots"][0]["available"] is True
    assert data["slots"][0]["reason"] is None
    
    # Verifica que chamou a API FreeBusy pois o dia é útil e sem feriados
    mock_service.freebusy().query.assert_any_call(
        body={
            "timeMin": "2026-06-18T10:00:00-03:00",
            "timeMax": "2026-06-18T11:00:00-03:00",
            "items": [{"id": "cal-id-123"}]
        }
    )


