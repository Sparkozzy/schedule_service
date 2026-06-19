import httpx
from typing import Dict, Any, Optional

async def send_crm_event(
    client_id: str, 
    appointment_data: Dict[str, Any], 
    crm_config: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Envia os detalhes do agendamento para o CRM do cliente configurado via Webhook.
    
    Args:
        client_id: ID do cliente.
        appointment_data: Dados completos do agendamento (incluindo lead e reunião).
        crm_config: Dicionário de configuração contendo 'crm_type', 'webhook_url' e opcionais.
        
    Returns:
        Dicionário com o resultado da execução.
    """
    if not crm_config:
        return {"status": "skipped", "reason": "Sem configuração de CRM ativa."}
        
    crm_type = crm_config.get("crm_type")
    if not crm_type or crm_type == "none":
        return {"status": "skipped", "reason": "Tipo de CRM definido como desabilitado."}
        
    if crm_type != "webhook":
        raise ValueError(f"Tipo de CRM '{crm_type}' não é suportado. Suportado apenas 'webhook'.")
        
    webhook_url = crm_config.get("webhook_url")
    if not webhook_url:
        raise ValueError("URL do Webhook do CRM ('webhook_url') não configurada.")
        
    # Obtém headers adicionais configurados (ex: tokens de autorização)
    headers = crm_config.get("headers") or {}
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
        
    # Payload padronizado contendo lead e informações da reunião
    payload = {
        "event": "appointment_scheduled",
        "client_id": client_id,
        "lead": {
            "nome": appointment_data.get("nome"),
            "email": appointment_data.get("email"),
            "numero": appointment_data.get("numero")
        },
        "appointment": {
            "canal": appointment_data.get("canal"),
            "data_agendamento": appointment_data.get("data_agendamento"),
            "status": appointment_data.get("status") or "agendado",
            "detalhes": appointment_data.get("resumo") or appointment_data.get("detalhes"),
            "google_event_id": appointment_data.get("google_event_id"),
            "meet_link": appointment_data.get("meet_link")
        }
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(webhook_url, json=payload, headers=headers)
        response.raise_for_status()
        
        try:
            response_json = response.json()
        except Exception:
            response_json = {"text": response.text}
            
        return {
            "status": "success",
            "status_code": response.status_code,
            "response": response_json
        }
