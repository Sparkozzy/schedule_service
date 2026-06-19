import asyncio
import random
import uuid
from datetime import datetime, timezone
from typing import Callable, Any, Dict, Optional, Awaitable
from supabase import Client
from utils.datetime_helpers import get_utc_now

async def start_workflow_execution(
    supabase_client: Client,
    workflow_name: str,
    input_data: Dict[str, Any],
    execution_id: uuid.UUID
) -> None:
    """Cria o registro mestre de execução na tabela workflow_executions do respectivo cliente."""
    supabase_client.table("workflow_executions").insert({
        "id": str(execution_id),
        "workflow_name": workflow_name,
        "status": "PENDING",
        "input_data": input_data,
        "created_at": get_utc_now(),
        "updated_at": get_utc_now()
    }).execute()

async def update_workflow_status(
    supabase_client: Client,
    execution_id: uuid.UUID,
    status: str,
    output_data: Optional[Dict[str, Any]] = None,
    error_details: Optional[str] = None
) -> None:
    """Atualiza o estado do registro mestre do workflow (RUNNING, SUCCESS, FAILED)."""
    update_data = {
        "status": status,
        "updated_at": get_utc_now()
    }
    if status == "RUNNING":
        update_data["started_at"] = get_utc_now()
    elif status in ("SUCCESS", "FAILED"):
        update_data["completed_at"] = get_utc_now()
        if output_data is not None:
            update_data["output_data"] = output_data
        if error_details is not None:
            update_data["error_details"] = error_details
            
    supabase_client.table("workflow_executions")\
        .update(update_data)\
        .eq("id", str(execution_id))\
        .execute()

async def run_step_with_retry(
    supabase_client: Client,
    execution_id: uuid.UUID,
    step_name: str,
    worker_func: Optional[Callable[[], Awaitable[Any]]] = None,
    input_data: Optional[Dict[str, Any]] = None,
    max_retries: int = 3
) -> Any:
    """
    Executa a lógica de um nó (Step) com retry exponencial e jitter, 
    registrando cada tentativa em workflow_step_executions do respectivo cliente.
    """
    attempt = 1
    last_exception = None
    
    while attempt <= max_retries:
        # Registrar início da tentativa do step
        step_log = supabase_client.table("workflow_step_executions").insert({
            "execution_id": str(execution_id),
            "step_name": step_name,
            "status": "RUNNING",
            "attempt": attempt,
            "input_data": input_data,
            "started_at": get_utc_now()
        }).execute()
        
        step_record_id = step_log.data[0]["id"]
        
        try:
            if worker_func:
                output = await worker_func()
            else:
                # Simulação caso worker_func não seja fornecido (fallback)
                await asyncio.sleep(0.1)
                output = {"status": "simulated_success"}
                
            # Registrar sucesso
            supabase_client.table("workflow_step_executions").update({
                "status": "SUCCESS",
                "output_data": output if isinstance(output, dict) else {"result": str(output)},
                "completed_at": get_utc_now()
            }).eq("id", step_record_id).execute()
            
            return output
            
        except Exception as e:
            last_exception = e
            # Registrar falha da tentativa
            supabase_client.table("workflow_step_executions").update({
                "status": "FAILED",
                "error_details": str(e),
                "completed_at": get_utc_now()
            }).eq("id", step_record_id).execute()
            
            if attempt < max_retries:
                # Exponential backoff + jitter: 2^attempt + random(0, 1) capped at 30 seconds
                backoff = min(2 ** attempt + random.random(), 30.0)
                await asyncio.sleep(backoff)
                
            attempt += 1
            
    # Se esgotar retentativas
    raise last_exception or RuntimeError(f"Step {step_name} falhou após {max_retries} tentativas.")
