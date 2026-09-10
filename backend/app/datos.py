"""Modulo de analisis de archivos.

El archivo que sube el usuario se lee una sola vez y se guarda convertido
a Parquet dentro de GridFS. Los filtros posteriores leen de ahi: Parquet
es columnar y comprimido, asi que cargar dos columnas de un archivo de
diez megas cuesta milisegundos en lugar de releer y reinterpretar el
original en cada cambio.
"""

import io
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
from bson import ObjectId

from app.config import (
    ARCHIVO_HORAS_VIDA,
    ARCHIVO_MAX_FILAS,
    ARCHIVOS_POR_USUARIO,
)
from app.database import archivos, datasets


class ErrorDeArchivo(Exception):
    """Problema esperable con el archivo; se muestra tal cual al usuario."""


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────── lectura ───────────────────────────────


def _leer(contenido: bytes, extension: str) -> pd.DataFrame:
    """Convierte los bytes recibidos en un DataFrame.

    Solo se admiten formatos de datos. Formatos que deserializan objetos
    de Python, como pickle, quedan fuera a proposito: permiten ejecutar
    codigo al abrirlos.
    """
    buffer = io.BytesIO(contenido)

    try:
        if extension == ".csv":
            # sep=None con el motor de Python detecta el separador solo:
            # los CSV en espanol suelen venir con punto y coma.
            return pd.read_csv(buffer, sep=None, engine="python", encoding_errors="replace")

        if extension == ".xlsx":
            return pd.read_excel(buffer, engine="openpyxl")

        if extension == ".json":
            crudo = json.loads(contenido.decode("utf-8", errors="replace"))

            if isinstance(crudo, dict):
                # Se acepta {"datos": [...]} tomando la primera lista util
                listas = [v for v in crudo.values() if isinstance(v, list)]
                if not listas:
                    raise ErrorDeArchivo(
                        "El JSON debe ser un arreglo de objetos o contener uno."
                    )
                crudo = listas[0]

            if not isinstance(crudo, list) or not crudo:
                raise ErrorDeArchivo("El JSON debe ser un arreglo de objetos.")

            if any(isinstance(v, (dict, list)) for v in crudo[0].values()):
                raise ErrorDeArchivo(
                    "El JSON tiene estructuras anidadas. Aplanalo antes de subirlo: "
                    "no hay una forma unica de convertirlo a tabla."
                )

            return pd.json_normalize(crudo)

    except ErrorDeArchivo:
        raise
    except Exception as error:
        raise ErrorDeArchivo(f"No se pudo leer el archivo: {error}") from error

    raise ErrorDeArchivo("Formato no admitido.")


# ─────────────────────────────── perfilado ─────────────────────────────


def _tipo_legible(serie: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(serie):
        return "numerica"
    if pd.api.types.is_datetime64_any_dtype(serie):
        return "fecha"
    return "texto"


def perfilar(df: pd.DataFrame) -> dict:
    """Resumen que el usuario ve apenas termina la carga."""
    columnas = []

    for nombre in df.columns:
        serie = df[nombre]
        nulos = int(serie.isna().sum())

        detalle = {
            "nombre": str(nombre),
            "tipo": _tipo_legible(serie),
            "nulos": nulos,
            "porcentaje_nulos": round(nulos / len(df) * 100, 1) if len(df) else 0.0,
            "unicos": int(serie.nunique(dropna=True)),
        }

        if detalle["tipo"] == "numerica" and serie.notna().any():
            detalle |= {
                "minimo": round(float(serie.min()), 2),
                "maximo": round(float(serie.max()), 2),
                "media": round(float(serie.mean()), 2),
                "mediana": round(float(serie.median()), 2),
            }

        columnas.append(detalle)

    return {
        "filas": int(len(df)),
        "columnas": int(len(df.columns)),
        "memoria_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
        "detalle": columnas,
    }


# ──────────────────────────────── guardado ─────────────────────────────


def registrar(usuario_id: str, nombre: str, contenido: bytes, extension: str) -> dict:
    """Valida, convierte y almacena. Devuelve el documento del dataset."""
    if datasets.count_documents({"usuario_id": ObjectId(usuario_id)}) >= ARCHIVOS_POR_USUARIO:
        raise ErrorDeArchivo(
            f"Alcanzaste el limite de {ARCHIVOS_POR_USUARIO} archivos. "
            "Elimina alguno para subir otro."
        )

    df = _leer(contenido, extension)

    if df.empty:
        raise ErrorDeArchivo("El archivo no tiene filas.")

    if len(df) > ARCHIVO_MAX_FILAS:
        raise ErrorDeArchivo(
            f"El archivo tiene {len(df):,} filas y el limite es {ARCHIVO_MAX_FILAS:,}."
        )

    # Nombres de columna limpios: evita duplicados y espacios sobrantes
    df.columns = [str(c).strip() or f"columna_{i}" for i, c in enumerate(df.columns)]

    perfil = perfilar(df)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, compression="snappy")
    buffer.seek(0)

    id_archivo = archivos.put(buffer.read(), filename=f"{usuario_id}.parquet")

    documento = {
        "usuario_id": ObjectId(usuario_id),
        "nombre": nombre,
        "extension": extension,
        "archivo_id": id_archivo,
        "perfil": perfil,
        "subido_en": _ahora(),
        "ultimo_uso": _ahora(),
    }
    documento["_id"] = datasets.insert_one(documento).inserted_id

    return documento


def listar(usuario_id: str) -> list[dict]:
    return list(
        datasets.find({"usuario_id": ObjectId(usuario_id)}).sort("subido_en", -1)
    )


def obtener(usuario_id: str, dataset_id: str) -> dict | None:
    """La pertenencia va en el filtro: nadie alcanza el archivo de otro."""
    if not ObjectId.is_valid(dataset_id):
        return None

    documento = datasets.find_one(
        {"_id": ObjectId(dataset_id), "usuario_id": ObjectId(usuario_id)}
    )

    if documento:
        datasets.update_one({"_id": documento["_id"]}, {"$set": {"ultimo_uso": _ahora()}})

    return documento


def cargar_tabla(documento: dict, columnas: list[str] | None = None) -> pd.DataFrame:
    """Lee el Parquet desde GridFS, opcionalmente solo algunas columnas."""
    datos = archivos.get(documento["archivo_id"]).read()
    return pd.read_parquet(io.BytesIO(datos), columns=columnas)


def eliminar(usuario_id: str, dataset_id: str) -> bool:
    documento = datasets.find_one_and_delete(
        {"_id": ObjectId(dataset_id), "usuario_id": ObjectId(usuario_id)}
    )

    if not documento:
        return False

    archivos.delete(documento["archivo_id"])
    return True


def eliminar_todos(usuario_id: str) -> int:
    """Se invoca al cerrar sesion."""
    borrados = 0

    for documento in datasets.find({"usuario_id": ObjectId(usuario_id)}):
        archivos.delete(documento["archivo_id"])
        borrados += 1

    datasets.delete_many({"usuario_id": ObjectId(usuario_id)})
    return borrados


def barrer_caducados() -> int:
    """Elimina los archivos sin uso reciente.

    Necesario porque casi nadie pulsa "Salir": sin este barrido, los
    archivos de quien cierra la pestana quedarian huerfanos para siempre.
    """
    limite = _ahora() - timedelta(hours=ARCHIVO_HORAS_VIDA)
    borrados = 0

    for documento in datasets.find({"ultimo_uso": {"$lt": limite}}):
        archivos.delete(documento["archivo_id"])
        datasets.delete_one({"_id": documento["_id"]})
        borrados += 1

    return borrados
