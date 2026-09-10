"""Conexion con MongoDB, indices y almacenamiento de archivos."""

import gridfs
from pymongo import ASCENDING, MongoClient

from app.config import DATABASE_NAME, MONGO_URI

cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
base = cliente[DATABASE_NAME]

usuarios = base["usuarios"]
tareas = base["tareas"]
datasets = base["datasets"]

# Los archivos convertidos a Parquet viven en GridFS, dentro de la misma
# base. Asi la aplicacion no depende del disco local y funciona igual en
# un servicio con sistema de archivos efimero.
archivos = gridfs.GridFS(base)


def preparar_indices() -> None:
    """Idempotente: se ejecuta en cada arranque."""
    usuarios.create_index([("email", ASCENDING)], unique=True)

    tareas.create_index([("usuario_id", ASCENDING), ("estado", ASCENDING)])
    tareas.create_index([("usuario_id", ASCENDING), ("creada_en", ASCENDING)])

    datasets.create_index([("usuario_id", ASCENDING), ("subido_en", ASCENDING)])
    datasets.create_index([("ultimo_uso", ASCENDING)])
