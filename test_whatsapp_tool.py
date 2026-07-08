import pytest
import uuid
import json
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from utils.phone import normalize_phone_to_12_digits
from mcp_server import send_whatsapp_message

# 1. Testes de Normalização de Telefone
def test_phone_normalization():
    # Caso 1: Formato padrão com + e 9 extra (13 dígitos úteis após limpar)
    assert normalize_phone_to_12_digits("+5541995252559") == "554195252559"
    
    # Caso 2: Formato sem + mas com 9 extra
    assert normalize_phone_to_12_digits("5541995252559") == "554195252559"
    
    # Caso 3: Formato sem DDI 55
    assert normalize_phone_to_12_digits("41995252559") == "554195252559"
    
    # Caso 4: Formato já com 12 dígitos correto
    assert normalize_phone_to_12_digits("554195252559") == "554195252559"
    assert normalize_phone_to_12_digits("+554195252559") == "554195252559"
    
    # Caso 5: Formato com caracteres especiais
    assert normalize_phone_to_12_digits("+55 (41) 99525-2559") == "554195252559"


# 2. Testes da Tool `send_whatsapp_message` do MCP
@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
@patch("httpx.AsyncClient.post")
async def test_send_whatsapp_message_success(mock_post, mock_config, mock_supabase):
    # Setup mocks
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    
    # Mock do insert/update do Supabase (para workflow_executions e workflow_step_executions)
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    # Mock das configurações da Z-API no Master
    mock_config.return_value = {
        "zapi_instance_id": "instance-abc",
        "zapi_client_token": "token-xyz",
        "zapi_security_token": "token-sec-123"
    }
    
    # Mock do envio da Z-API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"zaapId": "msg-123", "status": "sent"}
    mock_post.return_value = mock_response
    
    # Executa a tool
    res_str = await send_whatsapp_message(
        client_id="cliente-teste",
        phone="+5541995252559",
        message="Olá lead!",
        agent_id="agent_teste_whats"
    )
    
    # Validações
    res = json.loads(res_str)
    assert res["status"] == "sent"
    assert res["zaapId"] == "msg-123"
    
    # Verifica se os passos foram executados
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "instance-abc" in url
    assert "token-xyz" in url
    
    payload = mock_post.call_args[1]["json"]
    assert payload["phone"] == "554195252559"
    assert payload["message"] == "Olá lead!"
    
    headers = mock_post.call_args[1].get("headers", {})
    assert headers.get("Client-Token") == "token-sec-123"


@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
async def test_send_whatsapp_message_missing_config(mock_config, mock_supabase):
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    # Configurações Z-API ausentes
    mock_config.return_value = {
        "zapi_instance_id": None,
        "zapi_client_token": None,
        "zapi_security_token": None
    }
    
    res_str = await send_whatsapp_message(
        client_id="cliente-teste",
        phone="+5541995252559",
        message="Olá lead!"
    )
    
    res = json.loads(res_str)
    assert "error" in res
    assert "Configurações da Z-API ausentes" in res["error"]


@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
@patch("httpx.AsyncClient.post")
async def test_send_whatsapp_message_http_error(mock_post, mock_config, mock_supabase):
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    mock_config.return_value = {
        "zapi_instance_id": "instance-abc",
        "zapi_client_token": "token-xyz",
        "zapi_security_token": "token-sec-123"
    }
    
    # Simula erro de status do HTTP POST
    mock_post.side_effect = httpx.HTTPStatusError(
        "Erro de Gateway",
        request=MagicMock(),
        response=MagicMock(status_code=502)
    )
    
    res_str = await send_whatsapp_message(
        client_id="cliente-teste",
        phone="+5541995252559",
        message="Olá lead!"
    )
    
    res = json.loads(res_str)
    assert "error" in res
    assert "Falha na execução do workflow" in res["error"]
