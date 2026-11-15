"""Interfaz: menú lateral, aplicación instalable (PWA) y página 404 propia."""

from conftest import codigo_totp, crear_cuenta, CLAVE


def _sesion(cliente):
    _usuario, secreto = crear_cuenta()
    assert cliente.post("/ingresar", data={"email": "usuario@ejemplo.com", "password": CLAVE}, follow_redirects=False).status_code == 303
    r = cliente.post("/verificacion", data={"metodo": "totp", "codigo": codigo_totp(secreto, 1)}, follow_redirects=False)
    assert r.headers["location"] == "/tareas"


def test_menu_lateral_con_las_mismas_opciones(cliente):
    _sesion(cliente)
    html = cliente.get("/tareas").text
    assert 'class="menu-nav"' in html
    for enlace in ['href="/tareas"', 'href="/analitica"', 'href="/datos"', 'href="/cuenta/contrasena"', 'href="/cuenta/seguridad"', 'href="/docs"']:
        assert enlace in html, enlace
    assert html.count('action="/salir"') == 2  # menú y hoja "Más"
    assert 'class="hoja-mas"' in html and 'id="pulso-vivo"' in html
    assert 'aria-current="page"' in html
    assert 'href="/admin/tareas"' not in html  # solo el administrador


def test_sin_sesion_conserva_la_barra_superior(cliente):
    html = cliente.get("/ingresar").text
    assert "menu-nav" not in html


def test_pwa_service_worker_manifiesto_y_sin_conexion(cliente):
    sw = cliente.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    assert sw.headers["cache-control"] == "no-cache"
    assert '"/tareas"' not in sw.text and '"/eventos"' not in sw.text  # nunca páginas con datos ni SSE
    manifiesto = cliente.get("/manifest.webmanifest")
    assert manifiesto.status_code == 200 and manifiesto.json()["display"] == "standalone"
    for icono in manifiesto.json()["icons"]:
        assert cliente.get(icono["src"]).status_code == 200
    sin_red = cliente.get("/offline.html")
    assert sin_red.status_code == 200 and "Sin conexión" in sin_red.text


def test_404_propia_y_api_intacta(cliente):
    r = cliente.get("/no-existe-esta-ruta")
    assert r.status_code == 404
    assert "Esta tarea no está en el tablero" in r.text and "/no-existe-esta-ruta" in r.text
    api = cliente.get("/api/no-existe")
    assert api.status_code == 404 and api.headers["content-type"].startswith("application/json")
