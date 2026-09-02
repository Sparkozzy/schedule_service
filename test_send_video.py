import pytest
import uuid
import json
from unittest.mock import MagicMock, patch
import httpx

from mcp_server import send_whatsapp_video
from schemas import SendVideoRequest, SendVideoResponse

@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
@patch("httpx.AsyncClient.post")
async def test_send_whatsapp_video_success(mock_post, mock_config, mock_supabase):
    # Mock Supabase
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    # Mock Z-API Config
    mock_config.return_value = {
        "zapi_instance_id": "inst-video-123",
        "zapi_client_token": "token-video-456",
        "zapi_security_token": "token-sec-789"
    }
    
    # Mock Z-API Video response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "zaapId": "3999984263738042930CD6ECDE9VDWSA",
        "messageId": "D241XXXX732339502B68",
        "id": "D241XXXX732339502B68"
    }
    mock_post.return_value = mock_response
    
    # Executa a tool MCP
    res_str = await send_whatsapp_video(
        client_id="cliente-video",
        phone="+5541995252559",
        video="https://exemplo.com/demonstracao.mp4",
        caption="Veja a demonstração do nosso produto!",
        view_once=False,
        agent_id="agent_video_bot"
    )
    
    res = json.loads(res_str)
    assert res["zaapId"] == "3999984263738042930CD6ECDE9VDWSA"
    assert res["messageId"] == "D241XXXX732339502B68"
    
    # Validações da chamada HTTP
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "inst-video-123" in url
    assert "token-video-456" in url
    assert "send-video" in url
    
    payload = mock_post.call_args[1]["json"]
    assert payload["phone"] == "554195252559"
    assert payload["video"] == "https://exemplo.com/demonstracao.mp4"
    assert payload["caption"] == "Veja a demonstração do nosso produto!"
    assert payload["viewOnce"] is False
    
    headers = mock_post.call_args[1].get("headers", {})
    assert headers.get("Client-Token") == "token-sec-789"
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
async def test_send_whatsapp_video_missing_config(mock_config, mock_supabase):
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    mock_config.return_value = {
        "zapi_instance_id": None,
        "zapi_client_token": None
    }
    
    res_str = await send_whatsapp_video(
        client_id="cliente-video",
        phone="+5541995252559",
        video="https://exemplo.com/video.mp4",
        caption="Descrição"
    )
    
    res = json.loads(res_str)
    assert "error" in res
    assert "Configurações da Z-API ausentes" in res["error"]


def test_send_video_schema_validation():
    req = SendVideoRequest(
        client_id="cliente-test",
        phone="+5511999999999",
        video="https://exemplo.com/video.mp4",
        caption="Vídeo explicativo com legenda",
        viewOnce=True,
        delayMessage=5
    )
    assert req.client_id == "cliente-test"
    assert req.caption == "Vídeo explicativo com legenda"
    assert req.viewOnce is True
    assert req.delayMessage == 5
