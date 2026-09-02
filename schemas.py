from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, List

class TraceableBase(BaseModel):
    workflow_id: str = Field(default="scheduling_workflow", description="ID fixo do workflow")
    from_workflow: str = Field(default="api_gateway", description="Nome do workflow chamador")
    execution_id: UUID = Field(..., description="UUID único da execução")

# Payload de Entrada para o agendamento
class AgendarReuniaoRequest(BaseModel):
    client_id: str = Field(..., description="ID do cliente cadastrado no Master")
    nome: str = Field(..., description="Nome do lead")
    email: EmailStr = Field(..., description="E-mail do lead")
    numero: str = Field(..., description="Telefone do lead no formato E.164")
    canal: str = Field(..., description="Canal de origem (whats ou ligacao)")
    data_agendamento: datetime = Field(..., description="Data/hora no formato ISO 8601 com timezone offset")
    resumo: Optional[str] = Field(None, description="Resumo dos desafios do lead")
    titulo: Optional[str] = Field(None, description="Título para o evento de agendamento")
    agent_id: Optional[str] = Field(None, description="ID do agente AI (ex: Retell Agent ID ou bot do WhatsApp)")

    @field_validator("numero")
    @classmethod
    def validar_numero(cls, v: str) -> str:
        if not v.startswith("+") or len(v) < 10:
            raise ValueError("O número de telefone deve começar com '+' e estar no formato internacional E.164.")
        return v

    @field_validator("canal")
    @classmethod
    def validar_canal(cls, v: str) -> str:
        if v not in ("whats", "ligacao"):
            raise ValueError("O canal deve ser 'whats' ou 'ligacao'.")
        return v

# Resposta imediata do webhook (202 Accepted)
class WebhookResponse(BaseModel):
    status: str
    execution_id: UUID
    message: str

# Payload de Entrada para verificação de disponibilidade
class VerificaAgendaRequest(BaseModel):
    client_id: str = Field(..., description="ID do cliente cadastrado no Master")
    data_inicial: datetime = Field(..., description="ISO 8601 com timezone offset")
    data_final: datetime = Field(..., description="ISO 8601 com timezone offset")

class SlotDisponibilidade(BaseModel):
    data: datetime
    available: bool
    reason: Optional[str] = None


class VerificaAgendaResponse(BaseModel):
    client_id: str
    disponivel: bool
    slots: List[SlotDisponibilidade]


# Payload para envio de vídeo via Z-API
class SendVideoRequest(BaseModel):
    client_id: str = Field(..., description="ID do cliente cadastrado no Master")
    phone: str = Field(..., description="Telefone do destinatário (formato internacional ou DDI+DDD+número)")
    video: str = Field(..., description="Link público do vídeo (URL) ou string em formato Base64")
    caption: Optional[str] = Field("", description="Descrição/legenda em texto a ser enviada junto com o vídeo")
    viewOnce: Optional[bool] = Field(False, description="Se verdadeiro, define como mensagem de visualização única no WhatsApp")
    messageId: Optional[str] = Field(None, description="ID da mensagem anterior a ser respondida, se houver")
    delayMessage: Optional[int] = Field(None, description="Delay em segundos (1 a 15) antes do envio")
    async_mode: Optional[bool] = Field(False, description="Se ativo, a Z-API responderá imediatamente e processará em segundo plano")
    agent_id: Optional[str] = Field(None, description="ID do agente acionador para rastreamento EDW")


class SendVideoResponse(BaseModel):
    zaapId: Optional[str] = Field(None, description="ID interno da mensagem no Z-API")
    messageId: Optional[str] = Field(None, description="ID único da mensagem enviada no WhatsApp")
    id: Optional[str] = Field(None, description="ID de referência da mensagem")
    execution_id: UUID = Field(..., description="UUID único da execução EDW")

