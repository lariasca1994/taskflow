"""Recuperación de cuenta: "Olvidé mi contraseña" y "Perdí mi autenticador"."""

import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import database, mfa, repositorio
from app.config import RECUPERAR_MINUTOS
from app.main import app
from app.security import COOKIE_SESION, crear_token_recuperacion
from conftest import CLAVE, codigo_totp, crear_cuenta


def _codigo(correo: dict) -> str:
    return re.search(r"\b(\d{6})\b", correo["texto"]).group(1)


def _enlace(correo: dict) -> str:
    return re.search(r"token=([\w\-.]+)", correo["texto"]).group(1)


def _ingresar(cliente: TestClient, email: str = "usuario@ejemplo.com", clave: str = CLAVE):
    return cliente.post("/ingresar", data={"email": email, "password": clave}, follow_redirects=False)


def _sesion_completa(cliente: TestClient, secreto: str, desfase: int = 1) -> None:
    assert _ingresar(cliente).status_code == 303
    r = cliente.post("/verificacion", data={"metodo": "totp", "codigo": codigo_totp(secreto, desfase)},
                     follow_redirects=False)
    assert r.headers["location"] == "/tareas"


# ─────────────────────────── olvidé mi contraseña ───────────────────────────


def test_recuperar_responde_igual_exista_o_no_la_cuenta(cliente, correos):
    crear_cuenta()
    existe = cliente.post("/recuperar", data={"email": "usuario@ejemplo.com"})
    no_existe = cliente.post("/recuperar", data={"email": "nadie@ejemplo.com"})
    assert existe.status_code == no_existe.status_code == 200
    mensaje = "Si el correo pertenece a una cuenta"
    assert mensaje in existe.text and mensaje in no_existe.text
    assert [c["destino"] for c in correos] == ["usuario@ejemplo.com"]


def test_enlace_de_un_solo_uso_cierra_sesiones_y_conserva_mfa(cliente, correos):
    usuario, secreto = crear_cuenta()
    otro_equipo = TestClient(app)
    _sesion_completa(otro_equipo, secreto)
    assert otro_equipo.get("/tareas", follow_redirects=False).status_code == 200

    cliente.post("/recuperar", data={"email": "usuario@ejemplo.com"})
    token = _enlace(correos[-1])
    pantalla = cliente.get(f"/restablecer?token={token}")
    # Paso 2: solo contraseña nueva y su confirmación.
    assert set(re.findall(r'type="password" id="(\w+)"', pantalla.text)) == {"password", "confirmacion"}

    nueva = "otra-clave-segura-456"
    r = cliente.post("/restablecer", data={"token": token, "password": nueva, "confirmacion": nueva})
    assert "quedó actualizada" in r.text

    # El mismo enlace ya no sirve.
    r = cliente.post("/restablecer", data={"token": token, "password": "tercera-clave-789",
                                           "confirmacion": "tercera-clave-789"})
    assert r.status_code == 400 and "no es válido" in r.text

    # La sesión abierta con la contraseña anterior quedó cerrada.
    assert otro_equipo.get("/tareas", follow_redirects=False).status_code != 200

    # La verificación en dos pasos sigue activa: la contraseña sola no abre sesión.
    nuevo = TestClient(app)
    r = _ingresar(nuevo, clave=nueva)
    assert r.headers["location"] == "/verificacion"
    assert nuevo.get("/tareas", follow_redirects=False).status_code != 200
    assert mfa.metodos_activos(repositorio.buscar_usuario(str(usuario["_id"]))) == ["totp"]


def test_enlace_vencido_y_confirmacion_distinta(cliente, correos):
    usuario, _ = crear_cuenta()
    vencido = crear_token_recuperacion(str(usuario["_id"]), usuario["password"], -1)
    assert "no es válido" in cliente.get(f"/restablecer?token={vencido}").text

    vigente = crear_token_recuperacion(str(usuario["_id"]), usuario["password"], RECUPERAR_MINUTOS)
    r = cliente.post("/restablecer", data={"token": vigente, "password": "clave-larga-001",
                                           "confirmacion": "clave-larga-002"})
    assert r.status_code == 400 and "no coincide" in r.text


def test_cambiar_contrasena_cierra_otras_sesiones_y_mantiene_la_actual(correos):
    usuario, secreto = crear_cuenta()
    actual, otro = TestClient(app), TestClient(app)
    _sesion_completa(actual, secreto, 1)
    # El mismo código TOTP no se acepta dos veces: se simula el siguiente ingreso.
    database.usuarios.update_one({"_id": usuario["_id"]}, {"$set": {"mfa.ultimo_paso": 0}})
    _sesion_completa(otro, secreto, 1)
    nueva = "clave-cambiada-999"
    r = actual.post("/cuenta/contrasena", data={"actual": CLAVE, "password": nueva, "confirmacion": nueva})
    assert "quedó actualizada" in r.text
    assert actual.get("/tareas", follow_redirects=False).status_code == 200
    assert otro.get("/tareas", follow_redirects=False).status_code != 200


