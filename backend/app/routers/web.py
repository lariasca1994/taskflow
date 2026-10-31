"""Paginas HTML y fragmentos para HTMX.

Los fragmentos devuelven solo el trozo de HTML que cambia; HTMX lo
inserta en su sitio. Es lo que permite tener una interfaz reactiva sin
escribir JavaScript propio.
"""

import html
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import analitica, correo, datos, eventos, mfa, repositorio
from app.config import COOKIE_SEGURA, RECUPERAR_MINUTOS, URL_PUBLICA
from app.dependencias import usuario_opcional, usuario_web
from app.esquemas import Estado
from app.security import (
    COOKIE_MFA,
    COOKIE_SESION,
    MFA_MINUTOS,
    cifrar,
    crear_token,
    crear_token_mfa,
    crear_token_recuperacion,
    huella_coincide,
    leer_token_mfa,
    leer_token_recuperacion,
    verificar_y_migrar,
)

router = APIRouter()
plantillas = Jinja2Templates(directory="app/templates")


def _sesion(respuesta: Response, usuario: dict) -> None:
    respuesta.set_cookie(
        COOKIE_SESION,
        crear_token(str(usuario["_id"]), usuario["email"]),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SEGURA,
        max_age=60 * 60 * 12,
    )


# ──────────────────────────────── acceso ──────────────────────────────


@router.get("/ingresar", response_class=HTMLResponse)
def form_login(request: Request):
    return plantillas.TemplateResponse(request, "login.html", {})


@router.post("/ingresar")
def procesar_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    usuario = repositorio.buscar_usuario_por_email(email)

    valido, hash_nuevo = (
        verificar_y_migrar(password, usuario["password"]) if usuario else (False, None)
    )

    if not valido:
        return plantillas.TemplateResponse(
            request,
            "login.html",
            {"error": "Correo o contrasena incorrectos", "email": email},
            status_code=401,
        )

    # Si la cuenta venia con el esquema anterior, se actualiza en silencio.
    if hash_nuevo:
        repositorio.actualizar_password(str(usuario["_id"]), hash_nuevo)

    if not usuario.get("activo", True):
        return plantillas.TemplateResponse(
            request, "login.html", {"error": "Esta cuenta está suspendida", "email": email}, status_code=403
        )
    # La contraseña sola no abre sesion: falta el segundo paso.
    if mfa.preferido(usuario) == "correo":
        mfa.enviar_codigo(usuario)
    return _pase_mfa(usuario)


@router.get("/registro", response_class=HTMLResponse)
def form_registro(request: Request):
    return plantillas.TemplateResponse(request, "registro.html", {})


