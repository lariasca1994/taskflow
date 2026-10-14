"""Modulo de analisis de archivos: paginas y fragmentos HTMX."""

import io
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from markupsafe import escape

from app import dax, datos, eventos, generador, graficos, tablero
from app.config import ARCHIVO_HORAS_VIDA, ARCHIVO_MAX_BYTES, ARCHIVO_MAX_MB, ARCHIVOS_POR_USUARIO, EXTENSIONES
from app.dependencias import usuario_web

router = APIRouter(prefix="/datos")
plantillas = Jinja2Templates(directory="app/templates")
plantillas.env.filters["cifra"] = tablero.cifra
plantillas.env.filters["dax"] = dax.resaltar
plantillas.env.filters["miles"] = lambda v: f"{v:,}".replace(",", ".")

SECCIONES = {
    "resumen": "Resumen ejecutivo",
    "pivote": "Tabla dinámica",
    "medidas": "Medidas DAX",
    "explorador": "Explorador",
    "origen": "Origen y calidad",
}


def _lista(request: Request, uid: str, error: str | None = None) -> HTMLResponse:
    return plantillas.TemplateResponse(
        request,
        "_datasets.html",
        {
            "datasets": datos.listar(uid),
            "error": error,
            "max_mb": ARCHIVO_MAX_MB,
            "limite": ARCHIVOS_POR_USUARIO,
        },
    )


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
            "limite": ARCHIVOS_POR_USUARIO,
            "volumenes": {k: v[0] for k, v in generador.VOLUMENES.items()},
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
                documento = datos.registrar(
                    uid, archivo.filename, contenido, extension,
                    origen={"tipo": "subido", "archivo": archivo.filename},
                )
                eventos.publicar(uid, "dataset_listo", {"nombre": documento["nombre"]})
            except datos.ErrorDeArchivo as fallo:
                error = str(fallo)

    return _lista(request, uid, error)


@router.post("/generar", response_class=HTMLResponse)
def generar(
    request: Request,
    volumen: str = Form("aleatorio"),
    usuario: dict = Depends(usuario_web),
):
    """Crea un lote de ventas nuevo: otra semilla, otro volumen, otro escenario."""
    uid = str(usuario["_id"])
    df, ficha = generador.generar_ventas(volumen)
    nombre = f"ventas_simuladas_{ficha['semilla']}.csv"
    error = None

    try:
        datos.registrar(uid, nombre, generador.a_csv(df), ".csv", origen=ficha)
        eventos.publicar(uid, "dataset_listo", {"nombre": nombre})
    except datos.ErrorDeArchivo as fallo:
        error = str(fallo)

    return _lista(request, uid, error)


