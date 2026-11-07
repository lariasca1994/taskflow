"""Pruebas sin servicios externos: MongoDB se reemplaza por mongomock y el
correo se captura en memoria. Nunca se usa el .env real (las variables se
fijan antes de importar la app y python-dotenv no las sobrescribe)."""

import os
import sys
from pathlib import Path

import mongomock
import mongomock.gridfs
import pymongo
import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"

os.environ.update({
    "MONGO_URI": "mongodb://pruebas.invalid:27017",
    "DATABASE_NAME": "taskflow_pruebas",
    "JWT_SECRET": "secreto-de-pruebas-jwt-0123456789abcdef",
    "PASSWORD_PEPPER": "pimiento-de-pruebas-0123456789abcdef",
    "BREVO_API_KEY": "",
    "BREVO_REMITENTE": "",
    "URL_PUBLICA": "http://testserver",
})
pymongo.MongoClient = mongomock.MongoClient
mongomock.gridfs.enable_gridfs_integration()
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # las plantillas se cargan con ruta relativa

from fastapi.testclient import TestClient  # noqa: E402

from app import correo, database, mfa, repositorio  # noqa: E402
from app.main import app  # noqa: E402
from app.security import cifrar  # noqa: E402

CLAVE = "clave-de-prueba-123"


@pytest.fixture(autouse=True)
def base_limpia():
    for coleccion in database.base.list_collection_names():
        database.base.drop_collection(coleccion)
    yield


@pytest.fixture
def correos(monkeypatch):
    enviados: list[dict] = []

    def falso(destino, nombre, asunto, texto, html):
        enviados.append({"destino": destino, "asunto": asunto, "texto": texto})
        return True

    monkeypatch.setattr(correo, "enviar", falso)
    return enviados


@pytest.fixture
def cliente():
    return TestClient(app)


def crear_cuenta(email: str = "usuario@ejemplo.com") -> tuple[dict, str]:
    """Cuenta con app autenticadora activa. Devuelve (usuario, secreto TOTP)."""
    usuario = repositorio.crear_usuario("Prueba", email, cifrar(CLAVE))
    secreto = mfa.iniciar_totp(usuario)["secreto"]
    assert mfa.activar_totp(usuario, codigo_totp(secreto))
    return repositorio.buscar_usuario(str(usuario["_id"])), secreto


def codigo_totp(secreto: str, desfase: int = 0) -> str:
    import time

    return mfa._totp(secreto, int(time.time()) // 30 + desfase)
