"""Vista de solo lectura para el rol ADMIN.

Muestra las tareas de todos los usuarios para poder revisar el proyecto
de punta a punta, sin poder editar ni eliminar nada ajeno -- mismo
espiritu que /admin/pagos en PRPagos y el acceso de ADMIN en Gestor de
Casos QA.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import repositorio
from app.dependencias import usuario_admin_web

router = APIRouter()
plantillas = Jinja2Templates(directory="app/templates")


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
