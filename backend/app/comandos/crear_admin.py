"""Crea o promueve la cuenta administradora de revision.

    python -m app.comandos.crear_admin correo@ejemplo.com "Nombre" contrasena

Si el correo ya existe (por ejemplo, porque ya te registraste desde
/registro), la cuenta se promueve a rol ADMIN y la contrasena no se toca:
basta con pasar cualquier valor de relleno en <contrasena> en ese caso.
Si no existe, se crea de una vez con rol ADMIN.

El rol ADMIN da acceso de solo lectura a /admin/tareas: todas las tareas
de todos los usuarios, sin poder editarlas ni eliminarlas. Es el mismo
patron que la cuenta ADMIN en Gestor de Casos QA y PRPagos.
"""

import sys

from app import repositorio
from app.security import cifrar


def crear_o_promover(email: str, nombre: str, password: str) -> None:
    existente = repositorio.buscar_usuario_por_email(email)

    if existente:
        if repositorio.hacer_admin(email):
            print(f"La cuenta {email} ya existia: se promovio a rol ADMIN.")
        else:
            print(f"No se pudo promover {email} (no deberia pasar si ya existia).")
        return

    if len(password) < 10:
        print("La contrasena debe tener al menos 10 caracteres.")
        sys.exit(1)

    usuario = repositorio.crear_usuario(nombre, email, cifrar(password), rol="ADMIN")
    if usuario:
        print(f"Cuenta ADMIN creada para {email}.")
    else:
        print(f"No se pudo crear la cuenta para {email}.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print('Uso: python -m app.comandos.crear_admin <correo> "<nombre>" <contrasena>')
        sys.exit(1)

    crear_o_promover(sys.argv[1], sys.argv[2], sys.argv[3])
