"""Envío de correos con la API de Brevo (solo texto + HTML, sin adjuntos).

Sin BREVO_API_KEY (desarrollo) no envía nada: escribe el mensaje en el log.
"""

import html
import json
import logging
import urllib.request

from app.config import BREVO_API_KEY, BREVO_REMITENTE, URL_PUBLICA

logger = logging.getLogger("taskflow.correo")


# Paleta del sitio (static/acceso.css): el correo se ve como la aplicación.
_C = {
    "fondo": "#F6FAF8", "superficie": "#FFFFFF", "borde": "#DCE7E2", "texto": "#0F172A",
    "suave": "#5B6B66", "acento": "#0B7360", "cabecera": "#E4F3EE", "cabecera_texto": "#062B23",
}
_FUENTE = "Inter,system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif"


def documento(asunto: str, contenido: str) -> str:
    """Envuelve el contenido del correo con la cabecera, el logo y los colores del sitio."""
    c = _C
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(asunto)}</title></head>"
        f'<body style="margin:0;padding:0;background:{c["fondo"]};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{c["fondo"]};padding:24px 12px;"><tr><td align="center">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:{c["superficie"]};'
        f'border:1px solid {c["borde"]};border-radius:12px;overflow:hidden;font-family:{_FUENTE};color:{c["texto"]};">'
        f'<tr><td style="background:{c["cabecera"]};border-top:4px solid {c["acento"]};padding:16px 28px;">'
        f'<img src="{URL_PUBLICA}/static/iconos/apple-touch-icon.png" width="28" height="28" alt="" '
        'style="vertical-align:middle;border:0;border-radius:6px;margin-right:10px;">'
        f'<span style="vertical-align:middle;font-size:17px;font-weight:700;color:{c["cabecera_texto"]};">TaskFlow</span></td></tr>'
        f'<tr><td style="padding:24px 28px 12px;font-size:15px;line-height:1.6;color:{c["texto"]};">{contenido}</td></tr>'
        f'<tr><td style="padding:16px 28px 22px;border-top:1px solid {c["borde"]};font-size:12px;line-height:1.5;color:{c["suave"]};">'
        "Correo automático de TaskFlow. Si no esperabas este mensaje, puedes ignorarlo.</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def enviar(destino: str, nombre: str, asunto: str, texto: str, html: str) -> bool:
    if not BREVO_API_KEY or not BREVO_REMITENTE:
        logger.info("[correo local] Para %s | %s\n%s", destino, asunto, texto)
        return False
    cuerpo = json.dumps({
        "sender": {"email": BREVO_REMITENTE, "name": "TaskFlow"},
        "to": [{"email": destino, "name": nombre}],
        "subject": asunto,
        "textContent": texto,
        "htmlContent": documento(asunto, html),
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
