"""API REST. Documentada automaticamente en /docs."""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app import analitica, repositorio
from app.dependencias import usuario_api
from app.esquemas import (
    Estado,
    LoginEntrada,
    RegistroEntrada,
    TareaEntrada,
    TareaSalida,
    UsuarioSalida,
)
from app.security import COOKIE_SESION, cifrar, crear_token, verificar_y_migrar

router = APIRouter(prefix="/api")


# ───────────────────────────── autenticacion ──────────────────────────


@router.post("/auth/registro", response_model=UsuarioSalida, status_code=201)
def registro(datos: RegistroEntrada, respuesta: Response):
    usuario = repositorio.crear_usuario(
        datos.nombre, datos.email, cifrar(datos.password)
    )

    if not usuario:
        raise HTTPException(status_code=409, detail="Ese correo ya esta registrado")

    _abrir_sesion(respuesta, usuario)
    return _usuario_salida(usuario)


@router.post("/auth/login", response_model=UsuarioSalida)
def login(datos: LoginEntrada, respuesta: Response):
    usuario = repositorio.buscar_usuario_por_email(datos.email)

    valido, hash_nuevo = (
        verificar_y_migrar(datos.password, usuario["password"])
        if usuario
        else (False, None)
    )

    # Mismo mensaje exista o no la cuenta: revelar cual de las dos cosas
    # falla permitiria averiguar que correos estan registrados.
    if not valido:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    if hash_nuevo:
        repositorio.actualizar_password(str(usuario["_id"]), hash_nuevo)

    _abrir_sesion(respuesta, usuario)
    return _usuario_salida(usuario)


@router.post("/auth/salir", status_code=204)
def salir(respuesta: Response):
    respuesta.delete_cookie(COOKIE_SESION)


# ──────────────────────────────── tareas ──────────────────────────────


@router.get("/tareas", response_model=list[TareaSalida])
def listar(
    estado: Estado | None = None,
    categoria: str | None = None,
    usuario: dict = Depends(usuario_api),
):
    documentos = repositorio.listar_tareas(
        str(usuario["_id"]), estado.value if estado else None, categoria
    )
    return [repositorio.a_salida(d) for d in documentos]


@router.post("/tareas", response_model=TareaSalida, status_code=201)
def crear(datos: TareaEntrada, usuario: dict = Depends(usuario_api)):
    documento = repositorio.crear_tarea(str(usuario["_id"]), datos.model_dump())
    return repositorio.a_salida(documento)


@router.get("/tareas/{tarea_id}", response_model=TareaSalida)
def detalle(tarea_id: str, usuario: dict = Depends(usuario_api)):
    documento = repositorio.obtener_tarea(str(usuario["_id"]), tarea_id)
    if not documento:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return repositorio.a_salida(documento)


@router.patch("/tareas/{tarea_id}/estado", response_model=TareaSalida)
def cambiar_estado(
    tarea_id: str, estado: Estado, usuario: dict = Depends(usuario_api)
):
    documento = repositorio.cambiar_estado(str(usuario["_id"]), tarea_id, estado)
    if not documento:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return repositorio.a_salida(documento)


@router.delete("/tareas/{tarea_id}", status_code=204)
def eliminar(tarea_id: str, usuario: dict = Depends(usuario_api)):
    if not repositorio.eliminar_tarea(str(usuario["_id"]), tarea_id):
        raise HTTPException(status_code=404, detail="Tarea no encontrada")


# ─────────────────────────────── analitica ────────────────────────────


@router.get("/analitica/resumen")
def resumen(usuario: dict = Depends(usuario_api)):
    """Indicadores calculados con pandas."""
    return analitica.resumen_json(str(usuario["_id"]))


# ───────────────────────────────── apoyo ──────────────────────────────


def _abrir_sesion(respuesta: Response, usuario: dict) -> None:
    """La cookie es httponly: JavaScript no puede leer el token."""
    respuesta.set_cookie(
        COOKIE_SESION,
        crear_token(str(usuario["_id"]), usuario["email"]),
        httponly=True,
        samesite="lax",
        secure=False,  # poner en True al servir por HTTPS
        max_age=60 * 60 * 12,
    )


def _usuario_salida(usuario: dict) -> dict:
    return {
        "id": str(usuario["_id"]),
        "nombre": usuario["nombre"],
        "email": usuario["email"],
    }
