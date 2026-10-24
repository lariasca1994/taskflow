FROM python:3.12.15-slim
# Almacén de certificados del sistema sin las raíces que firmaron los intermedios
# comprometidos de eMudhra (octubre 2026): emSign y Comodo "AAA Certificate Services".
RUN if command -v update-ca-certificates > /dev/null; then \
        rm -f /usr/share/ca-certificates/mozilla/emSign_* /usr/share/ca-certificates/mozilla/Comodo_AAA_Services_root.crt \
        && update-ca-certificates --fresh > /dev/null 2>&1; \
    fi

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