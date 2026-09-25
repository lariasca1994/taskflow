"""Panel del rol ADMIN.

Muestra las tareas y las cuentas de todos los usuarios para poder revisar
el proyecto de punta a punta, y permite editar o eliminar tareas ajenas y
suspender/reactivar/eliminar cuentas -- mismo espiritu que /admin/pagos en
PRPagos y el acceso de ADMIN en Gestor de Casos QA, pero con permisos de
escritura reales.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import repositorio
from app.dependencias import usuario_admin_web
from app.esquemas import Estado

router = APIRouter()
plantillas = Jinja2Templates(directory="app/templates")


# ──────────────────────────────── tareas ───────────────────────────────


@router.get("/admin/tareas", response_class=HTMLResponse)
def panel_admin(request: Request, usuario: dict = Depends(usuario_admin_web)):
    documentos = repositorio.listar_todas_las_tareas()

    return plantillas.TemplateResponse(
        request,
        "admin_tareas.html",
        {
            "usuario": usuario,
            "activo": "admin",
            "tareas": [repositorio.a_salida_admin(d) for d in documentos],
            "total_usuarios": repositorio.contar_usuarios(),
        },
    )


@router.post("/admin/tareas/{tarea_id}/editar")
def admin_editar_tarea(
    tarea_id: str,
    titulo: str = Form(...),
    descripcion: str = Form(""),
    estado: str = Form(...),
    usuario: dict = Depends(usuario_admin_web),
):
    repositorio.admin_actualizar_tarea(
        tarea_id,
        {
            "titulo": titulo.strip(),
            "descripcion": descripcion.strip() or None,
            "estado": Estado(estado).value,
        },
    )
    return RedirectResponse("/admin/tareas", status_code=303)


@router.post("/admin/tareas/{tarea_id}/estado")
def admin_cambiar_estado_tarea(
    tarea_id: str,
    estado: str = Form(...),
    usuario: dict = Depends(usuario_admin_web),
):
    repositorio.admin_cambiar_estado(tarea_id, Estado(estado))
    return RedirectResponse("/admin/tareas", status_code=303)


@router.post("/admin/tareas/{tarea_id}/eliminar")
def admin_eliminar_tarea(tarea_id: str, usuario: dict = Depends(usuario_admin_web)):
    repositorio.admin_eliminar_tarea(tarea_id)
    return RedirectResponse("/admin/tareas", status_code=303)


# ─────────────────────────────── usuarios ──────────────────────────────


@router.get("/admin/usuarios", response_class=HTMLResponse)
def panel_usuarios(request: Request, usuario: dict = Depends(usuario_admin_web)):
    documentos = repositorio.listar_usuarios()

    return plantillas.TemplateResponse(
        request,
        "admin_usuarios.html",
        {
            "usuario": usuario,
            "activo": "admin_usuarios",
            "usuarios": [repositorio.usuario_a_salida(d) for d in documentos],
        },
    )


@router.post("/admin/usuarios/{usuario_id}/suspender")
def admin_suspender_usuario(
    usuario_id: str, usuario: dict = Depends(usuario_admin_web)
):
    if usuario_id == str(usuario["_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No podes suspender tu propia cuenta",
        )
    repositorio.suspender_usuario(usuario_id)
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/admin/usuarios/{usuario_id}/reactivar")
def admin_reactivar_usuario(
    usuario_id: str, usuario: dict = Depends(usuario_admin_web)
):
    repositorio.reactivar_usuario(usuario_id)
    return RedirectResponse("/admin/usuarios", status_code=303)


@router.post("/admin/usuarios/{usuario_id}/eliminar")
def admin_eliminar_usuario(usuario_id: str, usuario: dict = Depends(usuario_admin_web)):
    if usuario_id == str(usuario["_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No podes eliminar tu propia cuenta",
        )
    repositorio.eliminar_usuario(usuario_id)
    return RedirectResponse("/admin/usuarios", status_code=303)
