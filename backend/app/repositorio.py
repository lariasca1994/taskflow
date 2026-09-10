"""Acceso a datos. Aisla el resto de la aplicacion de la forma de Mongo."""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.database import tareas, usuarios
from app.esquemas import Estado


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────── usuarios ──────────────────────────────


def crear_usuario(
    nombre: str, email: str, clave_cifrada: str, rol: str = "USUARIO"
) -> dict | None:
    """Devuelve el usuario creado, o None si el correo ya existe.

    rol="USUARIO" para el registro publico; el comando crear_admin es el
    unico camino para crear o promover una cuenta con rol="ADMIN".
    """
    documento = {
        "nombre": nombre,
        "email": email.lower(),
        "password": clave_cifrada,
        "rol": rol,
        "creado_en": _ahora(),
    }
    try:
        resultado = usuarios.insert_one(documento)
    except DuplicateKeyError:
        return None

    documento["_id"] = resultado.inserted_id
    return documento


def hacer_admin(email: str) -> bool:
    """Promueve una cuenta ya existente a rol ADMIN."""
    resultado = usuarios.update_one(
        {"email": email.lower()}, {"$set": {"rol": "ADMIN"}}
    )
    return resultado.matched_count > 0


def contar_usuarios() -> int:
    return usuarios.count_documents({})


def buscar_usuario_por_email(email: str) -> dict | None:
    return usuarios.find_one({"email": email.lower()})


def actualizar_password(usuario_id: str, nuevo_hash: str) -> None:
    """Reemplaza el hash guardado. Se usa al migrar de esquema."""
    usuarios.update_one(
        {"_id": ObjectId(usuario_id)}, {"$set": {"password": nuevo_hash}}
    )


def buscar_usuario(usuario_id: str) -> dict | None:
    if not ObjectId.is_valid(usuario_id):
        return None
    return usuarios.find_one({"_id": ObjectId(usuario_id)})


# ──────────────────────────────── tareas ───────────────────────────────


def crear_tarea(usuario_id: str, datos: dict) -> dict:
    documento = {
        **datos,
        "usuario_id": ObjectId(usuario_id),
        "estado": Estado.PENDIENTE.value,
        "creada_en": _ahora(),
        "completada_en": None,
    }
    documento["_id"] = tareas.insert_one(documento).inserted_id
    return documento


def listar_tareas(
    usuario_id: str,
    estado: str | None = None,
    categoria: str | None = None,
    buscar: str | None = None,
) -> list[dict]:
    filtro: dict = {"usuario_id": ObjectId(usuario_id)}

    if estado:
        filtro["estado"] = estado
    if categoria:
        filtro["categoria"] = categoria
    if buscar:
        # $regex sobre entrada del usuario: se escapa para que no pueda
        # inyectar una expresion regular costosa o inesperada.
        import re

        filtro["titulo"] = {"$regex": re.escape(buscar), "$options": "i"}

    orden = [("estado", 1), ("prioridad", -1), ("creada_en", -1)]
    return list(tareas.find(filtro).sort(orden))


def obtener_tarea(usuario_id: str, tarea_id: str) -> dict | None:
    """La pertenencia va en el filtro: nadie alcanza la tarea de otro."""
    if not ObjectId.is_valid(tarea_id):
        return None
    return tareas.find_one(
        {"_id": ObjectId(tarea_id), "usuario_id": ObjectId(usuario_id)}
    )


def cambiar_estado(usuario_id: str, tarea_id: str, estado: Estado) -> dict | None:
    if not ObjectId.is_valid(tarea_id):
        return None

    cambios = {"estado": estado.value}
    cambios["completada_en"] = _ahora() if estado == Estado.COMPLETADA else None

    return tareas.find_one_and_update(
        {"_id": ObjectId(tarea_id), "usuario_id": ObjectId(usuario_id)},
        {"$set": cambios},
        return_document=True,
    )


def actualizar_tarea(usuario_id: str, tarea_id: str, datos: dict) -> dict | None:
    if not ObjectId.is_valid(tarea_id):
        return None
    return tareas.find_one_and_update(
        {"_id": ObjectId(tarea_id), "usuario_id": ObjectId(usuario_id)},
        {"$set": datos},
        return_document=True,
    )


def eliminar_tarea(usuario_id: str, tarea_id: str) -> bool:
    if not ObjectId.is_valid(tarea_id):
        return False
    resultado = tareas.delete_one(
        {"_id": ObjectId(tarea_id), "usuario_id": ObjectId(usuario_id)}
    )
    return resultado.deleted_count == 1


def categorias_de(usuario_id: str) -> list[str]:
    return sorted(tareas.distinct("categoria", {"usuario_id": ObjectId(usuario_id)}))


def listar_todas_las_tareas(limite: int = 300) -> list[dict]:
    """Solo para el admin: tareas de todos los usuarios, mas recientes
    primero, con el nombre y correo del dueno ya resuelto (evita una
    consulta a usuarios por cada fila en la plantilla)."""
    pipeline = [
        {"$sort": {"creada_en": -1}},
        {"$limit": limite},
        {
            "$lookup": {
                "from": "usuarios",
                "localField": "usuario_id",
                "foreignField": "_id",
                "as": "_dueno",
            }
        },
        {"$unwind": "$_dueno"},
    ]
    return list(tareas.aggregate(pipeline))


def a_salida_admin(documento: dict) -> dict:
    """Como a_salida, agregando quien es el dueno de la tarea."""
    salida = a_salida(documento)
    salida["usuario_nombre"] = documento["_dueno"]["nombre"]
    salida["usuario_email"] = documento["_dueno"]["email"]
    return salida


def a_salida(documento: dict) -> dict:
    """Convierte un documento de Mongo al formato de la API."""
    return {
        "id": str(documento["_id"]),
        "titulo": documento["titulo"],
        "descripcion": documento.get("descripcion"),
        "categoria": documento.get("categoria", "general"),
        "prioridad": documento.get("prioridad", "media"),
        "estado": documento["estado"],
        "fecha_limite": documento.get("fecha_limite"),
        "creada_en": documento["creada_en"],
        "completada_en": documento.get("completada_en"),
    }
