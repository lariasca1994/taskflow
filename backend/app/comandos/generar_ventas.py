"""Genera archivos de ventas simuladas para probar el modulo de datos.

    python -m app.comandos.generar_ventas                 # 3 archivos distintos en ../files
    python -m app.comandos.generar_ventas --semilla 4821  # reproduce un lote concreto

Cada archivo sale con su propia semilla, y por eso con otro volumen,
otro periodo y otro escenario de negocio. El mismo simulador alimenta
el boton "Generar lote" de la pagina Datos.
"""

import argparse
import json
from pathlib import Path

from app import generador

SALIDA = Path(__file__).resolve().parents[3] / "files"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--semilla", type=int, help="reproduce un lote concreto")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()
    args.salida.mkdir(parents=True, exist_ok=True)

    # Un archivo por formato, cada uno de un tamaño distinto.
    pedidos = [("csv", "grande"), ("xlsx", "mediano"), ("json", "pequeno")]
    for i, (formato, volumen) in enumerate(pedidos):
        semilla = args.semilla + i if args.semilla else None
        df, ficha = generador.generar_ventas(volumen, semilla)
        ruta = args.salida / f"ventas_{ficha['semilla']}.{formato}"

        if formato == "csv":
            ruta.write_bytes(generador.a_csv(df))
        elif formato == "xlsx":
            df.to_excel(ruta, index=False)
        else:
            registros = json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))
            for r in registros:
                r["fecha"] = r["fecha"][:10]
            ruta.write_text(json.dumps(registros, ensure_ascii=False, indent=1), encoding="utf-8")

        print(f"{ruta.name}: {ficha['filas']:,} filas, {ficha['desde']} a {ficha['hasta']}, "
              f"tendencia {ficha['crecimiento']:+.1f} %, temporada alta en {ficha['mes_pico']}")


if __name__ == "__main__":
    main()
