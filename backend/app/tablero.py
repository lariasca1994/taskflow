"""Tablero gerencial sobre cualquier archivo subido o generado.

El archivo no trae metadatos: aqui se deduce que columna es la fecha,
cual es la medida principal (la cifra que importa a gerencia) y cuales
son las dimensiones por las que vale la pena cortar. Con eso se arman
los indicadores, las medidas DAX del catalogo, los graficos y la tabla
dinamica.
"""

import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app import dax
from app.graficos import CATEGORICOS, NEGATIVO, OTROS, SECUENCIAL, _terminar, vacio

MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre"]

_MONETARIO = re.compile(r"venta|monto|importe|total|ingreso|precio|costo|margen|valor|revenue|sales|amount|price|cost|profit", re.I)
_PRIORIDAD_MEDIDA = ["total_venta", "ventas", "venta", "monto", "importe", "ingreso", "revenue",
                     "sales", "amount", "total", "valor"]
_CANTIDAD = re.compile(r"unidades|cantidad|qty|quantity|units", re.I)
_IDENTIFICADOR = re.compile(r"(^|_)(id|codigo|cod|key|nit|cedula)($|_)|^id", re.I)


# ─────────────────────────────── modelo ────────────────────────────────


@dataclass
class Modelo:
    """Roles de cada columna, deducidos una vez por archivo."""

    tabla: str
    fecha: str | None
    medida: str | None
    cantidad: str | None
    costo: str | None
    margen: str | None
    dimensiones: list[str] = field(default_factory=list)
    numericas: list[str] = field(default_factory=list)
    monetaria: bool = False


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def nombre_tabla(nombre_archivo: str) -> str:
    base = re.sub(r"\.[^.]+$", "", nombre_archivo)
    base = re.sub(r"[^A-Za-z0-9_]+", "_", _sin_tildes(base)).strip("_")
    return base or "Datos"


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte a fecha las columnas de texto que lo son.

    Los archivos subidos antes de que la carga detectara fechas las traen
    como texto; aqui se corrigen al vuelo.
    """
    df = df.copy()
    for col in df.columns:
        serie = df[col]
        if pd.api.types.is_datetime64_any_dtype(serie):
            if getattr(serie.dt, "tz", None) is not None:
                df[col] = serie.dt.tz_localize(None)
            continue
        if serie.dtype == object and _parece_fecha(col, serie):
            df[col] = pd.to_datetime(serie, errors="coerce", format="mixed", dayfirst=False)
    return df


def _parece_fecha(nombre: str, serie: pd.Series) -> bool:
    muestra = serie.dropna().astype(str).head(200)
    if muestra.empty:
        return False
    if not re.search(r"fecha|date|dia|periodo|mes", _sin_tildes(str(nombre)), re.I):
        if not muestra.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.9:
            return False
    convertidas = pd.to_datetime(muestra, errors="coerce", format="mixed")
    return convertidas.notna().mean() > 0.9


def detectar(df: pd.DataFrame, nombre_archivo: str) -> Modelo:
    filas = len(df)

    fechas = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    fecha = max(fechas, key=lambda c: df[c].nunique()) if fechas else None

    numericas = [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
    ]
    candidatas = [
        c for c in numericas
        if not _IDENTIFICADOR.search(c) and not (df[c].nunique() == filas and filas > 50)
    ]

    medida = None
    for clave in _PRIORIDAD_MEDIDA:
        exactas = [c for c in candidatas if _sin_tildes(c).lower() == clave]
        parciales = [c for c in candidatas if clave in _sin_tildes(c).lower()]
        if exactas or parciales:
            medida = (exactas or parciales)[0]
            break
    if medida is None and candidatas:
        medida = max(candidatas, key=lambda c: abs(float(df[c].sum())))

    def buscar(patron):
        for c in candidatas:
            if c != medida and re.search(patron, _sin_tildes(c), re.I):
                return c
        return None

    cantidad = next((c for c in candidatas if c != medida and _CANTIDAD.search(c)), None)

    dimensiones = []
    for c in df.columns:
        if c in numericas or c == fecha or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        unicos = df[c].nunique(dropna=True)
        if 2 <= unicos <= 60 and unicos < max(filas * 0.5, 3):
            dimensiones.append(c)
    # Primero las de pocas categorias: son las que se leen bien en un grafico.
    dimensiones.sort(key=lambda c: (df[c].nunique() > 12, df[c].nunique()))

    return Modelo(
        tabla=nombre_tabla(nombre_archivo),
        fecha=fecha,
        medida=medida,
        cantidad=cantidad,
        costo=buscar(r"^costo|^cost"),
        margen=buscar(r"margen|utilidad|ganancia|profit"),
        dimensiones=dimensiones,
        numericas=numericas,
        monetaria=bool(medida and _MONETARIO.search(_sin_tildes(medida))),
    )


def nombre_medida(modelo: Modelo) -> str:
    """«Total venta» y no «Total total venta» cuando la columna ya lo dice."""
    legible = (modelo.medida or "registros").replace("_", " ")
    return legible.capitalize() if legible.lower().startswith("total") else f"Total {legible}"


def filtrar(df: pd.DataFrame, modelo: Modelo, desde: str | None, hasta: str | None,
            segmentos: dict[str, str]) -> pd.DataFrame:
    if modelo.fecha:
        if desde:
            df = df[df[modelo.fecha] >= pd.Timestamp(desde)]
        if hasta:
            df = df[df[modelo.fecha] < pd.Timestamp(hasta) + pd.Timedelta(days=1)]
    for col, valor in segmentos.items():
        if valor and col in df.columns:
            df = df[df[col].astype(str) == valor]
    return df


# ─────────────────────────────── formato ───────────────────────────────


def cifra(valor, monetaria: bool = False, decimales: int = 1) -> str:
    """Formato compacto con separadores colombianos: 1.284,5 M."""
    if not dax.numero_valido(valor):
        return "—"
    signo = "-" if valor < 0 else ""
    v = abs(valor)
    if v >= 1e9:
        texto = f"{v / 1e9:,.2f} mil M"
    elif v >= 1e6:
        texto = f"{v / 1e6:,.{decimales}f} M"
    elif v >= 1e4:
        texto = f"{v / 1e3:,.{decimales}f} mil"
    elif v == int(v):
        texto = f"{v:,.0f}"
    else:
        texto = f"{v:,.2f}"
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{signo}{'$ ' if monetaria else ''}{texto}"


def porcentaje(valor, decimales: int = 1, signo: bool = False) -> str:
    if not dax.numero_valido(valor):
        return "—"
    texto = f"{valor * 100:{'+' if signo else ''}.{decimales}f} %".replace(".", ",")
    return texto


def etiqueta_mes(periodo: pd.Period) -> str:
    return f"{MESES_CORTOS[periodo.month - 1]} {periodo.year}"


# ─────────────────────────────── medidas ───────────────────────────────


def catalogo(modelo: Modelo) -> list[dict]:
    """Medidas del informe escritas en DAX.

    El orden importa: las de abajo se apoyan en las de arriba, igual que
    en un modelo de Power BI.
    """
    t = f"'{modelo.tabla}'"
    m = modelo.medida
    f = modelo.fecha
    lista = []

    def agregar(nombre, formula, formato, descripcion):
        lista.append({"nombre": nombre, "dax": formula, "formato": formato, "descripcion": descripcion})

    if m:
        agregar("Total", f"SUM({t}[{m}])", "cifra", f"Suma de {m} en el contexto filtrado.")
    agregar("Registros", f"COUNTROWS({t})", "entero", "Filas que cumplen los filtros.")
    if m:
        agregar("Promedio por registro", "DIVIDE([Total], [Registros])", "cifra",
                "Ticket promedio: total dividido entre registros.")
    if modelo.cantidad:
        agregar("Unidades", f"SUM({t}[{modelo.cantidad}])", "entero", f"Suma de {modelo.cantidad}.")
    if m and modelo.margen:
        agregar("Margen", f"SUM({t}[{modelo.margen}])", "cifra", f"Suma de {modelo.margen}.")
        agregar("Margen %", "DIVIDE([Margen], [Total])", "porcentaje", "Margen sobre el total.")
    elif m and modelo.costo:
        agregar("Margen %", f"DIVIDE([Total] - SUM({t}[{modelo.costo}]), [Total])", "porcentaje",
                "Total menos costo, sobre el total.")
    if m and f:
        agregar("Total mes anterior", f"CALCULATE([Total], DATEADD({t}[{f}], -1, MONTH))", "cifra",
                "El mismo calculo desplazado un mes hacia atras.")
        agregar("Variación mensual %", "DIVIDE([Total] - [Total mes anterior], [Total mes anterior])",
                "variacion", "Crecimiento frente al mes anterior.")
        agregar("Total año anterior", f"CALCULATE([Total], SAMEPERIODLASTYEAR({t}[{f}]))", "cifra",
                "Mismo periodo del año pasado.")
        agregar("Variación anual %", "DIVIDE([Total] - [Total año anterior], [Total año anterior])",
                "variacion", "Crecimiento frente al mismo periodo del año pasado.")
        agregar("Acumulado del año", f"TOTALYTD([Total], {t}[{f}])", "cifra",
                "Desde el 1 de enero hasta el cierre del periodo.")
        agregar("Promedio móvil 3 meses",
                f"CALCULATE([Total], DATESINPERIOD({t}[{f}], LASTDATE({t}[{f}]), -3, MONTH)) / 3",
                "cifra", "Promedio mensual de los ultimos tres meses.")
    if modelo.dimensiones:
        d = modelo.dimensiones[0]
        agregar(f"{d.capitalize()} distintos", f"DISTINCTCOUNT({t}[{d}])", "entero",
                f"Valores diferentes de {d}.")
    return lista


def evaluador(modelo: Modelo, columnas: list[str], extra: dict[str, str] | None = None) -> dax.Evaluador:
    medidas = {x["nombre"]: x["dax"] for x in catalogo(modelo)}
    medidas.update(extra or {})
    return dax.Evaluador(columnas, medidas)


def ventana_mes(df: pd.DataFrame, modelo: Modelo):
    """Mes de cierre: el ultimo mes completo con datos.

    Si el ultimo mes esta a medias (el archivo se corto a mitad de mes),
    compararlo con el anterior haria parecer que las ventas se
    desplomaron; se usa el mes previo.
    """
    if not modelo.fecha or df.empty:
        return None
    ultima = df[modelo.fecha].max()
    periodo = ultima.to_period("M")
    if ultima.day < periodo.days_in_month - 2 and df[modelo.fecha].min().to_period("M") < periodo:
        periodo -= 1
    inicio = periodo.start_time
    return periodo, inicio, (periodo + 1).start_time


def contexto(df: pd.DataFrame, modelo: Modelo, ventana=None) -> dax.Contexto:
    if ventana:
        return dax.Contexto(df, modelo.fecha, ventana[1], ventana[2])
    if modelo.fecha and not df.empty:
        inicio = df[modelo.fecha].min().normalize()
        fin = df[modelo.fecha].max().normalize() + pd.Timedelta(days=1)
        return dax.Contexto(df, modelo.fecha, inicio, fin)
    return dax.Contexto(df, modelo.fecha, None, None)


def formatear(valor, formato: str, modelo: Modelo) -> str:
    if formato in ("porcentaje",):
        return porcentaje(valor)
    if formato == "variacion":
        return porcentaje(valor, signo=True)
    if formato == "entero":
        return cifra(valor, False)
    return cifra(valor, modelo.monetaria)


def tabla_medidas(df: pd.DataFrame, modelo: Modelo) -> dict:
    """Cada medida evaluada en el rango filtrado y en el mes de cierre."""
    ev = evaluador(modelo, list(df.columns))
    ventana = ventana_mes(df, modelo)
    filas = []
    for medida in catalogo(modelo):
        fila = dict(medida)
        for clave, ctx in (("rango", contexto(df, modelo)),
                           ("mes", contexto(df, modelo, ventana) if ventana else None)):
            if ctx is None:
                fila[clave] = "—"
                continue
            try:
                fila[clave] = formatear(ev.evaluar(dax.analizar(medida["dax"]), ctx), medida["formato"], modelo)
            except dax.ErrorDax as error:
                fila[clave] = f"Error: {error}"
        filas.append(fila)
    return {"filas": filas, "mes": etiqueta_mes(ventana[0]) if ventana else None}


def _es_razon(formula: str, valores: list[float]) -> bool:
    """Una medida que divide y queda entre -1,5 y 1,5 es un porcentaje."""
    if re.search(r"%|particip|porcentaje|ratio|tasa|share|margen %", formula, re.I):
        return True
    return "DIVIDE" in formula.upper() and bool(valores) and all(abs(v) <= 1.5 for v in valores)


def evaluar_libre(df: pd.DataFrame, modelo: Modelo, formula: str, dimension: str | None) -> dict:
    """Medida escrita por el usuario: valor total y desglose por dimension."""
    ev = evaluador(modelo, list(df.columns))
    arbol = dax.analizar(formula)
    rango = contexto(df, modelo)
    total = ev.evaluar(arbol, rango)

    valores = []
    if dimension and dimension in df.columns:
        # Cada grupo es un filtro del contexto, no un recorte previo de la
        # tabla: asi ALL(dimension) puede quitarlo, como en una matriz de
        # Power BI, y DATEADD desplaza la misma ventana para todos.
        for valor in df[dimension].dropna().astype(str).unique():
            filtro = {dimension: lambda d, v=valor: d[dimension].astype(str) == v}
            v = ev.evaluar(arbol, dax.Contexto(df, modelo.fecha, rango.inicio, rango.fin, filtro))
            if dax.numero_valido(v):
                valores.append((str(valor), float(v)))
        valores.sort(key=lambda x: x[1], reverse=True)

    numeros = [v for _, v in valores] + ([float(total)] if dax.numero_valido(total) else [])
    razon = _es_razon(formula, numeros)
    fmt = (lambda v: porcentaje(v)) if razon else (lambda v: cifra(v, modelo.monetaria))

    resultado = {"total": fmt(total) if dax.numero_valido(total) else "—", "razon": razon,
                 "grafico": None, "desglose": [(k, fmt(v)) for k, v in valores[:30]]}
    if valores:
        resultado["grafico"] = barras_ranking(pd.Series(dict(valores[:15])), modelo, razon=razon)
    return resultado


# ─────────────────────────────── indicadores ───────────────────────────


def _serie_mensual(df: pd.DataFrame, modelo: Modelo, columna: str | None = None, funcion="sum") -> pd.Series:
    if not modelo.fecha or df.empty:
        return pd.Series(dtype=float)
    agrupado = df.groupby(df[modelo.fecha].dt.to_period("M"))
    if columna is None:
        serie = agrupado.size().astype(float)
    else:
        serie = getattr(agrupado[columna], funcion)()
    indice = pd.period_range(serie.index.min(), serie.index.max(), freq="M")
    return serie.reindex(indice, fill_value=0)


def sparkline(serie: pd.Series, ancho: int = 120, alto: int = 32) -> str:
    """Mini tendencia en SVG; hereda el color del texto (currentColor)."""
    valores = [float(v) for v in serie.tolist() if dax.numero_valido(v)]
    if len(valores) < 2:
        return ""
    minimo, maximo = min(valores), max(valores)
    rango = (maximo - minimo) or 1
    paso = ancho / (len(valores) - 1)
    puntos = [(i * paso, alto - 3 - (v - minimo) / rango * (alto - 6)) for i, v in enumerate(valores)]
    linea = " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos)
    area = f"0,{alto} {linea} {ancho},{alto}"
    ux, uy = puntos[-1]
    return (
        f'<svg class="kpi-spark" viewBox="0 0 {ancho} {alto}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polygon points="{area}" class="kpi-spark-area"/>'
        f'<polyline points="{linea}" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="3" fill="currentColor"/></svg>'
    )


def _delta(actual, anterior):
    if not dax.numero_valido(actual) or not anterior:
        return None
    return (actual - anterior) / abs(anterior)


def indicadores(df: pd.DataFrame, modelo: Modelo) -> list[dict]:
    """Tarjetas superiores: valor del rango, variacion del mes de cierre y tendencia."""
    ev = evaluador(modelo, list(df.columns))
    rango = contexto(df, modelo)
    ventana = ventana_mes(df, modelo)
    tarjetas = []

    def tarjeta(titulo, medida, formato, serie=None, invertir=False, nota=None, ayuda=""):
        try:
            valor = ev.evaluar(dax.analizar(f"[{medida}]"), rango)
        except dax.ErrorDax:
            return
        variacion = None
        if ventana:
            mes = dax.Contexto(df, modelo.fecha, ventana[1], ventana[2])
            previo = dax.Contexto(df, modelo.fecha, *_mover(ventana, -1))
            try:
                variacion = _delta(ev.evaluar(dax.analizar(f"[{medida}]"), mes),
                                   ev.evaluar(dax.analizar(f"[{medida}]"), previo))
            except dax.ErrorDax:
                variacion = None
        if formato == "porcentaje" and ventana:
            # Para un porcentaje la variacion se expresa en puntos.
            try:
                a = ev.evaluar(dax.analizar(f"[{medida}]"), dax.Contexto(df, modelo.fecha, ventana[1], ventana[2]))
                b = ev.evaluar(dax.analizar(f"[{medida}]"), dax.Contexto(df, modelo.fecha, *_mover(ventana, -1)))
                variacion = (a - b) if dax.numero_valido(a) and dax.numero_valido(b) else None
            except dax.ErrorDax:
                variacion = None
        tarjetas.append({
            "titulo": titulo,
            "valor": formatear(valor, formato, modelo),
            "variacion": variacion,
            "variacion_texto": (
                (f"{variacion * 100:+.1f} pts".replace(".", ",") if formato == "porcentaje"
                 else porcentaje(variacion, signo=True)) if variacion is not None else None
            ),
            "favorable": None if variacion is None else ((variacion >= 0) != invertir),
            "spark": sparkline(serie) if serie is not None and len(serie) > 1 else "",
            "nota": nota,
            "ayuda": ayuda,
            "dax": f"[{medida}]",
        })

    if modelo.medida:
        tarjeta(nombre_medida(modelo), "Total", "cifra",
                _serie_mensual(df, modelo, modelo.medida),
                ayuda=f"Suma de {modelo.medida} en el periodo y filtros elegidos. La línea muestra su evolución mes a mes.")
    tarjeta("Registros", "Registros", "entero", _serie_mensual(df, modelo),
            ayuda="Cantidad de filas (transacciones) que cumplen los filtros.")
    if modelo.medida:
        mensual_total = _serie_mensual(df, modelo, modelo.medida)
        mensual_n = _serie_mensual(df, modelo)
        tarjeta("Promedio por registro", "Promedio por registro", "cifra",
                (mensual_total / mensual_n.replace(0, np.nan)) if len(mensual_n) else None,
                ayuda="Ticket promedio: el total dividido entre el número de registros. Si sube, cada venta vale más.")
    if modelo.margen or modelo.costo:
        if modelo.margen:
            serie = _serie_mensual(df, modelo, modelo.margen) / _serie_mensual(df, modelo, modelo.medida).replace(0, np.nan)
        else:
            serie = None
        tarjeta("Margen %", "Margen %", "porcentaje", serie,
                ayuda="De cada $100 vendidos, cuánto queda después del costo. Su variación se expresa en puntos porcentuales.")
    elif modelo.cantidad:
        tarjeta("Unidades", "Unidades", "entero", _serie_mensual(df, modelo, modelo.cantidad),
                ayuda=f"Suma de {modelo.cantidad}: volumen físico movido.")
    return tarjetas


def _mover(ventana, meses: int):
    periodo = ventana[0] + meses
    return periodo.start_time, (periodo + 1).start_time


def calidad(df: pd.DataFrame) -> dict:
    celdas = df.size or 1
    nulos = int(df.isna().sum().sum())
    duplicadas = int(df.duplicated().sum())
    return {
        "completitud": round((1 - nulos / celdas) * 100, 1),
        "nulos": nulos,
        "duplicadas": duplicadas,
        "columnas_con_nulos": [c for c in df.columns if df[c].isna().any()],
    }


# ─────────────────────────────── graficos ──────────────────────────────


def _hover_valor(modelo: Modelo) -> str:
    return ("$ %{y:,.0f}" if modelo.monetaria else "%{y:,.0f}")


def tendencia(df: pd.DataFrame, modelo: Modelo) -> str:
    """Total mensual, promedio movil y el mismo mes del año anterior."""
    if not modelo.fecha or not modelo.medida or df.empty:
        return vacio("El archivo no tiene una columna de fecha y una medida numérica")

    serie = _serie_mensual(df, modelo, modelo.medida)
    # Un primer mes que arranca a mitad de camino parece un desplome; se
    # deja fuera para que la curva empiece en un mes completo.
    primera = df[modelo.fecha].min()
    if len(serie) > 3 and primera.day > 3:
        serie = serie.iloc[1:]
    if serie.empty:
        return vacio("Sin datos en el periodo")

    ventana = ventana_mes(df, modelo)
    x = [p.to_timestamp() for p in serie.index]
    figura = go.Figure()

    anterior = serie.shift(12)
    if anterior.notna().sum() >= 2:
        figura.add_trace(go.Scatter(
            x=x, y=anterior, name="Año anterior", mode="lines",
            line=dict(color=OTROS, width=2, dash="dot"),
            hovertemplate=_hover_valor(modelo) + "<extra>Año anterior</extra>",
        ))

    figura.add_trace(go.Scatter(
        x=x, y=serie, name=nombre_medida(modelo), mode="lines+markers",
        line=dict(color=CATEGORICOS[0], width=2.5, shape="spline", smoothing=0.4),
        marker=dict(size=7, color=CATEGORICOS[0], line=dict(width=2, color="#ffffff")),
        fill="tozeroy", fillcolor="rgba(10,138,100,0.08)",
        hovertemplate=_hover_valor(modelo) + "<extra>Total</extra>",
    ))

    movil = serie.rolling(3, min_periods=3).mean()
    figura.add_trace(go.Scatter(
        x=x, y=movil, name="Promedio móvil 3 meses", mode="lines",
        line=dict(color=CATEGORICOS[1], width=2, dash="dash"),
        hovertemplate=_hover_valor(modelo) + "<extra>Promedio móvil</extra>",
    ))

    # Rotulo directo solo en el ultimo punto y en el maximo: no en todos.
    maximo = serie.idxmax()
    for periodo, texto in ((serie.index[-1], "Último"), (maximo, "Máximo")):
        figura.add_annotation(
            x=periodo.to_timestamp(), y=serie[periodo],
            text=f"{texto}: {cifra(serie[periodo], modelo.monetaria)}",
            showarrow=False, yshift=18, font=dict(size=11),
        )
        if maximo == serie.index[-1]:
            break

    if ventana and ventana[0] != serie.index[-1]:
        figura.add_vrect(x0=ventana[0].to_timestamp(), x1=x[-1], fillcolor="rgba(100,116,139,0.08)",
                         line_width=0, annotation_text="mes incompleto", annotation_position="top left",
                         annotation_font_size=10)

    figura.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0),
        xaxis=dict(tickformat="%b %Y", dtick="M2" if len(x) > 14 else "M1", showgrid=False),
        yaxis=dict(tickprefix="$ " if modelo.monetaria else "", rangemode="tozero"),
    )
    return _terminar(figura, alto=360)


def _top(serie: pd.Series, n: int) -> pd.Series:
    serie = serie.sort_values(ascending=False)
    if len(serie) <= n:
        return serie
    resto = serie.iloc[n - 1:].sum()
    return pd.concat([serie.iloc[:n - 1], pd.Series({"Otros": resto})])


def barras_ranking(serie: pd.Series, modelo: Modelo, titulo_eje: str = "", razon: bool = False) -> str:
    serie = serie.sort_values(ascending=True)
    total = serie.sum() or 1
    colores = [OTROS if k == "Otros" else (CATEGORICOS[0] if v >= 0 else NEGATIVO)
               for k, v in serie.items()]
    if razon:
        textos = [porcentaje(v) for v in serie.values]
        hover = "%{y}: %{x:.1%}<extra></extra>"
    else:
        # El peso sobre el total solo tiene sentido si todo suma en positivo.
        aditiva = (serie >= 0).all()
        textos = [cifra(v, modelo.monetaria) + (f" · {porcentaje(v / total)}" if aditiva else "")
                  for v in serie.values]
        hover = "%{y}: " + ("$ %{x:,.0f}" if modelo.monetaria else "%{x:,.2f}") + "<extra></extra>"
    figura = go.Figure(go.Bar(
        x=serie.values, y=[str(k) for k in serie.index], orientation="h",
        marker=dict(color=colores, cornerradius=4),
        text=textos, textposition="outside", cliponaxis=False, hovertemplate=hover,
    ))
    figura.update_layout(
        bargap=0.35,
        xaxis=dict(showgrid=False, showticklabels=False, title=titulo_eje or None,
                   range=[min(0.0, float(serie.min()) * 1.35), max(0.0, float(serie.max())) * 1.35 or 1]),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=20, t=10, b=20),
    )
    return _terminar(figura, alto=max(260, 34 * len(serie) + 60))


def ranking(df: pd.DataFrame, modelo: Modelo, dimension: str) -> str:
    if df.empty or not dimension:
        return vacio("Sin dimensiones para comparar")
    if modelo.medida:
        serie = df.groupby(dimension, observed=True)[modelo.medida].sum()
    else:
        serie = df.groupby(dimension, observed=True).size()
    return barras_ranking(_top(serie, 10), modelo)


def composicion(df: pd.DataFrame, modelo: Modelo, dimension: str) -> str:
    """Mezcla mensual de una dimension, apilada al 100 %."""
    if df.empty or not modelo.fecha or not dimension:
        return vacio("Se necesita una fecha y una dimensión")

    valores = df[modelo.medida] if modelo.medida else pd.Series(1, index=df.index)
    tabla = (
        pd.DataFrame({"mes": df[modelo.fecha].dt.to_period("M"), "dim": df[dimension].astype(str), "v": valores})
        .groupby(["mes", "dim"])["v"].sum().unstack(fill_value=0)
    )
    # Cinco series como maximo; el resto se agrupa en "Otros" con gris.
    orden = tabla.sum().sort_values(ascending=False).index.tolist()
    if len(orden) > 5:
        tabla["Otros"] = tabla[orden[4:]].sum(axis=1)
        tabla = tabla[orden[:4] + ["Otros"]]
    else:
        tabla = tabla[orden]
    proporcion = tabla.div(tabla.sum(axis=1).replace(0, np.nan), axis=0)

    figura = go.Figure()
    x = [p.to_timestamp() for p in proporcion.index]
    for i, col in enumerate(proporcion.columns):
        figura.add_trace(go.Bar(
            x=x, y=proporcion[col], name=col,
            marker=dict(color=OTROS if col == "Otros" else CATEGORICOS[i % len(CATEGORICOS)],
                        line=dict(width=1, color="#ffffff")),
            hovertemplate=f"{col}: " + "%{y:.1%}<extra></extra>",
        ))
    figura.update_layout(
        barmode="stack", bargap=0.25, hovermode="x unified",
        legend=dict(orientation="h", y=1.14, x=0),
        yaxis=dict(tickformat=".0%", range=[0, 1]),
        xaxis=dict(tickformat="%b %y", showgrid=False),
    )
    return _terminar(figura, alto=340)


def variacion_por(df: pd.DataFrame, modelo: Modelo, dimension: str) -> str:
    """Quien crece y quien cae: mes de cierre frente al anterior."""
    ventana = ventana_mes(df, modelo)
    if not ventana or not modelo.medida or not dimension:
        return vacio("Se necesita una fecha, una medida y una dimensión")

    inicio, fin = ventana[1], ventana[2]
    previo_inicio, previo_fin = _mover(ventana, -1)
    fechas = df[modelo.fecha]
    actual = df[(fechas >= inicio) & (fechas < fin)].groupby(dimension, observed=True)[modelo.medida].sum()
    previo = df[(fechas >= previo_inicio) & (fechas < previo_fin)].groupby(dimension, observed=True)[modelo.medida].sum()
    cambio = actual.subtract(previo, fill_value=0).sort_values()
    if cambio.empty:
        return vacio("Sin datos para comparar los dos meses")
    if len(cambio) > 12:
        cambio = pd.concat([cambio.head(6), cambio.tail(6)])

    colores = [CATEGORICOS[0] if v >= 0 else NEGATIVO for v in cambio.values]
    pct = (cambio / previo.reindex(cambio.index).replace(0, np.nan)).tolist()
    figura = go.Figure(go.Bar(
        x=cambio.values, y=[str(k) for k in cambio.index], orientation="h",
        marker=dict(color=colores, cornerradius=4),
        text=[f"{'▲' if v >= 0 else '▼'} {cifra(v, modelo.monetaria)} ({porcentaje(p, signo=True)})"
              for v, p in zip(cambio.values, pct)],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: " + ("$ %{x:,.0f}" if modelo.monetaria else "%{x:,.0f}") + "<extra></extra>",
    ))
    limite = float(cambio.abs().max()) * 2.1 or 1
    figura.update_layout(
        xaxis=dict(range=[-limite, limite], zeroline=True, showticklabels=False, showgrid=False),
        yaxis=dict(showgrid=False),
        margin=dict(l=10, r=20, t=10, b=20),
    )
    return _terminar(figura, alto=max(260, 34 * len(cambio) + 60))


def mapa_calor(df: pd.DataFrame, modelo: Modelo, dimension: str) -> str:
    if df.empty or not modelo.fecha or not dimension:
        return vacio("Se necesita una fecha y una dimensión")
    valores = df[modelo.medida] if modelo.medida else pd.Series(1, index=df.index)
    tabla = (
        pd.DataFrame({"mes": df[modelo.fecha].dt.to_period("M"), "dim": df[dimension].astype(str), "v": valores})
        .groupby(["dim", "mes"])["v"].sum().unstack(fill_value=0)
    )
    tabla = tabla.loc[tabla.sum(axis=1).sort_values(ascending=True).index].tail(12)
    tabla = tabla.iloc[:, -18:]
    figura = go.Figure(go.Heatmap(
        z=tabla.values, x=[p.to_timestamp() for p in tabla.columns], y=tabla.index.tolist(),
        colorscale=SECUENCIAL, xgap=2, ygap=2,
        hovertemplate="%{y} · %{x|%b %Y}<br>" + ("$ %{z:,.0f}" if modelo.monetaria else "%{z:,.0f}") + "<extra></extra>",
        colorbar=dict(thickness=10, outlinewidth=0, tickfont=dict(size=10),
                      tickprefix="$ " if modelo.monetaria else ""),
    ))
    figura.update_layout(
        xaxis=dict(showgrid=False, tickangle=0, tickformat="%b %y",
                   dtick="M3" if len(tabla.columns) > 9 else "M1"),
        yaxis=dict(showgrid=False),
    )
    return _terminar(figura, alto=max(260, 30 * len(tabla) + 90))


# ─────────────────────────────── tabla dinamica ────────────────────────

FUNCIONES_PIVOTE = {
    "suma": ("Suma", "sum"),
    "promedio": ("Promedio", "mean"),
    "conteo": ("Conteo", "count"),
    "distintos": ("Distintos", "nunique"),
    "maximo": ("Máximo", "max"),
    "minimo": ("Mínimo", "min"),
}
MOSTRAR_COMO = {
    "valor": "Valor",
    "total": "% del total general",
    "fila": "% del total de la fila",
    "columna": "% del total de la columna",
}
DERIVADAS_FECHA = {"__anio": "Año", "__trimestre": "Trimestre", "__mes": "Mes"}


def _derivar(df: pd.DataFrame, modelo: Modelo, campo: str) -> pd.Series:
    if campo in DERIVADAS_FECHA and modelo.fecha:
        fechas = df[modelo.fecha]
        if campo == "__anio":
            return fechas.dt.year.astype("Int64").astype(str)
        if campo == "__trimestre":
            return fechas.dt.year.astype("Int64").astype(str) + "-T" + fechas.dt.quarter.astype("Int64").astype(str)
        return fechas.dt.strftime("%Y-%m")
    return df[campo].astype(str)


def pivote(df: pd.DataFrame, modelo: Modelo, filas: str, columnas: str, valores: str,
           funcion: str, mostrar: str) -> dict:
    """Tabla dinamica con totales, al estilo de Excel y Power BI."""
    if df.empty or not filas:
        return {"error": "Elige al menos un campo para las filas."}

    nombre_f, agregado = FUNCIONES_PIVOTE.get(funcion, FUNCIONES_PIVOTE["suma"])
    base = pd.DataFrame({"__f": _derivar(df, modelo, filas)})
    if columnas:
        base["__c"] = _derivar(df, modelo, columnas)
    if valores and valores in df.columns:
        base["__v"] = df[valores]
    else:
        base["__v"] = 1
        agregado, nombre_f = "count", "Conteo"
    if agregado in ("sum", "mean", "max", "min"):
        base["__v"] = pd.to_numeric(base["__v"], errors="coerce")

    if columnas:
        tabla = base.pivot_table(index="__f", columns="__c", values="__v", aggfunc=agregado,
                                 margins=True, margins_name="Total", observed=True)
    else:
        tabla = base.groupby("__f")["__v"].agg(agregado).to_frame("Total")
        tabla.loc["Total"] = base["__v"].agg(agregado)

    recortadas = len(tabla) > 41 or len(tabla.columns) > 25
    if len(tabla.columns) > 25:
        tabla = tabla[list(tabla.columns[:24]) + ["Total"]]
    if len(tabla) > 41:
        tabla = pd.concat([tabla.drop(index="Total").sort_values("Total", ascending=False).head(40),
                           tabla.loc[["Total"]]])
    elif filas not in DERIVADAS_FECHA:
        cuerpo = tabla.drop(index="Total").sort_values("Total", ascending=False)
        tabla = pd.concat([cuerpo, tabla.loc[["Total"]]])

    # % del total solo tiene sentido con medidas aditivas.
    if mostrar != "valor" and agregado in ("sum", "count"):
        if mostrar == "total":
            tabla = tabla / tabla.loc["Total", "Total"]
        elif mostrar == "fila":
            tabla = tabla.div(tabla["Total"], axis=0)
        elif mostrar == "columna":
            tabla = tabla.div(tabla.loc["Total"], axis=1)
        es_pct = True
    else:
        es_pct = False

    cuerpo = tabla.drop(index="Total", errors="ignore").drop(columns="Total", errors="ignore")
    maximo = float(np.nanmax(cuerpo.values)) if cuerpo.size and np.isfinite(cuerpo.values.astype(float)).any() else 0
    monetaria = bool(valores and _MONETARIO.search(_sin_tildes(valores))) and agregado in ("sum", "mean", "max", "min")

    def celda(v, total=False):
        if pd.isna(v):
            return {"texto": "", "intensidad": 0}
        texto = porcentaje(v) if es_pct else cifra(v, monetaria)
        intensidad = 0 if total or not maximo else max(0.0, min(float(v) / maximo, 1.0))
        return {"texto": texto, "intensidad": round(intensidad, 3), "crudo": float(v)}

    columnas_vista = [str(c) for c in tabla.columns]
    cuerpo_filas = []
    for indice, fila in tabla.iterrows():
        es_total = indice == "Total"
        cuerpo_filas.append({
            "etiqueta": str(indice),
            "total": es_total,
            "celdas": [celda(v, es_total or c == "Total") for c, v in fila.items()],
        })

    etiqueta = lambda c: DERIVADAS_FECHA.get(c, c)
    descripcion = f"{nombre_f} de {valores or 'registros'} por {etiqueta(filas)}"
    if columnas:
        descripcion += f" y {etiqueta(columnas)}"

    return {
        "columnas": columnas_vista,
        "filas": cuerpo_filas,
        "descripcion": descripcion,
        "mostrar": MOSTRAR_COMO.get(mostrar, "Valor") if es_pct else "Valor",
        "recortada": recortadas,
        "dax": _pivote_dax(modelo, filas, columnas, valores, funcion),
        "tabla": tabla,
    }


def _pivote_dax(modelo: Modelo, filas, columnas, valores, funcion) -> str:
    """La misma tabla expresada como consulta DAX (SUMMARIZECOLUMNS)."""
    t = f"'{modelo.tabla}'"
    dax_fn = {"suma": "SUM", "promedio": "AVERAGE", "conteo": "COUNT", "distintos": "DISTINCTCOUNT",
              "maximo": "MAX", "minimo": "MIN"}.get(funcion, "SUM")
    expr = f"{dax_fn}({t}[{valores}])" if valores else f"COUNTROWS({t})"

    def campo(c):
        if c in DERIVADAS_FECHA and modelo.fecha:
            return {"__anio": f"{t}[Año]", "__trimestre": f"{t}[Trimestre]", "__mes": f"{t}[Mes]"}[c]
        return f"{t}[{c}]"

    grupos = [campo(filas)] + ([campo(columnas)] if columnas else [])
    return ("EVALUATE\nSUMMARIZECOLUMNS(\n    " + ",\n    ".join(grupos) +
            f',\n    "Valor", {expr}\n)')
