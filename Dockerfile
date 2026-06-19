FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema necessárias para pacotes Python (se houver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar os requerimentos e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código fonte para o container
COPY . .

# Expor a porta que a API FastAPI utilizará
EXPOSE 8000

# Comando padrão de inicialização (substituído no docker-compose para o worker)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