@router.delete("/{dataset_id}", response_class=HTMLResponse)
def eliminar(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    uid = str(usuario["_id"])
    datos.eliminar(uid, dataset_id)
    eventos.publicar(uid, "dataset_eliminado")
    return _lista(request, uid)


# ─────────────────────────────── tablero ───────────────────────────────


def _cargar(request: Request, usuario: dict, dataset_id: str):
    """Documento, tabla completa, modelo, tabla filtrada y filtros activos."""
    documento = datos.obtener(str(usuario["_id"]), dataset_id)
    if not documento:
        return None

    completo = tablero.preparar(datos.cargar_tabla(documento))
    modelo = tablero.detectar(completo, documento["nombre"])

    q = request.query_params
    # Se muestran cuatro segmentadores, pero se acepta el filtro sobre
    # cualquier dimension: asi un enlace con ?s_producto=... tambien sirve.
    segmentadores = [d for d in modelo.dimensiones if completo[d].nunique() <= 30][:4]
    segmentos = {d: q.get(f"s_{d}", "") for d in modelo.dimensiones if d in segmentadores or q.get(f"s_{d}")}
    filtros = {"desde": q.get("desde", ""), "hasta": q.get("hasta", ""), "segmentos": segmentos}
    filtrado = tablero.filtrar(completo, modelo, filtros["desde"], filtros["hasta"], segmentos)

    opciones = {d: sorted(completo[d].dropna().astype(str).unique()) for d in segmentadores}
    rango_fechas = None
    if modelo.fecha and completo[modelo.fecha].notna().any():
        rango_fechas = (completo[modelo.fecha].min().date().isoformat(),
                        completo[modelo.fecha].max().date().isoformat())

    return {
        "dataset": documento,
        "perfil": documento["perfil"],
        "origen": documento.get("origen") or {"tipo": "subido"},
        "completo": completo,
        "df": filtrado,
        "modelo": modelo,
        "filtros": filtros,
        "opciones": opciones,
        "rango_fechas": rango_fechas,
        "activos": sum(1 for v in [filtros["desde"], filtros["hasta"], *segmentos.values()] if v),
    }


@router.get("/{dataset_id}", response_class=HTMLResponse)
def explorar(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    carga = _cargar(request, usuario, dataset_id)
    if not carga:
        return RedirectResponse("/datos", status_code=303)

    seccion = request.query_params.get("seccion", "resumen")
    return plantillas.TemplateResponse(
        request,
        "explorador.html",
        {
            "usuario": usuario,
            "activo": "datos",
            "secciones": SECCIONES,
            "seccion": seccion if seccion in SECCIONES else "resumen",
            "horas_vida": ARCHIVO_HORAS_VIDA,
            **carga,
        },
    )


@router.get("/{dataset_id}/seccion", response_class=HTMLResponse)
def seccion(request: Request, dataset_id: str, nombre: str = "resumen", usuario: dict = Depends(usuario_web)):
    """Contenido de una pestaña con los filtros actuales."""
    carga = _cargar(request, usuario, dataset_id)
    if not carga:
        return HTMLResponse("")

    df, modelo = carga["df"], carga["modelo"]
    contexto = {**carga, "seccion": nombre, "horas_vida": ARCHIVO_HORAS_VIDA}

    if df.empty:
        return plantillas.TemplateResponse(request, "_sin_datos.html", contexto)

    if nombre == "pivote":
        contexto |= _contexto_pivote(carga, request.query_params)
        plantilla = "_seccion_pivote.html"
    elif nombre == "medidas":
        contexto |= {"medidas": tablero.tabla_medidas(df, modelo)}
        plantilla = "_seccion_medidas.html"
    elif nombre == "explorador":
        detalle = carga["perfil"]["detalle"]
        contexto |= {
            "columnas": [c["nombre"] for c in detalle],
            "numericas": [c["nombre"] for c in detalle if c["tipo"] == "numerica"],
            "tipos": graficos.TIPOS,
            "agregaciones": graficos.AGREGACIONES,
        }
        plantilla = "_seccion_explorador.html"
    elif nombre == "origen":
        contexto |= {"calidad": tablero.calidad(carga["completo"])}
        plantilla = "_seccion_origen.html"
    else:
        dims = modelo.dimensiones
        principal = dims[0] if dims else None
        segunda = dims[1] if len(dims) > 1 else principal
        # La de mas categorias (producto, vendedor) es la que mejor muestra
        # quien sube y quien baja.
        detalle_dim = max(dims, key=lambda d: carga["completo"][d].nunique()) if dims else None
        ventana = tablero.ventana_mes(df, modelo)
        contexto |= {
            "tarjetas": tablero.indicadores(df, modelo),
            "mes_cierre": tablero.etiqueta_mes(ventana[0]) if ventana else None,
            "mes_previo": tablero.etiqueta_mes(ventana[0] - 1) if ventana else None,
            "principal": principal,
            "segunda": segunda,
            "detalle_dim": detalle_dim,
            "g_tendencia": tablero.tendencia(df, modelo),
            "g_ranking": tablero.ranking(df, modelo, principal) if principal else None,
            "g_composicion": tablero.composicion(df, modelo, segunda) if segunda else None,
            "g_variacion": tablero.variacion_por(df, modelo, detalle_dim) if detalle_dim else None,
            "g_calor": tablero.mapa_calor(df, modelo, principal) if principal else None,
            "hallazgos": _hallazgos(df, modelo, principal, ventana),
        }
        plantilla = "_seccion_resumen.html"

    return plantillas.TemplateResponse(request, plantilla, contexto)


def _hallazgos(df, modelo, principal, ventana) -> list[str]:
    """Tres frases que un gerente leeria antes que cualquier grafico."""
    frases = []
    if not modelo.medida:
        return frases
    nombre = modelo.medida.replace("_", " ")
    total = df[modelo.medida].sum()
    if principal:
        por_dim = df.groupby(principal, observed=True)[modelo.medida].sum().sort_values(ascending=False)
        if len(por_dim) and total:
            # Los nombres vienen del archivo: se escapan antes de mezclarlos con HTML.
            lider = escape(str(por_dim.index[0]))
            frases.append(
                f"<b>{lider}</b> lidera {escape(principal)} con {tablero.cifra(por_dim.iloc[0], modelo.monetaria)} "
                f"({tablero.porcentaje(por_dim.iloc[0] / total)} del total)."
            )
    if ventana:
        fechas = df[modelo.fecha]
        actual = df.loc[(fechas >= ventana[1]) & (fechas < ventana[2]), modelo.medida].sum()
        inicio, fin = (ventana[0] - 1).start_time, ventana[1]
        previo = df.loc[(fechas >= inicio) & (fechas < fin), modelo.medida].sum()
        if previo:
            cambio = (actual - previo) / previo
            verbo = "crece" if cambio >= 0 else "cae"
            frases.append(
                f"En {tablero.etiqueta_mes(ventana[0])} el {escape(nombre)} {verbo} "
                f"<b>{tablero.porcentaje(abs(cambio))}</b> frente al mes anterior "
                f"({tablero.cifra(actual, modelo.monetaria)} contra {tablero.cifra(previo, modelo.monetaria)})."
            )
    if modelo.fecha:
        mensual = df.groupby(df[modelo.fecha].dt.to_period("M"))[modelo.medida].sum()
        if len(mensual) >= 3:
            pico = mensual.idxmax()
            frases.append(
                f"El mejor mes del periodo fue <b>{tablero.etiqueta_mes(pico)}</b> con "
                f"{tablero.cifra(mensual.max(), modelo.monetaria)}; el promedio mensual es "
                f"{tablero.cifra(mensual.mean(), modelo.monetaria)}."
            )
    return frases


def _contexto_pivote(carga: dict, q) -> dict:
    modelo, completo = carga["modelo"], carga["completo"]
    dims = modelo.dimensiones
    campos = {d: d for d in dims}
    if modelo.fecha:
        campos |= {k: f"{v} ({modelo.fecha})" for k, v in tablero.DERIVADAS_FECHA.items()}

    filas = q.get("filas") or (dims[0] if dims else next(iter(campos), ""))
    columnas = q.get("columnas", "__trimestre" if modelo.fecha else "")
    if columnas == filas:
        columnas = ""
    valores = q.get("valores", modelo.medida or "")
    funcion = q.get("funcion", "suma")
    mostrar = q.get("mostrar", "valor")

    resultado = tablero.pivote(carga["df"], modelo, filas, columnas, valores, funcion, mostrar)
    sel = {"filas": filas, "columnas": columnas, "valores": valores, "funcion": funcion, "mostrar": mostrar}
    filtros = carga["filtros"]
    exportar = {"desde": filtros["desde"], "hasta": filtros["hasta"],
                **{f"s_{k}": v for k, v in filtros["segmentos"].items()}, **sel}
    return {
        "campos": campos,
        "numericas": modelo.numericas,
        "funciones": {k: v[0] for k, v in tablero.FUNCIONES_PIVOTE.items()},
        "mostrar_como": tablero.MOSTRAR_COMO,
        "sel": sel,
        "exportar": urlencode({k: v for k, v in exportar.items() if v}),
        "pivote": resultado,
    }


@router.get("/{dataset_id}/pivote.csv")
def pivote_csv(request: Request, dataset_id: str, usuario: dict = Depends(usuario_web)):
    carga = _cargar(request, usuario, dataset_id)
    if not carga:
        return RedirectResponse("/datos", status_code=303)
    resultado = _contexto_pivote(carga, request.query_params)["pivote"]
    if "tabla" not in resultado:
        return RedirectResponse(f"/datos/{dataset_id}", status_code=303)
    tabla = resultado["tabla"].copy()
    tabla.index.name, tabla.columns.name = "", None
    contenido = tabla.to_csv(sep=";", decimal=",").encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(contenido), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="pivote_{carga["modelo"].tabla}.csv"'},
    )


@router.post("/{dataset_id}/medida", response_class=HTMLResponse)
def medida_libre(
    request: Request,
    dataset_id: str,
    formula: str = Form(""),
    dimension: str = Form(""),
    usuario: dict = Depends(usuario_web),
):
    carga = _cargar(request, usuario, dataset_id)
    if not carga:
        return HTMLResponse("")
    contexto = {"formula": formula, "dimension": dimension, "modelo": carga["modelo"]}
    try:
        contexto["resultado"] = tablero.evaluar_libre(carga["df"], carga["modelo"], formula[:2000], dimension or None)
    except dax.ErrorDax as error:
        contexto["error"] = str(error)
    except (TypeError, ValueError) as error:
        contexto["error"] = f"No se pudo calcular: {error}"
    return plantillas.TemplateResponse(request, "_medida_libre.html", contexto)


@router.get("/{dataset_id}/descargar")
def descargar(dataset_id: str, usuario: dict = Depends(usuario_web)):
    """El lote completo en CSV, listo para abrir en Excel o Power BI."""
    documento = datos.obtener(str(usuario["_id"]), dataset_id)
    if not documento:
        return RedirectResponse("/datos", status_code=303)
    tabla = datos.cargar_tabla(documento)
    nombre = Path(documento["nombre"]).stem + ".csv"
    contenido = tabla.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(contenido), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ─────────────────────────────── explorador ────────────────────────────


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
