"""El nombre descriptivo "Gestor de tareas" aparece en todos los correos y en la app autenticadora."""

from urllib.parse import parse_qs, unquote, urlparse

from app import correo, mfa, repositorio
from app.security import cifrar
from conftest import CLAVE, crear_cuenta

NOMBRE = "Gestor de tareas"


def test_plantilla_de_correo_usa_el_nombre_visible():
    documento = correo.documento("Asunto", "<p>Hola</p>")
    assert documento.count(NOMBRE) == 2  # encabezado y pie
    assert "TaskFlow" not in documento


def test_todos_los_asuntos_llevan_el_nombre_visible(cliente, correos):
    usuario = repositorio.crear_usuario("Prueba", "usuario@ejemplo.com", cifrar(CLAVE))
    mfa.enviar_codigo(usuario)                       # código de acceso
    cliente.post("/recuperar", data={"email": "usuario@ejemplo.com"})  # olvidé mi contraseña
    mfa.enviar_codigo_recuperacion(usuario)          # perdí mi autenticador
    assert len(correos) == 3
    for enviado in correos:
        assert enviado["asunto"].endswith(f"· {NOMBRE}")
        assert "TaskFlow" not in enviado["asunto"] + enviado["texto"]


def test_emisor_del_qr_es_el_nombre_visible():
    usuario, _ = crear_cuenta()
    uri = urlparse(mfa.iniciar_totp(usuario)["uri"])
    assert unquote(uri.path).lstrip("/").startswith(f"{NOMBRE}:")
    assert parse_qs(uri.query)["issuer"] == [NOMBRE]


def test_cambiar_el_emisor_no_invalida_la_app_ya_configurada():
    # El secreto se descifra igual y los códigos de la app existente siguen sirviendo.
    usuario, secreto = crear_cuenta()
    from conftest import codigo_totp

    assert mfa.verificar(usuario, "totp", codigo_totp(secreto, 1))
