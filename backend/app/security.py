"""Contrasenas y sesiones.

Sobre las contrasenas
---------------------
No se cifran: se hashean. El cifrado es reversible, y en una filtracion
bastaria la clave para recuperar todas las contrasenas en claro. El hash
es de una sola via: nadie, ni el propio sistema, puede deshacerlo.

Se aplican tres capas:

  1. Pimiento (HMAC-SHA256 con un secreto del servidor). A diferencia de
     la sal, no se guarda junto al hash sino en la configuracion. Si
     alguien roba un volcado de la base sin el secreto, no puede siquiera
     probar contrasenas comunes contra los hashes.
     De paso resuelve el limite de 72 bytes de bcrypt: el HMAC produce
     siempre una entrada de longitud fija.

  2. bcrypt con sal unica por contrasena, generada automaticamente. Dos
     usuarios con la misma contrasena producen hashes distintos.

  3. Coste 12: bcrypt es deliberadamente lento. Cada intento de fuerza
     bruta cuesta tiempo de CPU al atacante.

Sobre las sesiones
------------------
Dos limites simultaneos: inactividad deslizante de 30 minutos, que se
renueva con cada peticion y protege el equipo desatendido; y expiracion
absoluta de 12 horas, que no se renueva y acota el dano si el token
llegara a filtrarse.
"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import (
    COOKIE_SESION,
    JWT_ALGORITMO,
    JWT_SECRET,
    PASSWORD_PEPPER,
    SESION_INACTIVIDAD_MIN,
    SESION_MAXIMA_HORAS,
)

# rounds=12: unas 250 ms por verificacion en hardware corriente. Suficiente
# para el usuario, costoso para quien intente millones de combinaciones.
_contexto = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# ───────────────────────────── contrasenas ─────────────────────────────


def _con_pimiento(clave: str) -> str:
    """Combina la contrasena con el secreto del servidor.

    Se usa HMAC y no una concatenacion simple porque HMAC esta disenado
    para mezclar una clave con un mensaje sin exponer ninguno de los dos.
    El resultado se pasa a base64 para que bcrypt reciba texto.
    """
    firma = hmac.new(
        PASSWORD_PEPPER.encode("utf-8"),
        clave.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(firma).decode("ascii")


def cifrar(clave: str) -> str:
    """Devuelve el hash que se guarda en la base."""
    return _contexto.hash(_con_pimiento(clave))


def verificar(clave: str, almacenado: str) -> bool:
    """Comprueba una contrasena contra el hash guardado."""
    valido, _ = verificar_y_migrar(clave, almacenado)
    return valido


def verificar_y_migrar(clave: str, almacenado: str) -> tuple[bool, str | None]:
    """Verifica y, si el hash es de un esquema anterior, devuelve el nuevo.

    Permite introducir el pimiento sin obligar a nadie a restablecer su
    contrasena: la cuenta se actualiza sola en el siguiente ingreso.

    Returns:
        (es_valida, hash_actualizado_o_None)
    """
    try:
        if _contexto.verify(_con_pimiento(clave), almacenado):
            return True, None
    except ValueError:
        pass

    # Esquema anterior: bcrypt directo sobre la contrasena, sin pimiento.
    try:
        if _contexto.verify(clave, almacenado):
            return True, cifrar(clave)
    except ValueError:
        pass

    return False, None


# ─────────────────────────────── sesiones ──────────────────────────────


def _marca(momento: datetime) -> int:
    return int(momento.timestamp())


def crear_token(usuario_id: str, email: str, inicio: datetime | None = None) -> str:
    ahora = datetime.now(timezone.utc)
    inicio = inicio or ahora

    return jwt.encode(
        {
            "sub": usuario_id,
            "email": email,
            "ini": _marca(inicio),                       # ingreso original
            "act": _marca(ahora),                        # ultima actividad
            "exp": inicio + timedelta(hours=SESION_MAXIMA_HORAS),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITMO,
    )


def leer_token(token: str) -> dict | None:
    """Devuelve la carga si el token es valido y la sesion sigue viva."""
    try:
        carga = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITMO])
    except jwt.PyJWTError:
        return None

    ahora = datetime.now(timezone.utc)
    inactividad = ahora - datetime.fromtimestamp(carga["act"], tz=timezone.utc)

    if inactividad > timedelta(minutes=SESION_INACTIVIDAD_MIN):
        return None

    return carga


def renovar(carga: dict) -> str:
    """Emite un token nuevo conservando el inicio original de la sesion."""
    inicio = datetime.fromtimestamp(carga["ini"], tz=timezone.utc)
    return crear_token(carga["sub"], carga["email"], inicio)


__all__ = [
    "cifrar",
    "verificar",
    "verificar_y_migrar",
    "crear_token",
    "leer_token",
    "renovar",
    "COOKIE_SESION",
]
