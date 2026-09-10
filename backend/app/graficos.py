"""Construccion de graficos con Plotly, renderizados en el servidor.

El navegador recibe HTML listo para dibujar: no hay logica de graficacion
en el cliente, coherente con el objetivo de que el proyecto sea Python de
punta a punta.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

COLORES = ["#4f46e5", "#0ea5e9", "#14b8a6", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"]

AGREGACIONES = {
    "conteo": "Cantidad de registros",
    "suma": "Suma",
    "promedio": "Promedio",
    "maximo": "Maximo",
    "minimo": "Minimo",
}

TIPOS = {
    "barras": "Barras",
    "lineas": "Lineas",
    "area": "Area",
    "torta": "Torta",
    "dispersion": "Dispersion",
    "caja": "Caja",
    "histograma": "Histograma",
}


def _terminar(figura, alto: int = 380) -> str:
    figura.update_layout(
        template="plotly_white",
        margin=dict(t=30, b=40, l=50, r=25),
        height=alto,
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#475569"),
        colorway=COLORES,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="#f1f5f9"),
        yaxis=dict(gridcolor="#f1f5f9"),
    )
    return figura.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def vacio(mensaje: str, alto: int = 320) -> str:
    figura = go.Figure()
    figura.add_annotation(text=mensaje, showarrow=False, font=dict(size=13, color="#94a3b8"))
    figura.update_layout(
        template="plotly_white",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=alto,
        margin=dict(t=20, b=20, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return figura.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def _agregar(df: pd.DataFrame, dimension: str, medida: str | None, funcion: str) -> pd.DataFrame:
    """Aplica la agregacion elegida y devuelve una tabla de dos columnas."""
    if funcion == "conteo" or not medida:
        tabla = df.groupby(dimension, dropna=False).size().reset_index(name="valor")
    else:
        operacion = {"suma": "sum", "promedio": "mean", "maximo": "max", "minimo": "min"}[funcion]
        tabla = (
            df.groupby(dimension, dropna=False)[medida]
            .agg(operacion)
            .reset_index(name="valor")
        )

    tabla[dimension] = tabla[dimension].astype(str)
    tabla["valor"] = pd.to_numeric(tabla["valor"], errors="coerce").round(2)

    # Con demasiadas categorias el grafico deja de leerse: se muestran las
    # 20 mayores y el resto se agrupa.
    if len(tabla) > 20:
        tabla = tabla.sort_values("valor", ascending=False)
        cabeza = tabla.head(19)
        resto = pd.DataFrame([{dimension: "otros", "valor": tabla.tail(len(tabla) - 19)["valor"].sum()}])
        tabla = pd.concat([cabeza, resto], ignore_index=True)

    return tabla.sort_values("valor", ascending=False)


def construir(
    df: pd.DataFrame,
    tipo: str,
    dimension: str,
    medida: str | None = None,
    funcion: str = "conteo",
) -> str:
    """Genera el grafico pedido por el explorador."""
    if df.empty or dimension not in df.columns:
        return vacio("Elige una columna para empezar")

    etiqueta = AGREGACIONES.get(funcion, "Valor")

    try:
        if tipo == "histograma":
            figura = px.histogram(df, x=dimension, nbins=30, labels={dimension: dimension})
            return _terminar(figura)

        if tipo == "caja":
            if not medida:
                return vacio("La caja necesita una columna numerica como medida")
            figura = px.box(df, x=dimension, y=medida)
            return _terminar(figura)

        if tipo == "dispersion":
            if not medida:
                return vacio("La dispersion necesita dos columnas numericas")
            figura = px.scatter(df, x=dimension, y=medida, opacity=0.65)
            return _terminar(figura)

        tabla = _agregar(df, dimension, medida, funcion)
        ejes = {dimension: dimension, "valor": etiqueta}

        if tipo == "torta":
            figura = px.pie(tabla, names=dimension, values="valor", hole=0.5)
            figura.update_traces(textposition="outside", textinfo="label+percent")
        elif tipo == "lineas":
            figura = px.line(tabla.sort_values(dimension), x=dimension, y="valor", markers=True, labels=ejes)
        elif tipo == "area":
            figura = px.area(tabla.sort_values(dimension), x=dimension, y="valor", labels=ejes)
        else:
            horizontal = len(tabla) > 8
            figura = px.bar(
                tabla,
                x="valor" if horizontal else dimension,
                y=dimension if horizontal else "valor",
                orientation="h" if horizontal else "v",
                labels=ejes,
            )

        return _terminar(figura)

    except Exception as error:
        return vacio(f"No se pudo graficar: {error}")
