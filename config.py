import os
import json
from typing import Dict, Any, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Carrega arquivo .env se presente
load_dotenv()

class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379/0"
    
    SUPABASE_MASTER_URL: str
    SUPABASE_MASTER_SERVICE_KEY: str
    
    # Google API Credentials (suporta Service Account JSON bruto ou OAuth2)
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REFRESH_TOKEN: Optional[str] = None
    GOOGLE_SENDER_EMAIL: Optional[str] = "ryanferrari@iatize-ia.com"
    
    # API Protection
    API_BEARER_TOKEN: str
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Singleton do Supabase Master
supabase_master: Client = create_client(
    settings.SUPABASE_MASTER_URL,
    settings.SUPABASE_MASTER_SERVICE_KEY
)

# Cache de conexões dos Supabases dos Clientes (multi-tenant)
# Mapeamento: client_id -> Client
_supabase_client_cache: Dict[str, Client] = {}

def get_client_config(client_id: str) -> Dict[str, Any]:
    """Busca as credenciais de um cliente na tabela Master client_configurations."""
    response = supabase_master.table("client_configurations")\
        .select("*")\
        .eq("client_id", client_id)\
        .maybe_single()\
        .execute()
    
    if response is None or not response.data:
        raise ValueError(f"Configuração para o cliente '{client_id}' não encontrada no Supabase Master.")
    
    return response.data

def get_supabase_client(client_id: str, use_service_role: bool = True) -> Client:
    """
    Retorna o cliente Supabase instanciado para o cliente específico.
    Utiliza cache para evitar múltiplas instanciation por processo.
    """
    cache_key = f"{client_id}_{'service' if use_service_role else 'anon'}"
    
    if cache_key not in _supabase_client_cache:
        config = get_client_config(client_id)
        url = config["supabase_url"]
        key = config["supabase_service_key"] if use_service_role else config["supabase_anon_key"]
        
        _supabase_client_cache[cache_key] = create_client(url, key)
        
    return _supabase_client_cache[cache_key]

# Instanciação do Cliente do Google Calendar
def get_google_calendar_service():
    """
    Cria e retorna o serviço do Google Calendar API baseado na credencial de ryanferrari@iatize-ia.com.
    Tenta Service Account primeiro; se não configurado, cai para OAuth2 com Refresh Token.
    """
    scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = None

    # Opção 1: Service Account
    if settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            print(f"Erro ao carregar credenciais da Service Account do Google: {e}")

    # Opção 2: OAuth2 Refresh Token Flow
    if not creds and settings.GOOGLE_REFRESH_TOKEN:
        info = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": settings.GOOGLE_REFRESH_TOKEN,
        }
        creds = Credentials.from_authorized_user_info(info, scopes=scopes)
        
        # Atualiza o token caso esteja expirado
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
    if not creds:
        raise ValueError("Nenhuma credencial Google Calendar configurada em variáveis de ambiente (.env).")
        
    return build("calendar", "v3", credentials=creds)
