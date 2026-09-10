"""Punto de entrada de TaskFlow."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import datos
from app.config import COOKIE_SESION, SESION_MAXIMA_HORAS
from app.database import cliente, preparar_indices
from app.dependencias import RedirigirAlLogin
from app.routers import admin, api, datasets, eventos, web

registro = logging.getLogger("taskflow")


async def _barrido_periodico() -> None:
    """Elimina cada hora los archivos sin uso reciente.

    Hace falta porque casi nadie pulsa "Salir": sin este barrido, los
    archivos de quien cierra la pestana quedarian huerfanos para siempre.
    """
    while True:
        try:
            borrados = await asyncio.to_thread(datos.barrer_caducados)
            if borrados:
                registro.info("Barrido: %s archivos caducados eliminados", borrados)
        except Exception as error:
            registro.warning("Fallo el barrido de archivos: %s", error)

        await asyncio.sleep(3600)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    preparar_indices()
    tarea = asyncio.create_task(_barrido_periodico())

    yield

    tarea.cancel()
    cliente.close()


app = FastAPI(
    title="TaskFlow API",
    version="1.0.0",
    description="Gestion de tareas personales con analitica en pandas.",
    lifespan=ciclo_de_vida,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(admin.router)
app.include_router(api.router)
app.include_router(datasets.router)
app.include_router(eventos.router)
app.include_router(web.router)


@app.exception_handler(RedirigirAlLogin)
async def sin_sesion(request: Request, exc: RedirigirAlLogin):
    """Las paginas mandan al login; la API responde 401 por su cuenta."""
    return RedirectResponse("/ingresar?expirada=1", status_code=303)


@app.middleware("http")
async def sesion_y_cabeceras(request: Request, call_next):
    respuesta = await call_next(request)

    # Inactividad deslizante: si la peticion venia autenticada, se emite
    # una cookie nueva con el contador reiniciado.
    token = getattr(request.state, "token_renovado", None)
    if token:
        respuesta.set_cookie(
            COOKIE_SESION,
            token,
            httponly=True,
            samesite="lax",
            secure=False,  # poner en True al servir por HTTPS
            max_age=SESION_MAXIMA_HORAS * 3600,
        )

    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "SAMEORIGIN"
    respuesta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return respuesta


@app.get("/api/health", tags=["sistema"])
def health_check():
    """Confirma que la API puede comunicarse con MongoDB."""
    try:
        cliente.admin.command("ping")
    except Exception as error:
        raise HTTPException(status_code=503, detail="MongoDB no esta disponible") from error

    return {"status": "ok", "database": "connected"}
