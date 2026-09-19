FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Instalar dependencias
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del backend y archivos estáticos/templates
COPY backend/ /app/

EXPOSE 8000

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}