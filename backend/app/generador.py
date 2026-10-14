"""Generador de ventas simuladas para probar el tablero.

Cada ejecucion arma un escenario de negocio propio a partir de una
semilla: cuantas filas, que meses cubre, si la empresa crece o se
contrae, en que mes tiene su temporada alta, que region y que canal
pesan mas y si hubo algun evento (una promocion o un desabastecimiento).
Por eso dos lotes generados nunca se parecen, y el mismo lote se puede
reproducir con su semilla.
"""

import secrets
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

VOLUMENES = {
    "aleatorio": ("Aleatorio", 600, 20000),
    "pequeno": ("Pequeño · 500 a 2.000 filas", 500, 2000),
    "mediano": ("Mediano · 2.000 a 8.000 filas", 2000, 8000),
    "grande": ("Grande · 8.000 a 20.000 filas", 8000, 20000),
}

REGIONES = ["Bogotá", "Antioquia", "Valle del Cauca", "Atlántico", "Santander", "Eje Cafetero"]
CANALES = ["Tienda física", "E-commerce", "Distribuidor", "Marketplace"]
VENDEDORES = ["A. Rojas", "C. Ramírez", "D. Mejía", "J. Peña", "L. Gómez", "M. Torres",
              "S. Vargas", "P. Ríos", "V. Castro"]

# Precio base por producto; cada escenario lo mueve hasta un 15 %.
CATALOGO = {
    "Café": {"Café de origen 500 g": 38900, "Café molido 250 g": 18500,
             "Cápsulas x10": 24900, "Café en grano 1 kg": 59600},
    "Cuidado": {"Crema corporal": 24100, "Jabón artesanal": 19800,
                "Aceite esencial": 32500},
    "Snacks": {"Barra de cereal": 8900, "Chips de plátano": 10300,
               "Mix de frutos secos": 16700},
    "Bebidas": {"Té frío": 6900, "Agua saborizada": 5200, "Kombucha": 11800},
}

# Margen bruto tipico de cada categoria.
MARGEN = {"Café": 0.42, "Cuidado": 0.55, "Snacks": 0.33, "Bebidas": 0.28}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _pesos(rng: np.random.Generator, n: int, concentracion: float) -> np.ndarray:
    """Reparto aleatorio que suma 1. Concentracion baja = mas desigual."""
    return rng.dirichlet(np.full(n, concentracion))


