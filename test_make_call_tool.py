import sys
from unittest.mock import MagicMock, patch

# Mock google client modules if not installed in current environment
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['google.oauth2'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google.oauth2.service_account'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()

# Mock env vars needed by config.py
import os
os.environ["SUPABASE_MASTER_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_MASTER_SERVICE_KEY"] = "test-key"
os.environ["API_BEARER_TOKEN"] = "test-token"

import pytest
import json
from mcp_server import make_phone_call

@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("httpx.AsyncClient.post")
async def test_make_phone_call_success(mock_post, mock_supabase):
    # Mock Supabase EDW Client
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])

    # Mock pre_call_processing response
    mock_response = MagicMock()
    mock_response.status_code = 202
    mock_response.json.return_value = {
        "status": "success",
        "message": "Webhook aceito, registro mestre criado e delegado para a fila persistente.",
        "execution_db_id": "b3f6c8d2-4e2a-412b-98df-89212ab56789"
    }
    mock_post.return_value = mock_response

    # Patch settings.PRE_CALL_PROCESSING_API_KEY
    with patch("mcp_server.settings.PRE_CALL_PROCESSING_API_KEY", "mf_sk_2026_pre_call_xK9v3Qm7bR4wT1nZ"):
        res_str = await make_phone_call(
            client_id="cliente-alpha",
            numero="+5548996027108",
            nome="Carlos Eduardo",
            agent_id="agent_retell_123",
            prompt_id="prompt_24",
            contexto="Lead interessado no plano corporativo. Entrar em contato para agendar demonstração."
        )

    res = json.loads(res_str)
    assert res["status"] == "success"
    assert res["execution_db_id"] == "b3f6c8d2-4e2a-412b-98df-89212ab56789"

    # Validar chamada HTTP
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "https://call-github.bkpxmb.easypanel.host/webhook" in url

    payload = mock_post.call_args[1]["json"]
    assert payload["numero"] == "+5548996027108"
    assert payload["nome"] == "Carlos Eduardo"
    assert payload["agent_id"] == "agent_retell_123"
    assert payload["Prompt_id"] == "prompt_24"
    assert "plano corporativo" in payload["contexto"]

    headers = mock_post.call_args[1]["headers"]
    assert headers["X-API-Key"] == "mf_sk_2026_pre_call_xK9v3Qm7bR4wT1nZ"


@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
async def test_make_phone_call_missing_api_key(mock_supabase):
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])

    with patch("mcp_server.settings.PRE_CALL_PROCESSING_API_KEY", ""):
        res_str = await make_phone_call(
            client_id="cliente-alpha",
            numero="+5548996027108",
            nome="Carlos Eduardo",
            agent_id="agent_retell_123",
            prompt_id="prompt_24",
            contexto="Teste sem API Key"
        )

    res = json.loads(res_str)
    assert "error" in res
    assert "PRE_CALL_PROCESSING_API_KEY" in res["error"]