@router.post("/registro")
def procesar_registro(
    request: Request,
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    if len(password) < 10:
        return plantillas.TemplateResponse(
            request,
            "registro.html",
            {
                "error": "La contrasena debe tener al menos 10 caracteres",
                "nombre": nombre,
                "email": email,
            },
            status_code=422,
        )

    usuario = repositorio.crear_usuario(nombre, email, cifrar(password))

    if not usuario:
        return plantillas.TemplateResponse(
            request,
            "registro.html",
            {"error": "Ese correo ya esta registrado", "nombre": nombre},
            status_code=409,
        )

    # La cuenta nueva elige su segundo paso antes de entrar.
    return _pase_mfa(usuario)


# ─────────────────────── verificación en dos pasos ───────────────────────


def _pase_mfa(usuario: dict) -> RedirectResponse:
    respuesta = RedirectResponse("/verificacion", status_code=303)
    respuesta.set_cookie(
        COOKIE_MFA, crear_token_mfa(str(usuario["_id"])),
        httponly=True, samesite="lax", secure=COOKIE_SEGURA, max_age=MFA_MINUTOS * 60,
    )
    return respuesta


def _usuario_en_verificacion(request: Request) -> dict | None:
    usuario_id = leer_token_mfa(request.cookies.get(COOKIE_MFA))
    usuario = repositorio.buscar_usuario(usuario_id) if usuario_id else None
    return usuario if usuario and usuario.get("activo", True) else None


def _pantalla_mfa(request: Request, usuario: dict, metodo: str | None = None, status_code: int = 200, **contexto):
    if not mfa.configurado(usuario):
        return plantillas.TemplateResponse(request, "mfa_elegir.html", {"metodos": mfa.METODOS, **contexto},
                                           status_code=status_code)
    metodo = metodo if metodo in mfa.metodos_activos(usuario) else mfa.preferido(usuario)
    otros = [m for m in mfa.metodos_activos(usuario) if m != metodo]
    return plantillas.TemplateResponse(
        request, "mfa_verificar.html",
        {"metodo": metodo, "otro": otros[0] if otros else None, "metodos": mfa.METODOS,
         "email": usuario["email"], **contexto},
        status_code=status_code,
    )


def _vencido() -> RedirectResponse:
    return RedirectResponse("/ingresar", status_code=303)


@router.get("/verificacion", response_class=HTMLResponse)
def form_verificacion(request: Request, metodo: str | None = None):
    usuario = _usuario_en_verificacion(request)
    return _pantalla_mfa(request, usuario, metodo) if usuario else _vencido()


@router.post("/verificacion", response_class=HTMLResponse)
def procesar_verificacion(request: Request, metodo: str = Form(...), codigo: str = Form(...)):
    usuario = _usuario_en_verificacion(request)
    if not usuario:
        return _vencido()
    if not mfa.verificar(usuario, metodo, codigo):
        return _pantalla_mfa(request, usuario, metodo, error="El código no es correcto o ya venció.", status_code=401)
    respuesta = RedirectResponse("/tareas", status_code=303)
    respuesta.delete_cookie(COOKIE_MFA)
    _sesion(respuesta, usuario)
    return respuesta


@router.post("/verificacion/correo", response_class=HTMLResponse)
def reenviar_codigo(request: Request):
    usuario = _usuario_en_verificacion(request)
    if not usuario:
        return _vencido()
    if not mfa.enviar_codigo(usuario):
        return _pantalla_mfa(request, usuario, "correo", error="Pediste varios códigos seguidos. Espera unos minutos.")
    return _pantalla_mfa(request, usuario, "correo", exito=f"Te enviamos un código a {usuario['email']}.")


@router.post("/verificacion/configurar", response_class=HTMLResponse)
def configurar_metodo(request: Request, metodo: str = Form(...)):
    usuario = _usuario_en_verificacion(request)
    if not usuario:
        return _vencido()
    return _iniciar_metodo(request, usuario, metodo, "/verificacion/activar", "acceso")


@router.post("/verificacion/activar", response_class=HTMLResponse)
def activar_metodo(request: Request, metodo: str = Form(...), codigo: str = Form(...)):
    usuario = _usuario_en_verificacion(request)
    if not usuario:
        return _vencido()
    if mfa.configurado(usuario):  # ya tiene uno: este paso es solo para la primera vez
        return _pantalla_mfa(request, usuario)
    activado = mfa.activar_totp(usuario, codigo) if metodo == "totp" else mfa.activar_correo(usuario, codigo)
    if not activado:
        return _confirmar_metodo(request, usuario, metodo, "/verificacion/activar", "acceso",
                                 error="El código no es correcto o ya venció.")
    respuesta = RedirectResponse("/tareas", status_code=303)
    respuesta.delete_cookie(COOKIE_MFA)
    _sesion(respuesta, usuario)
    return respuesta


def _iniciar_metodo(request: Request, usuario: dict, metodo: str, accion: str, vista: str, **contexto):
    if metodo == "totp":
        return _confirmar_metodo(request, usuario, metodo, accion, vista, app=mfa.iniciar_totp(usuario), **contexto)
    if not mfa.enviar_codigo(usuario):
        contexto["error"] = "Pediste varios códigos seguidos. Espera unos minutos."
    return _confirmar_metodo(request, usuario, "correo", accion, vista, **contexto)


def _confirmar_metodo(request: Request, usuario: dict, metodo: str, accion: str, vista: str, **contexto):
    plantilla = "mfa_confirmar.html" if vista == "acceso" else "cuenta_seguridad.html"
    base = {"metodo": metodo, "accion": accion, "metodos": mfa.METODOS, "email": usuario["email"]}
    if vista != "acceso":
        base.update(_contexto_seguridad(usuario))
    return plantillas.TemplateResponse(request, plantilla, {**base, **contexto},
                                       status_code=401 if "error" in contexto else 200)


def _contexto_seguridad(usuario: dict) -> dict:
    return {"usuario": usuario, "activo": "cuenta", "activos": mfa.metodos_activos(usuario),
            "preferido": mfa.preferido(usuario)}


@router.get("/cuenta/seguridad", response_class=HTMLResponse)
def form_seguridad(request: Request, usuario: dict = Depends(usuario_web)):
    return plantillas.TemplateResponse(request, "cuenta_seguridad.html",
                                       {"metodos": mfa.METODOS, **_contexto_seguridad(usuario)})


@router.post("/cuenta/seguridad/agregar", response_class=HTMLResponse)
def agregar_metodo(request: Request, metodo: str = Form(...), usuario: dict = Depends(usuario_web)):
    if metodo not in mfa.METODOS or metodo in mfa.metodos_activos(usuario):
        return RedirectResponse("/cuenta/seguridad", status_code=303)
    return _iniciar_metodo(request, usuario, metodo, "/cuenta/seguridad/activar", "cuenta")


@router.post("/cuenta/seguridad/activar", response_class=HTMLResponse)
def activar_en_perfil(request: Request, metodo: str = Form(...), codigo: str = Form(...),
                      usuario: dict = Depends(usuario_web)):
    activado = mfa.activar_totp(usuario, codigo) if metodo == "totp" else mfa.activar_correo(usuario, codigo)
    if not activado:
        return _confirmar_metodo(request, usuario, metodo, "/cuenta/seguridad/activar", "cuenta",
                                 error="El código no es correcto o ya venció.")
    return plantillas.TemplateResponse(request, "cuenta_seguridad.html", {
        "metodos": mfa.METODOS, **_contexto_seguridad(usuario),
        "exito": f"{mfa.METODOS[metodo]} quedó activada como segundo paso.",
    })


@router.post("/cuenta/seguridad/preferido", response_class=HTMLResponse)
def cambiar_preferido(request: Request, metodo: str = Form(...), usuario: dict = Depends(usuario_web)):
    mfa.elegir_preferido(usuario, metodo)
    return RedirectResponse("/cuenta/seguridad", status_code=303)


# ─────────────────────── recuperar y cambiar contraseña ───────────────────────

_RESPUESTA_RECUPERAR = (
    "Si el correo pertenece a una cuenta, te enviamos un enlace para crear una contraseña nueva. "
    "Revisa tu bandeja (y la carpeta de spam)."
)
_ENVIOS_RECUPERAR: dict[str, list[float]] = {}
_CANDADO_RECUPERAR = threading.Lock()


def _puede_enviar(email: str) -> bool:
    """Máximo 3 enlaces cada 15 minutos por correo (no bloquea el ingreso)."""
    ahora = time.time()
    with _CANDADO_RECUPERAR:
        recientes = [t for t in _ENVIOS_RECUPERAR.get(email, []) if ahora - t < 15 * 60]
        if len(recientes) >= 3:
            _ENVIOS_RECUPERAR[email] = recientes
            return False
        _ENVIOS_RECUPERAR[email] = recientes + [ahora]
        return True


@router.get("/recuperar", response_class=HTMLResponse)
def form_recuperar(request: Request):
    return plantillas.TemplateResponse(request, "recuperar.html", {})


@router.post("/recuperar", response_class=HTMLResponse)
def procesar_recuperar(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    usuario = repositorio.buscar_usuario_por_email(email)
    if usuario and usuario.get("activo", True) and _puede_enviar(email):
        token = crear_token_recuperacion(str(usuario["_id"]), usuario["password"], RECUPERAR_MINUTOS)
        enlace = f"{URL_PUBLICA}/restablecer?token={token}"
        nombre = usuario.get("nombre", "")
        correo.enviar(
            usuario["email"], nombre, "Restablece tu contraseña · TaskFlow",
            f"Hola {nombre},\n\nPara crear una contraseña nueva abre este enlace (vence en "
            f"{RECUPERAR_MINUTOS} minutos y sirve una vez):\n\n{enlace}\n\n"
            "Si no fuiste tú, ignora este correo: tu contraseña no cambia.",
            f"<p>Hola {html.escape(nombre)},</p><p>Para crear una contraseña nueva en <strong>TaskFlow</strong>:</p>"
            f'<p><a href="{enlace}" style="background:#0e6b45;color:#fff;padding:10px 18px;border-radius:6px;'
            f'text-decoration:none">Crear contraseña nueva</a></p><p>El enlace vence en {RECUPERAR_MINUTOS} '
            "minutos y sirve una sola vez. Si no fuiste tú, ignora este correo.</p>",
        )
    return plantillas.TemplateResponse(request, "recuperar.html", {"exito": _RESPUESTA_RECUPERAR})


@router.get("/restablecer", response_class=HTMLResponse)
def form_restablecer(request: Request, token: str = ""):
    contexto = {"token": token}
    if not leer_token_recuperacion(token):
        contexto["error"] = "El enlace no es válido o ya venció. Pide uno nuevo."
    return plantillas.TemplateResponse(request, "restablecer.html", contexto)


@router.post("/restablecer", response_class=HTMLResponse)
def procesar_restablecer(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirmacion: str = Form(...),
):
    error = None
    leido = leer_token_recuperacion(token)
    usuario = repositorio.buscar_usuario(leido[0]) if leido else None
    if not usuario or not usuario.get("activo", True) or not huella_coincide(usuario["password"], leido[1]):
        error = "El enlace no es válido o ya venció. Pide uno nuevo."
    elif len(password) < 10:
        error = "La contraseña debe tener al menos 10 caracteres"
    elif password != confirmacion:
        error = "La confirmación no coincide"
    if error:
        return plantillas.TemplateResponse(
            request, "restablecer.html", {"token": token, "error": error}, status_code=400
        )
    repositorio.actualizar_password(str(usuario["_id"]), cifrar(password))
    return plantillas.TemplateResponse(
        request, "login.html", {"exito": "Tu contraseña quedó actualizada. Ya puedes ingresar.", "email": usuario["email"]}
    )


@router.get("/cuenta/contrasena", response_class=HTMLResponse)
def form_cambiar_contrasena(request: Request, usuario: dict = Depends(usuario_web)):
    return plantillas.TemplateResponse(request, "cuenta_contrasena.html", {"usuario": usuario, "activo": "cuenta"})


@router.post("/cuenta/contrasena", response_class=HTMLResponse)
def cambiar_contrasena(
    request: Request,
    actual: str = Form(...),
    password: str = Form(...),
    confirmacion: str = Form(...),
    usuario: dict = Depends(usuario_web),
):
    contexto = {"usuario": usuario, "activo": "cuenta"}
    valido, _ = verificar_y_migrar(actual, usuario["password"])
    if not valido:
        contexto["error"] = "La contraseña actual no es correcta"
    elif len(password) < 10:
        contexto["error"] = "La contraseña nueva debe tener al menos 10 caracteres"
    elif password != confirmacion:
        contexto["error"] = "La confirmación no coincide"
    elif password == actual:
        contexto["error"] = "La contraseña nueva debe ser distinta de la actual"
    if "error" in contexto:
        return plantillas.TemplateResponse(request, "cuenta_contrasena.html", contexto, status_code=400)
    repositorio.actualizar_password(str(usuario["_id"]), cifrar(password))
    contexto["exito"] = "Tu contraseña quedó actualizada."
    return plantillas.TemplateResponse(request, "cuenta_contrasena.html", contexto)


@router.post("/salir")
def salir(request: Request):
    """Cerrar sesion elimina los archivos subidos por el usuario."""
    token = request.cookies.get(COOKIE_SESION)

    if token:
        from app.security import leer_token

        carga = leer_token(token)
        if carga:
            datos.eliminar_todos(carga["sub"])

    respuesta = RedirectResponse("/ingresar", status_code=303)
    respuesta.delete_cookie(COOKIE_SESION)
    return respuesta


# ──────────────────────────────── tareas ──────────────────────────────


@router.get("/", response_class=HTMLResponse)
def inicio(request: Request, usuario: dict | None = Depends(usuario_opcional)):
    # La portada de acceso es la primera pantalla, igual que en el resto
    # del portafolio; con sesion abierta se va directo a las tareas.
    if usuario:
        return RedirectResponse("/tareas", status_code=303)
    return plantillas.TemplateResponse(request, "login.html", {})


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Los navegadores lo piden en la raiz aunque la pagina declare otro icono.
    return FileResponse("app/static/iconos/favicon.ico")


@router.get("/tareas", response_class=HTMLResponse)
def pagina_tareas(
    request: Request,
    estado: str | None = None,
    categoria: str | None = None,
    buscar: str | None = None,
    usuario: dict = Depends(usuario_web),
):
    uid = str(usuario["_id"])
    documentos = repositorio.listar_tareas(uid, estado, categoria, buscar)

    return plantillas.TemplateResponse(
        request,
        "tareas.html",
        {
            "usuario": usuario,
            "activo": "tareas",
            "tareas": [repositorio.a_salida(d) for d in documentos],
            "categorias": repositorio.categorias_de(uid),
            "filtro_estado": estado,
            "filtro_categoria": categoria,
            "buscar": buscar or "",
        },
    )


@router.post("/tareas", response_class=HTMLResponse)
def crear_tarea(
    request: Request,
    titulo: str = Form(...),
    descripcion: str = Form(""),
    categoria: str = Form("general"),
    prioridad: str = Form("media"),
    fecha_limite: str = Form(""),
    usuario: dict = Depends(usuario_web),
):
    limite = None
    if fecha_limite:
        try:
            limite = datetime.fromisoformat(fecha_limite)
        except ValueError:
            limite = None

    repositorio.crear_tarea(
        str(usuario["_id"]),
        {
            "titulo": titulo.strip(),
            "descripcion": descripcion.strip() or None,
            "categoria": (categoria.strip() or "general").lower(),
            "prioridad": prioridad,
            "fecha_limite": limite,
        },
    )

    eventos.publicar(str(usuario["_id"]), "tarea_creada")
    return _fragmento_lista(request, usuario)


@router.patch("/tareas/{tarea_id}/estado", response_class=HTMLResponse)
def alternar_estado(
    request: Request,
    tarea_id: str,
    estado: str,
    usuario: dict = Depends(usuario_web),
):
    repositorio.cambiar_estado(str(usuario["_id"]), tarea_id, Estado(estado))
    eventos.publicar(str(usuario["_id"]), "tarea_actualizada")
    return _fragmento_lista(request, usuario)


@router.delete("/tareas/{tarea_id}", response_class=HTMLResponse)
def borrar_tarea(request: Request, tarea_id: str, usuario: dict = Depends(usuario_web)):
    repositorio.eliminar_tarea(str(usuario["_id"]), tarea_id)
    eventos.publicar(str(usuario["_id"]), "tarea_eliminada")
    return _fragmento_lista(request, usuario)


def _fragmento_lista(request: Request, usuario: dict) -> HTMLResponse:
    uid = str(usuario["_id"])
    documentos = repositorio.listar_tareas(uid)

    return plantillas.TemplateResponse(
        request,
        "_lista.html",
        {
            "tareas": [repositorio.a_salida(d) for d in documentos],
            "usuario": usuario,
        },
    )


# ─────────────────────────────── analitica ────────────────────────────


def _contexto_analitica(
    usuario: dict,
    desde: str | None,
    hasta: str | None,
    categoria: str | None,
    prioridad: str | None,
) -> dict:
    uid = str(usuario["_id"])
    df = analitica.filtrar(analitica.cargar(uid), desde, hasta, categoria, prioridad)

    return {
        "kpi": analitica.indicadores(df),
        "tarjetas": analitica.tarjetas(df),
        "hallazgos": analitica.hallazgos(df),
        "grafico_estados": analitica.grafico_estados(df),
        "grafico_categorias": analitica.grafico_categorias(df),
        "grafico_evolucion": analitica.grafico_evolucion(df),
        "grafico_prioridades": analitica.grafico_prioridades(df),
    }


@router.get("/analitica", response_class=HTMLResponse)
def pagina_analitica(
    request: Request,
    desde: str | None = None,
    hasta: str | None = None,
    categoria: str | None = None,
    prioridad: str | None = None,
    usuario: dict = Depends(usuario_web),
):
    return plantillas.TemplateResponse(
        request,
        "analitica.html",
        {
            "usuario": usuario,
            "activo": "analitica",
            "categorias": repositorio.categorias_de(str(usuario["_id"])),
            "filtros": {
                "desde": desde or "",
                "hasta": hasta or "",
                "categoria": categoria or "",
                "prioridad": prioridad or "",
            },
            **_contexto_analitica(usuario, desde, hasta, categoria, prioridad),
        },
    )


@router.get("/analitica/panel", response_class=HTMLResponse)
def fragmento_analitica(
    request: Request,
    desde: str | None = None,
    hasta: str | None = None,
    categoria: str | None = None,
    prioridad: str | None = None,
    usuario: dict = Depends(usuario_web),
):
    """Bloque que HTMX reemplaza al cambiar un filtro o al llegar un evento."""
    return plantillas.TemplateResponse(
        request,
        "_panel.html",
        _contexto_analitica(usuario, desde, hasta, categoria, prioridad),
    )
