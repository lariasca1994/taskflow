"""Envío de correos con la API de Brevo (solo texto + HTML, sin adjuntos).

Sin BREVO_API_KEY (desarrollo) no envía nada: escribe el mensaje en el log.
"""

import json
import logging
import urllib.request

from app.config import BREVO_API_KEY, BREVO_REMITENTE

logger = logging.getLogger("taskflow.correo")


def enviar(destino: str, nombre: str, asunto: str, texto: str, html: str) -> bool:
    if not BREVO_API_KEY or not BREVO_REMITENTE:
        logger.info("[correo local] Para %s | %s\n%s", destino, asunto, texto)
        return False
    cuerpo = json.dumps({
        "sender": {"email": BREVO_REMITENTE, "name": "TaskFlow"},
        "to": [{"email": destino, "name": nombre}],
        "subject": asunto,
        "textContent": texto,
        "htmlContent": html,
    }).encode("utf-8")
    pedido = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=cuerpo,
        headers={"api-key": BREVO_API_KEY, "content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=20) as respuesta:
            return 200 <= respuesta.status < 300
    except Exception:  # el usuario recibe la misma respuesta genérica igual
        logger.exception("Brevo no aceptó el correo")
        return False
