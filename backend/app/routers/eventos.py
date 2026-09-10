"""Canal de eventos en vivo."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import eventos
from app.dependencias import usuario_web

router = APIRouter()


@router.get("/eventos")
async def canal(request: Request, usuario: dict = Depends(usuario_web)):
    """Server-Sent Events.

    EventSource no admite cabeceras propias, de modo que la autenticacion
    viaja necesariamente en la cookie de sesion. Es justo la razon por la
    que la sesion se guarda asi y no en almacenamiento del navegador.
    """
    uid = str(usuario["_id"])
    cola = eventos.suscribir(uid)

    return StreamingResponse(
        eventos.flujo(uid, cola),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # evita el buffering de nginx
        },
    )
