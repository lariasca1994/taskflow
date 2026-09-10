"""Modulo de analisis de archivos: paginas y fragmentos HTMX."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import datos, eventos, graficos
from app.config import ARCHIVO_MAX_BYTES, ARCHIVO_MAX_MB, EXTENSIONES
from app.dependencias import usuario_web

router = APIRouter(prefix="/datos")
plantillas = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def pagina(request: Request, usuario: dict = Depends(usuario_web)):
    return plantillas.TemplateResponse(
        request,
        "datos.html",
        {
            "usuario": usuario,
            "activo": "datos",
            "datasets": datos.listar(str(usuario["_id"])),
            "max_mb": ARCHIVO_MAX_MB,
        },
    )


@router.post("", response_class=HTMLResponse)
async def subir(
    request: Request,
    archivo: UploadFile = File(...),
    usuario: dict = Depends(usuario_web),
):
    uid = str(usuario["_id"])
    extension = Path(archivo.filename or "").suffix.lower()
    error = None

    if extension not in EXTENSIONES:
        error = f"Formato no admitido. Se aceptan {', '.join(sorted(EXTENSIONES))}."
    else:
        contenido = await archivo.read()

        if len(contenido) > ARCHIVO_MAX_BYTES:
            error = f"El archivo pesa mas de {ARCHIVO_MAX_MB} MB."
        else:
            try:
                documento = datos.registrar(uid, archivo.filename, contenido, extension)
                eventos.publicar(uid, "dataset_listo", {"nombre": documento["nombre"]})
            except datos.ErrorDeArchivo as fallo:
                error = str(fallo)

    return plantillas.TemplateResponse(
        request,
        "_datasets.html",
        {
            "datasets": datos.listar(uid),
            "error": error,
            "max_mb": ARCHIVO_MAX_MB,
        },
    )


@router.delete("/{dataset_id}", response_class=HTMLResponse)
def eliminar(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    uid = str(usuario["_id"])
    datos.eliminar(uid, dataset_id)
    eventos.publicar(uid, "dataset_eliminado")

    return plantillas.TemplateResponse(
        request,
        "_datasets.html",
        {"datasets": datos.listar(uid), "max_mb": ARCHIVO_MAX_MB},
    )


@router.get("/{dataset_id}", response_class=HTMLResponse)
def explorar(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    documento = datos.obtener(str(usuario["_id"]), dataset_id)

    if not documento:
        return RedirectResponse("/datos", status_code=303)

    detalle = documento["perfil"]["detalle"]

    return plantillas.TemplateResponse(
        request,
        "explorador.html",
        {
            "usuario": usuario,
            "activo": "datos",
            "dataset": documento,
            "perfil": documento["perfil"],
            "columnas": [c["nombre"] for c in detalle],
            "numericas": [c["nombre"] for c in detalle if c["tipo"] == "numerica"],
            "tipos": graficos.TIPOS,
            "agregaciones": graficos.AGREGACIONES,
        },
    )


@router.get("/{dataset_id}/grafico", response_class=HTMLResponse)
def grafico(
    request: Request,
    dataset_id: str,
    tipo: str = "barras",
    dimension: str = "",
    medida: str = "",
    funcion: str = "conteo",
    usuario: dict = Depends(usuario_web),
):
    """Fragmento que HTMX recarga cada vez que cambia un control."""
    documento = datos.obtener(str(usuario["_id"]), dataset_id)

    if not documento or not dimension:
        return HTMLResponse(graficos.vacio("Elige una columna para empezar"))

    # Se leen solo las columnas necesarias: es la ventaja de Parquet.
    requeridas = [c for c in {dimension, medida} if c]
    tabla = datos.cargar_tabla(documento, columnas=requeridas)

    return HTMLResponse(
        graficos.construir(tabla, tipo, dimension, medida or None, funcion)
    )


@router.get("/{dataset_id}/vista", response_class=HTMLResponse)
def vista_previa(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    documento = datos.obtener(str(usuario["_id"]), dataset_id)

    if not documento:
        return HTMLResponse("")

    tabla = datos.cargar_tabla(documento).head(20)

    return plantillas.TemplateResponse(
        request,
        "_vista_previa.html",
        {
            "columnas": list(tabla.columns),
            "filas": tabla.astype(str).values.tolist(),
        },
    )
