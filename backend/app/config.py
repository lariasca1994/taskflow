"""Configuracion cargada desde el .env de la raiz del proyecto."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")

MONGO_URI = os.getenv("MONGO_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME", "taskflow")

JWT_SECRET = os.getenv("JWT_SECRET")
PASSWORD_PEPPER = os.getenv("PASSWORD_PEPPER")
JWT_ALGORITMO = "HS256"
COOKIE_SESION = "taskflow_sesion"

SESION_INACTIVIDAD_MIN = int(os.getenv("SESION_INACTIVIDAD_MIN", "30"))
SESION_MAXIMA_HORAS = int(os.getenv("SESION_MAXIMA_HORAS", "12"))

ARCHIVO_MAX_MB = int(os.getenv("ARCHIVO_MAX_MB", "10"))
ARCHIVO_MAX_BYTES = ARCHIVO_MAX_MB * 1024 * 1024
ARCHIVO_MAX_FILAS = int(os.getenv("ARCHIVO_MAX_FILAS", "500000"))
ARCHIVOS_POR_USUARIO = int(os.getenv("ARCHIVOS_POR_USUARIO", "5"))
ARCHIVO_HORAS_VIDA = int(os.getenv("ARCHIVO_HORAS_VIDA", "24"))

EXTENSIONES = {".csv", ".xlsx", ".json"}

if not MONGO_URI:
    raise RuntimeError("Falta MONGO_URI en el archivo .env de la raiz del proyecto.")

_GENERAR = '  python -c "import secrets; print(secrets.token_urlsafe(48))"'

if not JWT_SECRET or JWT_SECRET.startswith("cambia-esto"):
    raise RuntimeError(f"Falta JWT_SECRET en el .env. Genera uno con:\n{_GENERAR}")

if not PASSWORD_PEPPER or PASSWORD_PEPPER.startswith("cambia-esto"):
    raise RuntimeError(f"Falta PASSWORD_PEPPER en el .env. Genera uno con:\n{_GENERAR}")

if PASSWORD_PEPPER == JWT_SECRET:
    raise RuntimeError(
        "PASSWORD_PEPPER y JWT_SECRET deben ser distintos: si se filtra uno, "
        "el otro debe seguir protegiendo su parte."
    )
