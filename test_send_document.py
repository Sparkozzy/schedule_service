import pytest
import uuid
import json
from unittest.mock import MagicMock, patch
import httpx

from mcp_server import send_whatsapp_document
from schemas import SendDocumentRequest, SendDocumentResponse

@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
@patch("httpx.AsyncClient.post")
async def test_send_whatsapp_document_success(mock_post, mock_config, mock_supabase):
    # Mock Supabase
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    # Mock Z-API Config
    mock_config.return_value = {
        "zapi_instance_id": "inst-doc-123",
        "zapi_client_token": "token-doc-456",
        "zapi_security_token": "token-sec-789"
    }
    
    # Mock Z-API Document response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "zaapId": "3999984263738042930CD6ECDE9DOCS",
        "messageId": "D241XXXX732339502DOC",
        "id": "D241XXXX732339502DOC"
    }
    mock_post.return_value = mock_response
    
    # Executa a tool MCP
    res_str = await send_whatsapp_document(
        client_id="cliente-doc",
        phone="+5541995252559",
        document_url="https://exemplo.com/proposta.pdf",
        extension="pdf",
        file_name="Proposta_Comercial.pdf",
        caption="Segue a proposta comercial solicitada.",
        agent_id="agent_doc_bot"
    )
    
    res = json.loads(res_str)
    assert res["zaapId"] == "3999984263738042930CD6ECDE9DOCS"
    assert res["messageId"] == "D241XXXX732339502DOC"
    
    # Validações da chamada HTTP
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "inst-doc-123" in url
    assert "token-doc-456" in url
    assert "send-document/pdf" in url
    
    payload = mock_post.call_args[1]["json"]
    assert payload["phone"] == "554195252559"
    assert payload["document"] == "https://exemplo.com/proposta.pdf"
    assert payload["fileName"] == "Proposta_Comercial.pdf"
    assert payload["caption"] == "Segue a proposta comercial solicitada."
    
    headers = mock_post.call_args[1].get("headers", {})
    assert headers.get("Client-Token") == "token-sec-789"
    assert headers.get("Content-Type") == "application/json"


@pytest.mark.asyncio
@patch("mcp_server.get_supabase_client")
@patch("mcp_server.get_client_config")
async def test_send_whatsapp_document_missing_config(mock_config, mock_supabase):
    mock_supabase_client = MagicMock()
    mock_supabase.return_value = mock_supabase_client
    mock_supabase_client.table().insert().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    mock_supabase_client.table().update().execute.return_value = MagicMock(data=[{"id": "step-id-123"}])
    
    mock_config.return_value = {
        "zapi_instance_id": None,
        "zapi_client_token": None
    }
    
    res_str = await send_whatsapp_document(
        client_id="cliente-doc",
        phone="+5541995252559",
        document_url="https://exemplo.com/proposta.pdf",
        caption="Descrição"
    )
    
    res = json.loads(res_str)
    assert "error" in res
    assert "Configurações da Z-API ausentes" in res["error"]


def test_send_document_schema_validation():
    req = SendDocumentRequest(
        client_id="cliente-test",
        phone="+5511999999999",
        document="https://exemplo.com/relatorio.pdf",
        extension="pdf",
        fileName="Relatorio.pdf",
        caption="Relatório financeiro",
        delayMessage=3
    )
    assert req.client_id == "cliente-test"
    assert req.extension == "pdf"
    assert req.fileName == "Relatorio.pdf"
    assert req.delayMessage == 3
