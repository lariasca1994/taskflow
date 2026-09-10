"""Modelos de entrada y salida de la API."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class Estado(StrEnum):
    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"


class Prioridad(StrEnum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class RegistroEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginEntrada(BaseModel):
    email: EmailStr
    password: str


class UsuarioSalida(BaseModel):
    id: str
    nombre: str
    email: EmailStr


class TareaEntrada(BaseModel):
    titulo: str = Field(min_length=3, max_length=140)
    descripcion: str | None = Field(default=None, max_length=1000)
    categoria: str = Field(default="general", max_length=40)
    prioridad: Prioridad = Prioridad.MEDIA
    fecha_limite: datetime | None = None


class TareaSalida(BaseModel):
    id: str
    titulo: str
    descripcion: str | None
    categoria: str
    prioridad: Prioridad
    estado: Estado
    fecha_limite: datetime | None
    creada_en: datetime
    completada_en: datetime | None
