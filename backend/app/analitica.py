"""Analisis de tareas con pandas.

Toda la agregacion se hace en un DataFrame y no en la base: el volumen por
usuario es pequeno, y trabajar en pandas permite operaciones de series de
tiempo (resample, medias moviles) que en Mongo exigirian pipelines mucho
mas largos y dificiles de leer.
"""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from bson import ObjectId

from app.database import tareas

from app.graficos import _terminar, vacio as _vacio


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


def grafico_estados(df: pd.DataFrame) -> str:
    if df.empty:
        return _vacio("Sin tareas registradas")

    conteo = df["estado"].value_counts().reset_index()
    conteo.columns = ["estado", "cantidad"]
    conteo["estado"] = conteo["estado"].str.replace("_", " ").str.capitalize()

    figura = px.pie(conteo, names="estado", values="cantidad", hole=0.55)
    figura.update_traces(textposition="outside", textinfo="label+percent")
    figura.update_layout(showlegend=False)
    return _terminar(figura)


def grafico_categorias(df: pd.DataFrame) -> str:
    if df.empty:
        return _vacio("Sin tareas registradas")

    tabla = (
        df.groupby("categoria")
        .agg(
            total=("estado", "size"),
            completadas=("estado", lambda s: (s == "completada").sum()),
        )
        .reset_index()
        .sort_values("total", ascending=True)
        .tail(8)
    )
    tabla["cumplimiento"] = (tabla["completadas"] / tabla["total"] * 100).round(1)

    figura = px.bar(
        tabla,
        x="total",
        y="categoria",
        orientation="h",
        text="cumplimiento",
        labels={"total": "Tareas", "categoria": ""},
    )
    figura.update_traces(texttemplate="%{text}% completado", textposition="outside")
    return _terminar(figura)


def grafico_evolucion(df: pd.DataFrame, semanas: int = 12) -> str:
    """Creadas frente a completadas, por semana."""
    if df.empty:
        return _vacio("Sin tareas registradas")

    desde = pd.Timestamp.now(tz="UTC") - timedelta(weeks=semanas)

    creadas = (
        df[df["creada_en"] >= desde]
        .set_index("creada_en")
        .resample("W")
        .size()
        .rename("Creadas")
    )

    cerradas = df[df["completada_en"].notna() & (df["completada_en"] >= desde)]
    completadas = (
        cerradas.set_index("completada_en").resample("W").size().rename("Completadas")
    )

    serie = pd.concat([creadas, completadas], axis=1).fillna(0).reset_index()
    serie.columns = ["semana", "Creadas", "Completadas"]

    if serie.empty:
        return _vacio("Sin actividad en el periodo")

    figura = px.line(
        serie,
        x="semana",
        y=["Creadas", "Completadas"],
        markers=True,
        labels={"semana": "", "value": "Tareas", "variable": ""},
    )
    figura.update_layout(showlegend=True, legend=dict(orientation="h", y=1.15))
    return _terminar(figura, alto=340)


def grafico_prioridades(df: pd.DataFrame) -> str:
    if df.empty:
        return _vacio("Sin tareas registradas")

    orden = ["baja", "media", "alta"]
    tabla = (
        df.groupby(["prioridad", "estado"]).size().reset_index(name="cantidad")
    )
    tabla["prioridad"] = pd.Categorical(
        tabla["prioridad"], categories=orden, ordered=True
    )
    tabla = tabla.sort_values("prioridad")
    tabla["estado"] = tabla["estado"].str.replace("_", " ").str.capitalize()

    figura = px.bar(
        tabla,
        x="prioridad",
        y="cantidad",
        color="estado",
        barmode="stack",
        labels={"prioridad": "", "cantidad": "Tareas", "estado": ""},
    )
    figura.update_layout(showlegend=True, legend=dict(orientation="h", y=1.15))
    return _terminar(figura)


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
