"""Canal de eventos en vivo, uno por usuario.

Cuando ocurre algo relevante el servidor lo publica y los navegadores
conectados lo reciben sin haberlo pedido. Se usa Server-Sent Events y no
WebSockets porque el flujo es en un solo sentido y SSE reconecta solo.

Limitacion conocida: el registro de suscriptores vive en memoria del
proceso. Con un unico proceso de Uvicorn funciona; con varios
trabajadores haria falta un intermediario como Redis.
"""

import asyncio
import json
from collections import defaultdict

# usuario_id -> colas activas de ese usuario (una por pestana abierta)
_suscriptores: dict[str, set[asyncio.Queue]] = defaultdict(set)


def suscribir(usuario_id: str) -> asyncio.Queue:
    cola: asyncio.Queue = asyncio.Queue(maxsize=20)
    _suscriptores[usuario_id].add(cola)
    return cola


def cancelar(usuario_id: str, cola: asyncio.Queue) -> None:
    _suscriptores[usuario_id].discard(cola)
    if not _suscriptores[usuario_id]:
        _suscriptores.pop(usuario_id, None)


def publicar(usuario_id: str, tipo: str, datos: dict | None = None) -> None:
    """Envia un evento a todas las pestanas del usuario.

    Si una cola esta llena se descarta el mensaje en lugar de bloquear:
    un cliente lento no debe frenar la peticion que genero el evento.
    """
    mensaje = json.dumps({"tipo": tipo, "datos": datos or {}})

    for cola in list(_suscriptores.get(usuario_id, ())):
        try:
            cola.put_nowait(mensaje)
        except asyncio.QueueFull:
            pass


async def flujo(usuario_id: str, cola: asyncio.Queue):
    """Generador del cuerpo de la respuesta SSE."""
    try:
        yield "retry: 3000\n\n"

        while True:
            try:
                mensaje = await asyncio.wait_for(cola.get(), timeout=25)
                yield f"data: {mensaje}\n\n"
            except asyncio.TimeoutError:
                # Latido: mantiene viva la conexion frente a proxies que
                # cortan las conexiones inactivas.
                yield ": latido\n\n"
    finally:
        cancelar(usuario_id, cola)