def generar_ventas(volumen: str = "aleatorio", semilla: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Devuelve el DataFrame y la ficha del escenario que lo produjo."""
    if semilla is None:
        semilla = secrets.randbelow(900_000) + 100_000

    rng = np.random.default_rng(semilla)
    _, minimo, maximo = VOLUMENES.get(volumen, VOLUMENES["aleatorio"])
    filas = int(rng.integers(minimo, maximo + 1))

    # ── periodo ──────────────────────────────────────────────────────────
    meses = int(rng.integers(9, 31))
    fin = pd.Timestamp(date.today()) - pd.Timedelta(days=int(rng.integers(0, 20)))
    inicio = (fin - pd.DateOffset(months=meses)).normalize()
    dias = pd.date_range(inicio, fin, freq="D")
    t = np.linspace(0, 1, len(dias))

    # ── escenario ────────────────────────────────────────────────────────
    crecimiento = float(rng.uniform(-0.30, 0.65))          # variacion total del periodo
    amplitud = float(rng.uniform(0.05, 0.40))               # fuerza de la temporada
    mes_pico = int(rng.integers(1, 13))
    ruido = float(rng.uniform(0.04, 0.18))

    tendencia = 1 + crecimiento * t
    temporada = 1 + amplitud * np.cos(2 * np.pi * (dias.month.to_numpy() - mes_pico) / 12)
    semana = np.array([1.0, 0.95, 0.97, 1.02, 1.18, 1.32, 0.78])[dias.dayofweek.to_numpy()]
    intensidad = tendencia * temporada * semana * rng.lognormal(0, ruido, len(dias))

    evento = None
    if rng.random() < 0.7 and meses >= 4:
        tipo = rng.choice(["promocion", "desabastecimiento"])
        centro = int(rng.integers(len(dias) // 5, len(dias) - 15))
        ancho = int(rng.integers(12, 35))
        factor = float(rng.uniform(1.6, 2.4)) if tipo == "promocion" else float(rng.uniform(0.35, 0.6))
        intensidad[centro:centro + ancho] *= factor
        evento = {
            "tipo": str(tipo),
            "desde": dias[centro].date().isoformat(),
            "dias": ancho,
            "factor": round(factor, 2),
        }

    fechas = rng.choice(dias.to_numpy(), size=filas, p=intensidad / intensidad.sum())

    # ── dimensiones ──────────────────────────────────────────────────────
    peso_region = _pesos(rng, len(REGIONES), 2.5)
    regiones = rng.choice(REGIONES, size=filas, p=peso_region)

    # El canal digital gana o pierde terreno con el tiempo segun el escenario.
    giro_digital = float(rng.uniform(-0.15, 0.35))
    base_canal = _pesos(rng, len(CANALES), 4)
    pos = (fechas - dias[0].to_datetime64()) / (dias[-1] - dias[0]).to_timedelta64()
    pesos = np.tile(base_canal, (filas, 1))
    pesos[:, 1] = np.maximum(pesos[:, 1] * (1 + giro_digital * pos * 2), 0.02)
    acumulado = (pesos / pesos.sum(axis=1, keepdims=True)).cumsum(axis=1)
    elegido = (rng.random((filas, 1)) > acumulado).sum(axis=1).clip(0, len(CANALES) - 1)
    canales = np.array(CANALES, dtype=object)[elegido]

    categorias_lista = list(CATALOGO)
    peso_categoria = _pesos(rng, len(categorias_lista), 3)
    categorias = rng.choice(categorias_lista, size=filas, p=peso_categoria)

    ajuste_precio = {
        prod: precio * rng.uniform(0.85, 1.15)
        for cat in CATALOGO.values() for prod, precio in cat.items()
    }
    productos = np.array([rng.choice(list(CATALOGO[c])) for c in categorias])
    precio = np.array([ajuste_precio[p] for p in productos]).round(-2)

    plantilla = list(rng.choice(VENDEDORES, size=int(rng.integers(5, len(VENDEDORES) + 1)), replace=False))
    desempeno = _pesos(rng, len(plantilla), 3)
    vendedores = rng.choice(plantilla, size=filas, p=desempeno).astype(object)

    # ── medidas ──────────────────────────────────────────────────────────
    canal_mayorista = np.isin(canales, ["Distribuidor"])
    unidades = rng.poisson(np.where(canal_mayorista, 22, 7)) + 1

    descuento = rng.choice([0, 0.05, 0.10, 0.15, 0.20], size=filas,
                           p=_pesos(rng, 5, 1.5))
    total = (unidades * precio * (1 - descuento)).round(0)

    margen_base = np.array([MARGEN[c] for c in categorias])
    costo = (unidades * precio * (1 - margen_base * rng.uniform(0.85, 1.15, filas))).round(0)

    satisfaccion = np.clip(
        rng.normal(4.1 + descuento * 2 - canal_mayorista * 0.3, 0.55), 1, 5
    ).round(1)

    df = pd.DataFrame({
        "id_venta": np.arange(1, filas + 1),
        "fecha": pd.to_datetime(fechas).normalize(),
        "region": regiones,
        "canal": canales,
        "categoria": categorias,
        "producto": productos,
        "vendedor": vendedores,
        "unidades": unidades,
        "precio_unitario": precio,
        "descuento": descuento,
        "total_venta": total,
        "costo": costo,
        "margen": total - costo,
        "satisfaccion": satisfaccion,
    }).sort_values("fecha", kind="stable").reset_index(drop=True)
    df["id_venta"] = np.arange(10001, 10001 + filas)

    # Datos reales nunca llegan completos: algunos huecos a proposito.
    tasa_nulos = float(rng.uniform(0, 0.05))
    df.loc[rng.random(filas) < tasa_nulos, "satisfaccion"] = np.nan
    df.loc[rng.random(filas) < tasa_nulos / 2, "vendedor"] = None

    ficha = {
        "tipo": "generado",
        "semilla": int(semilla),
        "volumen": volumen,
        "filas": filas,
        "desde": df["fecha"].min().date().isoformat(),
        "hasta": df["fecha"].max().date().isoformat(),
        "meses": meses,
        "crecimiento": round(crecimiento * 100, 1),
        "estacionalidad": round(amplitud * 100, 1),
        "mes_pico": MESES[mes_pico - 1],
        "giro_digital": round(giro_digital * 100, 1),
        "region_lider": REGIONES[int(np.argmax(peso_region))],
        "nulos": round(tasa_nulos * 100, 1),
        "evento": evento,
        "creado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return df, ficha


def a_csv(df: pd.DataFrame) -> bytes:
    """CSV con fechas ISO, el formato que espera cualquier herramienta de BI."""
    return df.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8")
