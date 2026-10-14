"""Analisis de tareas con pandas.

Toda la agregacion se hace en un DataFrame y no en la base: el volumen por
usuario es pequeno, y trabajar en pandas permite operaciones de series de
tiempo (resample, medias moviles) que en Mongo exigirian pipelines mucho
mas largos y dificiles de leer.
"""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from bson import ObjectId

from app.database import tareas

from app.graficos import CATEGORICOS, OTROS, _terminar, vacio as _vacio
from app.tablero import porcentaje, sparkline

# Cada estado tiene siempre el mismo color, en todos los graficos.
ESTADOS = {
    "completada": ("Completada", CATEGORICOS[0]),
    "en_progreso": ("En progreso", CATEGORICOS[1]),
    "pendiente": ("Pendiente", CATEGORICOS[2]),
}
PRIORIDADES = ["alta", "media", "baja"]


def cargar(usuario_id: str) -> pd.DataFrame:
    """Trae las tareas del usuario a un DataFrame ya normalizado."""
    documentos = list(tareas.find({"usuario_id": ObjectId(usuario_id)}))

    if not documentos:
        return pd.DataFrame()

    df = pd.DataFrame(documentos)
    df["creada_en"] = pd.to_datetime(df["creada_en"], utc=True)
    df["completada_en"] = pd.to_datetime(df.get("completada_en"), utc=True)

    if "fecha_limite" in df:
        df["fecha_limite"] = pd.to_datetime(df["fecha_limite"], utc=True)
    else:
        df["fecha_limite"] = pd.NaT

    # Horas transcurridas entre creacion y cierre
    df["horas_cierre"] = (
        df["completada_en"] - df["creada_en"]
    ).dt.total_seconds() / 3600

    df["categoria"] = df.get("categoria", "general").fillna("general")
    df["prioridad"] = df.get("prioridad", "media").fillna("media")

    return df


def filtrar(
    df: pd.DataFrame,
    desde: str | None = None,
    hasta: str | None = None,
    categoria: str | None = None,
    prioridad: str | None = None,
) -> pd.DataFrame:
    """Aplica los filtros del panel. Devuelve un DataFrame nuevo."""
    if df.empty:
        return df

    filtrado = df

    if desde:
        filtrado = filtrado[filtrado["creada_en"] >= pd.Timestamp(desde, tz="UTC")]
    if hasta:
        limite = pd.Timestamp(hasta, tz="UTC") + timedelta(days=1)
        filtrado = filtrado[filtrado["creada_en"] < limite]
    if categoria:
        filtrado = filtrado[filtrado["categoria"] == categoria]
    if prioridad:
        filtrado = filtrado[filtrado["prioridad"] == prioridad]

    return filtrado


def indicadores(df: pd.DataFrame) -> dict:
    """Cifras principales del panel."""
    if df.empty:
        return {
            "total": 0,
            "completadas": 0,
            "pendientes": 0,
            "cumplimiento": 0.0,
            "horas_medias": None,
            "vencidas": 0,
        }

    total = len(df)
    completadas = int((df["estado"] == "completada").sum())
    abiertas = df[df["estado"] != "completada"]

    ahora = pd.Timestamp.now(tz="UTC")
    vencidas = int(
        (abiertas["fecha_limite"].notna() & (abiertas["fecha_limite"] < ahora)).sum()
    )

    horas = df.loc[df["horas_cierre"].notna(), "horas_cierre"]

    return {
        "total": total,
        "completadas": completadas,
        "pendientes": total - completadas,
        "cumplimiento": round(completadas / total * 100, 1),
        "horas_medias": round(float(horas.mean()), 1) if not horas.empty else None,
        "vencidas": vencidas,
    }


def horas_legibles(horas) -> str:
    """30 h se lee mejor que 1,3 dias; 96 h, al reves."""
    if horas is None or pd.isna(horas):
        return "—"
    if horas >= 48:
        return f"{horas / 24:.1f} días".replace(".", ",")
    return f"{horas:.0f} h"


def _semanal(df: pd.DataFrame, columna: str, semanas: int = 12) -> pd.Series:
    """Conteo por semana completa (lunes a domingo) de las ultimas `semanas`.

    La semana en curso queda fuera: a mitad de semana parece un desplome.
    """
    hoy = pd.Timestamp.now(tz="UTC").normalize()
    ultimo_domingo = hoy - timedelta(days=(hoy.dayofweek + 1) % 7 or 7)
    desde = ultimo_domingo - timedelta(weeks=semanas) + timedelta(days=1)
    hasta = ultimo_domingo + timedelta(days=1)
    indice = pd.date_range(desde + timedelta(days=6), ultimo_domingo, freq="W-SUN")
    if df.empty or columna not in df:
        return pd.Series(0.0, index=indice)
    datos = df[df[columna].notna() & (df[columna] >= desde) & (df[columna] < hasta)]
    if datos.empty:
        return pd.Series(0.0, index=indice)
    serie = datos.set_index(columna).resample("W-SUN").size()
    return serie.reindex(indice, fill_value=0).astype(float)


