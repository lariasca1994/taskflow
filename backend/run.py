"""
Arranque del servidor leyendo el puerto de la configuracion.

    python run.py

Existe para que el puerto viva en el .env y no en el comando: asi cada
proyecto del portafolio conserva el suyo sin depender de recordar un
parametro distinto en cada arranque.

Equivale a:
    uvicorn app.main:app --reload --port <APP_PORT>
"""

import os

import uvicorn

# Importar la configuracion carga el .env desde la raiz del proyecto.
from app import config  # noqa: F401

PUERTO = int(os.getenv("APP_PORT", "8100"))
HOST = os.getenv("APP_HOST", "127.0.0.1")
RECARGA = os.getenv("APP_RELOAD", "true").lower() == "true"

if __name__ == "__main__":
    print(f"\n  TaskFlow en http://{HOST}:{PUERTO}")
    print(f"  API      en http://{HOST}:{PUERTO}/docs\n")

    uvicorn.run("app.main:app", host=HOST, port=PUERTO, reload=RECARGA)