# ─────────────────────────── perdí mi autenticador ───────────────────────────


def test_enlace_siempre_visible_en_la_verificacion(cliente):
    crear_cuenta()
    _ingresar(cliente)
    assert "Perdí mi autenticador" in cliente.get("/verificacion").text


def test_perdi_autenticador_envia_codigo_aunque_correo_no_este_activo(cliente, correos):
    usuario, secreto_viejo = crear_cuenta()
    assert "correo" not in mfa.metodos_activos(usuario)
    _ingresar(cliente)

    r = cliente.post("/verificacion/perdi-autenticador")
    assert r.status_code == 200 and "Vence en 15 minutos" in r.text
    assert correos[-1]["destino"] == "usuario@ejemplo.com"

    # El código correcto lleva a configurar la app nueva (QR), todavía sin sesión.
    r = cliente.post("/verificacion/recuperar", data={"codigo": _codigo(correos[-1])})
    assert "Configura tu app autenticadora nueva" in r.text and "<svg" in r.text
    assert cliente.get("/tareas", follow_redirects=False).status_code != 200
    secreto_nuevo = re.search(r'class="mfa-clave">(\w+)<', r.text).group(1)

    r = cliente.post("/verificacion/reemplazar", data={"codigo": codigo_totp(secreto_nuevo, 1)},
                     follow_redirects=False)
    assert r.headers["location"] == "/tareas"
    assert cliente.get("/tareas", follow_redirects=False).status_code == 200

    # La app anterior dejó de servir y la nueva queda registrada.
    usuario = repositorio.buscar_usuario(str(usuario["_id"]))
    assert not mfa.verificar(usuario, "totp", codigo_totp(secreto_viejo, 1))
    assert mfa.metodos_activos(usuario) == ["totp"]


def test_codigo_de_recuperacion_es_de_un_solo_uso_y_vence(cliente, correos):
    usuario, _ = crear_cuenta()
    _ingresar(cliente)
    cliente.post("/verificacion/perdi-autenticador")
    codigo = _codigo(correos[-1])
    database.usuarios.update_one({"_id": usuario["_id"]}, {"$set": {
        "mfa.recuperacion.expira": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    r = cliente.post("/verificacion/recuperar", data={"codigo": codigo})
    assert r.status_code == 401

    cliente.post("/verificacion/perdi-autenticador")
    codigo = _codigo(correos[-1])
    assert "Configura tu app" in cliente.post("/verificacion/recuperar", data={"codigo": codigo}).text
    _ingresar(cliente)
    assert cliente.post("/verificacion/recuperar", data={"codigo": codigo}).status_code == 401


def test_limite_de_envios(cliente, correos):
    crear_cuenta()
    _ingresar(cliente)
    for _ in range(3):
        assert cliente.post("/verificacion/perdi-autenticador").status_code == 200
    r = cliente.post("/verificacion/perdi-autenticador")
    assert r.status_code == 429 and len(correos) == 3


def test_cinco_codigos_errados_bloquean_quince_minutos(cliente, correos):
    usuario, _ = crear_cuenta()
    _ingresar(cliente)
    cliente.post("/verificacion/perdi-autenticador")
    bueno = _codigo(correos[-1])
    malo = "000000" if bueno != "000000" else "111111"
    for _ in range(4):
        assert cliente.post("/verificacion/recuperar", data={"codigo": malo}).status_code == 401
    assert cliente.post("/verificacion/recuperar", data={"codigo": malo}).status_code == 429
    # Bloqueada: ni el código bueno ni uno nuevo sirven durante el bloqueo.
    assert cliente.post("/verificacion/recuperar", data={"codigo": bueno}).status_code == 429
    assert cliente.post("/verificacion/perdi-autenticador").status_code == 429
    restante = repositorio.buscar_usuario(str(usuario["_id"]))["mfa"]["rec_bloqueo_hasta"]
    import time
    assert 14 * 60 < restante - time.time() <= 15 * 60


def test_reemplazar_exige_haber_verificado_el_correo(cliente):
    _, _ = crear_cuenta()
    _ingresar(cliente)
    r = cliente.post("/verificacion/reemplazar", data={"codigo": "123456"}, follow_redirects=False)
    assert r.status_code == 200 and "Escribe tu código" in r.text
    assert COOKIE_SESION not in r.cookies