def tarjetas(df: pd.DataFrame) -> list[dict]:
    """Indicadores con su variacion: ultimas 4 semanas frente a las 4 previas."""
    kpi = indicadores(df)
    ahora = pd.Timestamp.now(tz="UTC")
    corte, previo = ahora - timedelta(weeks=4), ahora - timedelta(weeks=8)

    def ventana(desde, hasta):
        if df.empty:
            return df
        return df[(df["creada_en"] >= desde) & (df["creada_en"] < hasta)]

    actual, anterior = ventana(corte, ahora), ventana(previo, corte)

    def cumplimiento(d):
        return float((d["estado"] == "completada").mean()) if len(d) else None

    def cierre(d):
        h = d["horas_cierre"].dropna() if len(d) else pd.Series(dtype=float)
        return float(h.mean()) if len(h) else None

    n_act, n_ant = len(actual), len(anterior)
    c_act, c_ant = cumplimiento(actual), cumplimiento(anterior)
    h_act, h_ant = cierre(actual), cierre(anterior)
    abiertas = kpi["total"] - kpi["completadas"]

    def variacion(a, b):
        return (a - b) / b if a is not None and b else None

    v_n = variacion(n_act, n_ant)
    v_h = variacion(h_act, h_ant)
    v_c = (c_act - c_ant) if c_act is not None and c_ant is not None else None

    return [
        {
            "titulo": "Tareas registradas",
            "valor": f"{kpi['total']:,}".replace(",", "."),
            "variacion": v_n,
            "texto": porcentaje(v_n, signo=True) if v_n is not None else None,
            # Mas tareas no es bueno ni malo: se muestra en neutro.
            "favorable": None,
            "spark": sparkline(_semanal(df, "creada_en")),
            "ayuda": "Todas las tareas que cumplen los filtros. La etiqueta compara las creadas en las últimas 4 semanas con las 4 anteriores.",
        },
        {
            "titulo": "Cumplimiento",
            "valor": f"{kpi['cumplimiento']:.1f} %".replace(".", ","),
            "variacion": v_c,
            "texto": f"{v_c * 100:+.1f} pts".replace(".", ",") if v_c is not None else None,
            "favorable": None if v_c is None else v_c >= 0,
            "spark": sparkline(_semanal(df, "completada_en")),
            "ayuda": "Porcentaje de tareas completadas. La variación, en puntos, compara las tareas de las últimas 4 semanas con las de las 4 anteriores.",
        },
        {
            "titulo": "Tiempo medio de cierre",
            "valor": horas_legibles(kpi["horas_medias"]),
            "variacion": v_h,
            "texto": porcentaje(v_h, signo=True) if v_h is not None else None,
            # Tardar menos es la buena noticia.
            "favorable": None if v_h is None else v_h <= 0,
            "spark": "",
            "ayuda": "Promedio entre la creación y la finalización de las tareas completadas. Si baja, se cierra más rápido.",
        },
        {
            "titulo": "Vencidas sin cerrar",
            "valor": f"{kpi['vencidas']:,}".replace(",", "."),
            "variacion": None,
            "texto": None,
            "favorable": None,
            "nota": f"de {abiertas} abiertas" if abiertas else "ninguna abierta",
            "alerta": kpi["vencidas"] > 0,
            "spark": "",
            "ayuda": "Tareas sin completar cuya fecha límite ya pasó: la lista por donde conviene empezar.",
        },
    ]


def hallazgos(df: pd.DataFrame) -> list[str]:
    """Frases que resumen el panel antes de mirar un grafico."""
    if df.empty:
        return []
    from markupsafe import escape

    frases = []
    por_cat = df.groupby("categoria").agg(
        total=("estado", "size"),
        hechas=("estado", lambda s: (s == "completada").sum()),
    )
    lider = por_cat["total"].idxmax()
    frases.append(
        f"<b>{escape(lider)}</b> concentra el {porcentaje(por_cat.loc[lider, 'total'] / len(df))} "
        f"de las tareas ({por_cat.loc[lider, 'total']} de {len(df)})."
    )
    if len(por_cat) > 1:
        tasa = por_cat["hechas"] / por_cat["total"]
        floja = tasa.idxmin()
        if floja == lider:
            frases.append(
                f"<b>{escape(floja)}</b> es además la categoría con menor cumplimiento: "
                f"{porcentaje(tasa[floja])} completado."
            )
        else:
            frases.append(
                f"La categoría con menor cumplimiento es <b>{escape(floja)}</b>: "
                f"{porcentaje(tasa[floja])} completado."
            )
    horas = df.groupby("prioridad")["horas_cierre"].mean().dropna()
    if "alta" in horas.index and len(horas) > 1:
        frases.append(
            f"Las tareas de prioridad <b>alta</b> se cierran en {horas_legibles(horas['alta'])}; "
            f"el promedio general es {horas_legibles(df['horas_cierre'].mean())}."
        )
    return frases[:3]


