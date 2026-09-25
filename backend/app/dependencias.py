"""Identificacion del usuario en cada peticion."""

from fastapi import HTTPException, Request, status

from app import repositorio
from app.security import COOKIE_SESION, leer_token, renovar


class RedirigirAlLogin(Exception):
    """Senal para que las paginas manden al formulario de ingreso."""


def _resolver(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_SESION)
    if not token:
        return None

    carga = leer_token(token)
    if not carga:
        return None

    usuario = repositorio.buscar_usuario(carga["sub"])
    if not usuario:
        return None

    # Cuenta suspendida por un admin: se trata igual que "no autenticado",
    # sin importar que el token siga siendo valido. .get() porque los
    # documentos creados antes de este campo no lo tienen (se asumen activos).
    if not usuario.get("activo", True):
        return None

    # El middleware recogera este token para refrescar la cookie: es lo
    # que hace que la inactividad sea deslizante.
    request.state.token_renovado = renovar(carga)

    return usuario


def usuario_api(request: Request) -> dict:
    usuario = _resolver(request)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesion no valida o expirada",
        )
    return usuario


def usuario_web(request: Request) -> dict:
    usuario = _resolver(request)
    if not usuario:
        raise RedirigirAlLogin()
    return usuario


def usuario_opcional(request: Request) -> dict | None:
    """Como usuario_web, pero sin exigir sesion: para paginas publicas (la
    portada) que cambian un poco su llamado a la accion segun si ya
    iniciaste sesion, sin forzar el redireccionamiento a /ingresar."""
    return _resolver(request)


def es_admin(usuario: dict) -> bool:
    return usuario.get("rol") == "ADMIN"


def usuario_admin_web(request: Request) -> dict:
    """Como usuario_web, pero exige ademas el rol ADMIN.

    Da acceso al panel de administracion: revisar, editar y eliminar las
    tareas de cualquier usuario, y gestionar las cuentas (suspender,
    reactivar, eliminar). Mismo espiritu que /admin/pagos en PRPagos o
    proyecto_autorizado en Gestor de Casos QA, pero con permisos de
    escritura reales sobre los datos ajenos.
    """
    usuario = usuario_web(request)
    if not es_admin(usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta seccion es solo para administradores",
        )
    return usuario
