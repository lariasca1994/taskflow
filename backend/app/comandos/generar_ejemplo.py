"""Genera tareas de ejemplo para poblar el panel de analitica.

    python -m app.comandos.generar_ejemplo correo@ejemplo.com        # volumen al azar
    python -m app.comandos.generar_ejemplo correo@ejemplo.com 180    # volumen fijo

Sin datos suficientes el panel se ve pobre: la serie semanal necesita
varios meses de historia para tener forma. Este comando crea tareas
repartidas en el tiempo, con categorias, prioridades y tiempos de cierre
verosimiles. Cada ejecucion arma un perfil distinto (volumen, categorias
que mas pesan, ritmo de cierre, cuanta historia), asi que dos corridas
dejan paneles visiblemente diferentes.
"""

import random
import sys
from datetime import datetime, timedelta, timezone

from app.database import tareas, usuarios

CATEGORIAS = ["trabajo", "personal", "estudio", "hogar", "salud", "finanzas"]
PRIORIDADES = ["baja", "media", "alta"]

VERBOS = ["Revisar", "Preparar", "Enviar", "Actualizar", "Coordinar",
          "Documentar", "Analizar", "Corregir", "Planear", "Cerrar"]
OBJETOS = ["el informe mensual", "la propuesta al cliente", "el respaldo de la base",
           "las facturas del mes", "la agenda de la semana", "el material del curso",
           "el presupuesto", "la revision de codigo", "las metricas del tablero",
           "la lista del mercado", "la cita medica", "el pago de servicios"]


def generar(email: str, cantidad: int | None = None) -> None:
    usuario = usuarios.find_one({"email": email.lower()})

    if not usuario:
        print(f"No existe ninguna cuenta con el correo {email}.")
        sys.exit(1)

    # Perfil de esta corrida: todo lo que cambia de una ejecucion a otra.
    cantidad = cantidad or random.randint(60, 420)
    historia = random.randint(60, 240)
    pesos_categoria = [random.uniform(0.3, 3) for _ in CATEGORIAS]
    pesos_prioridad = [random.uniform(1, 5) for _ in PRIORIDADES]
    ritmo = random.uniform(-0.15, 0.2)          # equipo mas o menos cumplido
    horas_tipicas = random.uniform(12, 96)      # cuanto tarda en cerrar

    ahora = datetime.now(timezone.utc)
    lote = []

    for _ in range(cantidad):
        # Distribucion sesgada hacia fechas recientes, como ocurre en la
        # realidad: se acumulan mas tareas de las ultimas semanas.
        dias_atras = int(random.triangular(0, historia, historia * random.uniform(0.05, 0.4)))
        creada = ahora - timedelta(days=dias_atras, hours=random.randint(0, 23))

        prioridad = random.choices(PRIORIDADES, weights=pesos_prioridad)[0]

        # Las tareas antiguas y las de prioridad alta se cierran mas.
        probabilidad = 0.45 + ritmo + min(dias_atras / 200, 0.35)
        if prioridad == "alta":
            probabilidad += 0.1

        completada = random.random() < probabilidad

        documento = {
            "usuario_id": usuario["_id"],
            "titulo": f"{random.choice(VERBOS)} {random.choice(OBJETOS)}",
            "descripcion": None,
            "categoria": random.choices(CATEGORIAS, weights=pesos_categoria)[0],
            "prioridad": prioridad,
            "estado": "pendiente",
            "fecha_limite": creada + timedelta(days=random.randint(1, 21)),
            "creada_en": creada,
            "completada_en": None,
        }

        if completada:
            horas = random.triangular(1, 240, horas_tipicas)
            cierre = creada + timedelta(hours=horas)

            if cierre <= ahora:
                documento["estado"] = "completada"
                documento["completada_en"] = cierre
        elif random.random() < 0.25:
            documento["estado"] = "en_progreso"

        lote.append(documento)

    tareas.insert_many(lote)
    print(f"Se crearon {len(lote)} tareas de ejemplo para {email} "
          f"({historia} dias de historia, cierre tipico {horas_tipicas:.0f} h).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m app.comandos.generar_ejemplo <correo> [cantidad]")
        sys.exit(1)

    generar(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