def grafico_evolucion(df: pd.DataFrame, semanas: int = 12) -> str:
    """Creadas frente a completadas, por semana."""
    if df.empty:
        return _vacio("Sin tareas registradas")

    figura = go.Figure()
    for nombre, columna, color, guion in (
        ("Creadas", "creada_en", CATEGORICOS[1], "dash"),
        ("Completadas", "completada_en", CATEGORICOS[0], "solid"),
    ):
        serie = _semanal(df, columna, semanas)
        figura.add_trace(go.Scatter(
            x=serie.index, y=serie.values, name=nombre, mode="lines+markers",
            line=dict(color=color, width=2.5, dash=guion, shape="spline", smoothing=0.4),
            marker=dict(size=7, color=color, line=dict(width=2, color="#ffffff")),
            hovertemplate="%{y:.0f} tareas<extra>" + nombre + "</extra>",
        ))
    figura.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", y=1.14, x=0),
        xaxis=dict(type="date", tickformat="%d %b", dtick=14 * 24 * 3600 * 1000, showgrid=False),
        yaxis=dict(rangemode="tozero", tickformat="d"),
    )
    return _terminar(figura, alto=340)


def grafico_estados(df: pd.DataFrame) -> str:
    """Barras horizontales: con tres estados se leen mejor que una dona."""
    if df.empty:
        return _vacio("Sin tareas registradas")

    conteo = df["estado"].value_counts()
    orden = [e for e in ESTADOS if e in conteo.index][::-1]
    total = int(conteo.sum())
    figura = go.Figure(go.Bar(
        x=[int(conteo[e]) for e in orden], y=[ESTADOS[e][0] for e in orden], orientation="h",
        marker=dict(color=[ESTADOS[e][1] for e in orden], cornerradius=4),
        text=[f"{conteo[e]} · {porcentaje(conteo[e] / total)}" for e in orden],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x} tareas<extra></extra>",
    ))
    figura.update_layout(
        bargap=0.4,
        xaxis=dict(showgrid=False, showticklabels=False, range=[0, float(conteo.max()) * 1.45]),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=20, t=10, b=10),
    )
    return _terminar(figura, alto=260)


def grafico_prioridades(df: pd.DataFrame) -> str:
    if df.empty:
        return _vacio("Sin tareas registradas")

    tabla = df.groupby(["prioridad", "estado"]).size().unstack(fill_value=0)
    filas = [p for p in PRIORIDADES if p in tabla.index][::-1]
    figura = go.Figure()
    for estado, (nombre, color) in ESTADOS.items():
        if estado not in tabla.columns:
            continue
        figura.add_trace(go.Bar(
            y=[p.capitalize() for p in filas], x=[int(tabla.loc[p, estado]) for p in filas],
            name=nombre, orientation="h",
            marker=dict(color=color, line=dict(width=2, color="#ffffff")),
            hovertemplate=nombre + ": %{x}<extra>%{y}</extra>",
        ))
    figura.update_layout(
        barmode="stack", bargap=0.4,
        legend=dict(orientation="h", y=1.2, x=0, traceorder="normal"),
        xaxis=dict(tickformat="d"),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=20, t=30, b=30),
    )
    return _terminar(figura, alto=260)


def grafico_categorias(df: pd.DataFrame) -> str:
    """Volumen por categoria, partido en completadas y abiertas."""
    if df.empty:
        return _vacio("Sin tareas registradas")

    tabla = (
        df.groupby("categoria")
        .agg(total=("estado", "size"), completadas=("estado", lambda s: (s == "completada").sum()))
        .sort_values("total", ascending=True)
        .tail(10)
    )
    tabla["abiertas"] = tabla["total"] - tabla["completadas"]
    tabla["cumplimiento"] = tabla["completadas"] / tabla["total"]
    nombres = [str(c).capitalize() for c in tabla.index]

    figura = go.Figure()
    figura.add_trace(go.Bar(
        y=nombres, x=tabla["completadas"], name="Completadas", orientation="h",
        marker=dict(color=CATEGORICOS[0], line=dict(width=2, color="#ffffff")),
        hovertemplate="%{x} completadas<extra>%{y}</extra>",
    ))
    figura.add_trace(go.Bar(
        y=nombres, x=tabla["abiertas"], name="Abiertas", orientation="h",
        marker=dict(color=OTROS, line=dict(width=2, color="#ffffff")),
        text=[f"{porcentaje(c, 0)} completado" for c in tabla["cumplimiento"]],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{x} abiertas<extra>%{y}</extra>",
    ))
    figura.update_layout(
        barmode="stack", bargap=0.35,
        legend=dict(orientation="h", y=1.12, x=0, traceorder="normal"),
        xaxis=dict(tickformat="d", range=[0, float(tabla["total"].max()) * 1.3]),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=20, t=30, b=30),
    )
    return _terminar(figura, alto=max(260, 42 * len(tabla) + 80))


def resumen_json(usuario_id: str) -> dict:
    """Version de los indicadores para la API REST."""
    df = cargar(usuario_id)
    datos = indicadores(df)

    if not df.empty:
        datos["por_categoria"] = (
            df.groupby("categoria").size().sort_values(ascending=False).to_dict()
        )
        datos["por_prioridad"] = df.groupby("prioridad").size().to_dict()
    else:
        datos["por_categoria"] = {}
        datos["por_prioridad"] = {}

    return datos
