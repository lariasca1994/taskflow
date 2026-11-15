"""Nombre visible de las columnas de un conjunto de datos (los datos no cambian)."""

_CON_TILDE = {
    "categoria": "categoría", "region": "región", "pais": "país", "codigo": "código",
    "numero": "número", "dia": "día", "anio": "año", "telefono": "teléfono",
}


def etiqueta(nombre) -> str:
    """'categoria' -> 'categoría'; 'total_venta' -> 'total venta'."""
    texto = str(nombre or "")
    return " ".join(_CON_TILDE.get(p.lower(), p) for p in texto.replace("_", " ").split(" "))
