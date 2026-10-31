"""Registro de eventos de seguridad de las cuentas.

Guarda que paso, a que cuenta y cuando; nunca contrasenas, codigos ni datos
del equipo. Los eventos se depuran solos a los 15 dias (indice TTL).
Si la base no responde, el evento se pierde pero el ingreso sigue: la
auditoria nunca bloquea al usuario.
"""

import logging
from datetime import datetime, timezone

from app.database import base

INGRESO = "ingreso"
CLAVE_ERRADA = "clave_errada"
CODIGO_ERRADO = "codigo_errado"
CUENTA_BLOQUEADA = "cuenta_bloqueada"
CLAVE_CAMBIADA = "clave_cambiada"
RECUPERACION = "recuperacion_solicitada"
METODO_ACTIVADO = "metodo_activado"

RETENCION_DIAS = 15

eventos_seguridad = base["eventos_seguridad"]
_log = logging.getLogger(__name__)


def registrar(tipo: str, usuario: dict) -> None:
    try:
        eventos_seguridad.insert_one({
            "tipo": tipo,
            "usuario_id": str(usuario["_id"]),
            "fecha": datetime.now(timezone.utc),
        })
    except Exception:  # noqa: BLE001 - la auditoria no debe tumbar el ingreso
        _log.warning("No se pudo registrar el evento de seguridad %s", tipo)
