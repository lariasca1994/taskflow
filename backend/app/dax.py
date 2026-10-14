"""Interprete de un subconjunto de DAX sobre pandas.

No es Power BI: es la parte de DAX que se usa en el dia a dia de un
informe gerencial, evaluada con pandas, para que el usuario vea la
formula y su resultado sobre su propio archivo. Las medidas del catalogo
del tablero se escriben aqui mismo en DAX, asi que lo que se muestra es
exactamente lo que calcula la cifra.

Se analiza con un parser propio (descenso recursivo). Nunca se pasa el
texto a eval: el usuario escribe la formula y solo se ejecutan las
funciones de esta lista.

Soportado
  Agregaciones   SUM AVERAGE MIN MAX COUNT COUNTROWS DISTINCTCOUNT MEDIAN
  Escalares      DIVIDE ROUND ABS IF BLANK
  Contexto       CALCULATE(expr, filtro...) con filtros col = valor, <>, >, <,
                 >=, <=, col IN {..}, ALL(col), DATEADD(col, n, DAY|MONTH|
                 QUARTER|YEAR), SAMEPERIODLASTYEAR(col), DATESYTD(col),
                 DATESMTD(col), DATESINPERIOD(col, LASTDATE(col), n, unidad)
  Atajos         TOTALYTD(expr, col), TOTALMTD(expr, col)
  Referencias    Tabla[columna], 'Tabla'[columna], [columna], [Medida]
"""

import math
import re
from dataclasses import dataclass, field

import pandas as pd
from markupsafe import Markup, escape


class ErrorDax(Exception):
    """Formula invalida o no soportada; el mensaje se muestra al usuario."""


# ─────────────────────────────── contexto ──────────────────────────────


@dataclass
class Contexto:
    """Filas visibles mas la ventana de fechas activa.

    `base` ya trae los segmentadores aplicados. La ventana [inicio, fin)
    es la que mueven las funciones de inteligencia de tiempo, igual que en
    DAX el filtro de fechas es el que DATEADD desplaza.
    """

    base: pd.DataFrame
    columna_fecha: str | None
    inicio: pd.Timestamp | None
    fin: pd.Timestamp | None
    filtros: dict = field(default_factory=dict)
    # Se marca cuando un desplazamiento de fechas cae antes del primer dato:
    # mejor un BLANK que comparar contra un periodo a medias.
    sin_datos: bool = False

    def filas(self) -> pd.DataFrame:
        df = self.base
        if self.sin_datos:
            return df.iloc[0:0]
        if self.columna_fecha and self.inicio is not None:
            fechas = df[self.columna_fecha]
            df = df[(fechas >= self.inicio) & (fechas < self.fin)]
        for _, condicion in self.filtros.items():
            df = df[condicion(df)]
        return df


# ─────────────────────────────── lexico ────────────────────────────────

_TOKENS = re.compile(
    r"""
    (?P<espacio>\s+)
  | (?P<numero>\d+(?:\.\d+)?)
  | (?P<cadena>"(?:[^"]|"")*")
  | (?P<tabla>'(?:[^']|'')+')
  | (?P<corchete>\[[^\]]+\])
  | (?P<op><>|>=|<=|&&|\|\||[=<>+\-*/(),{}])
  | (?P<nombre>[A-Za-z_][A-Za-z0-9_\.]*)
    """,
    re.VERBOSE,
)


def _tokenizar(texto: str) -> list[tuple[str, str]]:
    salida, pos = [], 0
    while pos < len(texto):
        m = _TOKENS.match(texto, pos)
        if not m:
            raise ErrorDax(f"Caracter no reconocido cerca de: {texto[pos:pos + 12]!r}")
        pos = m.end()
        if m.lastgroup != "espacio":
            salida.append((m.lastgroup, m.group()))
    return salida


# ─────────────────────────────── arbol ─────────────────────────────────
# Nodos como tuplas: ("num", v) ("txt", v) ("col", nombre) ("ref", nombre)
# ("fn", NOMBRE, [args]) ("bin", op, a, b) ("neg", a) ("set", [valores])


class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def ver(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def tomar(self, valor=None):
        tipo, texto = self.ver()
        if tipo is None:
            raise ErrorDax("La formula termina antes de tiempo.")
        if valor is not None and texto.upper() != valor:
            raise ErrorDax(f"Se esperaba «{valor}» y aparecio «{texto}».")
        self.i += 1
        return tipo, texto

    def formula(self):
        nodo = self.logico()
        if self.i != len(self.t):
            raise ErrorDax(f"Sobra texto al final: «{self.t[self.i][1]}».")
        return nodo

    def logico(self):
        nodo = self.comparacion()
        while self.ver()[1] in ("&&", "||"):
            op = self.tomar()[1]
            nodo = ("bin", op, nodo, self.comparacion())
        return nodo

    def comparacion(self):
        nodo = self.suma()
        tipo, texto = self.ver()
        if texto in ("=", "<>", ">", "<", ">=", "<="):
            self.tomar()
            return ("bin", texto, nodo, self.suma())
        if tipo == "nombre" and texto.upper() == "IN":
            self.tomar()
            return ("bin", "IN", nodo, self.conjunto())
        return nodo

    def conjunto(self):
        self.tomar("{")
        valores = [self.suma()]
        while self.ver()[1] == ",":
            self.tomar()
            valores.append(self.suma())
        self.tomar("}")
        return ("set", valores)

    def suma(self):
        nodo = self.producto()
        while self.ver()[1] in ("+", "-"):
            op = self.tomar()[1]
            nodo = ("bin", op, nodo, self.producto())
        return nodo

    def producto(self):
        nodo = self.unario()
        while self.ver()[1] in ("*", "/"):
            op = self.tomar()[1]
            nodo = ("bin", op, nodo, self.unario())
        return nodo

    def unario(self):
        if self.ver()[1] == "-":
            self.tomar()
            return ("neg", self.unario())
        return self.atomo()

    def atomo(self):
        tipo, texto = self.tomar()

        if tipo == "numero":
            return ("num", float(texto))
        if tipo == "cadena":
            return ("txt", texto[1:-1].replace('""', '"'))
        if texto == "(":
            nodo = self.logico()
            self.tomar(")")
            return nodo
        if tipo == "corchete":
            return ("ref", texto[1:-1])
        if tipo == "tabla":
            # 'Tabla'[columna]: el nombre de tabla se ignora, hay una sola.
            if self.ver()[0] != "corchete":
                return ("tabla", texto[1:-1])
            return ("col", self.tomar()[1][1:-1])
        if tipo == "nombre":
            siguiente = self.ver()
            if siguiente[0] == "corchete":
                self.tomar()
                return ("col", siguiente[1][1:-1])
            if siguiente[1] == "(":
                self.tomar("(")
                args = []
                if self.ver()[1] != ")":
                    args.append(self.logico())
                    while self.ver()[1] == ",":
                        self.tomar()
                        args.append(self.logico())
                self.tomar(")")
                return ("fn", texto.upper(), args)
            if texto.upper() in ("TRUE", "FALSE"):
                return ("num", 1.0 if texto.upper() == "TRUE" else 0.0)
            if texto.upper() in UNIDADES:
                return ("txt", texto.upper())
            # Nombre suelto: puede ser una columna (region = "Bogotá") o el
            # nombre de la tabla (COUNTROWS(ventas)); se resuelve al evaluar.
            return ("col", texto)

        raise ErrorDax(f"No se esperaba «{texto}».")


def analizar(texto: str):
    """Texto DAX -> arbol. Acepta la forma 'Nombre = expresion'."""
    texto = texto.strip()
    if not texto:
        raise ErrorDax("Escribe una formula.")
    m = re.match(r"^\s*([^=\[\]()'\"]+?)\s*=(?![=])\s*(.+)$", texto, re.S)
    if m and not re.search(r"[<>]$", m.group(1)):
        texto = m.group(2)
    return _Parser(_tokenizar(texto)).formula()


# ─────────────────────────────── evaluacion ───────────────────────────

UNIDADES = {"DAY": "D", "MONTH": "M", "QUARTER": "Q", "YEAR": "Y"}
AGREGADORES = {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "DISTINCTCOUNT", "MEDIAN"}


def _desplazar(fecha: pd.Timestamp, n: int, unidad: str) -> pd.Timestamp:
    if unidad == "D":
        return fecha + pd.Timedelta(days=n)
    meses = {"M": 1, "Q": 3, "Y": 12}[unidad] * n
    return fecha + pd.DateOffset(months=meses)


class Evaluador:
    def __init__(self, columnas: list[str], medidas: dict[str, str] | None = None):
        self.columnas = set(columnas)
        self.medidas = {k.lower(): (k, v) for k, v in (medidas or {}).items()}
        self._arboles: dict[str, tuple] = {}
        self._pila: list[str] = []

    # -- utilidades
    def _columna(self, nodo) -> str:
        if nodo[0] in ("col", "ref") and nodo[1] in self.columnas:
            return nodo[1]
        raise ErrorDax(f"Se esperaba una columna del archivo y llego {_texto(nodo)}.")

    def _escalar(self, nodo, ctx):
        valor = self.evaluar(nodo, ctx)
        return valor

    # -- nucleo
    def evaluar(self, nodo, ctx: Contexto):
        tipo = nodo[0]

        if tipo in ("num", "txt"):
            return nodo[1]

        if tipo == "neg":
            v = self.evaluar(nodo[1], ctx)
            return None if v is None else -v

        if tipo == "ref":
            nombre = nodo[1]
            if nombre.lower() in self.medidas:
                return self._medida(nombre, ctx)
            if nombre in self.columnas:
                raise ErrorDax(f"[{nombre}] es una columna: usala dentro de SUM, AVERAGE, etc.")
            raise ErrorDax(f"No existe la medida ni la columna [{nombre}].")

        if tipo == "col":
            if nodo[1] not in self.columnas:
                raise ErrorDax(f"«{nodo[1]}» no es una columna del archivo ni una funcion soportada.")
            raise ErrorDax(f"La columna {nodo[1]} debe ir dentro de una agregacion (SUM, AVERAGE…).")

        if tipo == "tabla":
            raise ErrorDax(f"La tabla '{nodo[1]}' solo puede usarse dentro de COUNTROWS.")

        if tipo == "bin":
            return self._binario(nodo, ctx)

        if tipo == "fn":
            return self._funcion(nodo[1], nodo[2], ctx)

        raise ErrorDax("Expresion no soportada.")

    def _medida(self, nombre: str, ctx: Contexto):
        clave = nombre.lower()
        if clave in self._pila:
            raise ErrorDax(f"La medida [{nombre}] se referencia a si misma.")
        if clave not in self._arboles:
            self._arboles[clave] = analizar(self.medidas[clave][1])
        self._pila.append(clave)
        try:
            return self.evaluar(self._arboles[clave], ctx)
        finally:
            self._pila.pop()

    def _binario(self, nodo, ctx):
        _, op, a, b = nodo
        x, y = self.evaluar(a, ctx), self.evaluar(b, ctx)
        if op in ("+", "-", "*", "/"):
            if x is None and y is None:
                return None
            x, y = x or 0, y or 0
            if op == "/":
                if y == 0:
                    raise ErrorDax("Division por cero: usa DIVIDE(a, b) para evitarla.")
                return x / y
            return {"+": x + y, "-": x - y, "*": x * y}[op]
        if op == "&&":
            return float(bool(x) and bool(y))
        if op == "||":
            return float(bool(x) or bool(y))
        comparar = {"=": lambda: x == y, "<>": lambda: x != y, ">": lambda: x > y,
                    "<": lambda: x < y, ">=": lambda: x >= y, "<=": lambda: x <= y}
        if op in comparar:
            return float(comparar[op]())
        raise ErrorDax(f"Operador {op} fuera de lugar.")

    def _funcion(self, nombre, args, ctx: Contexto):
        if nombre in AGREGADORES:
            if len(args) != 1:
                raise ErrorDax(f"{nombre} recibe una columna.")
            serie = ctx.filas()[self._columna(args[0])]
            if nombre == "COUNT":
                return float(serie.count())
            if nombre == "DISTINCTCOUNT":
                return float(serie.nunique(dropna=True))
            serie = pd.to_numeric(serie, errors="coerce").dropna()
            if serie.empty:
                return None
            return float({"SUM": serie.sum, "AVERAGE": serie.mean, "MIN": serie.min,
                          "MAX": serie.max, "MEDIAN": serie.median}[nombre]())

        if nombre == "COUNTROWS":
            return float(len(ctx.filas()))

        if nombre == "DIVIDE":
            if len(args) not in (2, 3):
                raise ErrorDax("DIVIDE(numerador, denominador [, alternativo]).")
            num, den = self.evaluar(args[0], ctx), self.evaluar(args[1], ctx)
            if not den or num is None:
                return self.evaluar(args[2], ctx) if len(args) == 3 else None
            return num / den

        if nombre == "ROUND":
            v = self.evaluar(args[0], ctx)
            return None if v is None else round(v, int(self.evaluar(args[1], ctx)))

        if nombre == "ABS":
            v = self.evaluar(args[0], ctx)
            return None if v is None else abs(v)

        if nombre == "BLANK":
            return None

        if nombre == "IF":
            if len(args) not in (2, 3):
                raise ErrorDax("IF(condicion, si_verdadero [, si_falso]).")
            if self.evaluar(args[0], ctx):
                return self.evaluar(args[1], ctx)
            return self.evaluar(args[2], ctx) if len(args) == 3 else None

        if nombre == "CALCULATE":
            if not args:
                raise ErrorDax("CALCULATE(expresion, filtro...).")
            nuevo = Contexto(ctx.base, ctx.columna_fecha, ctx.inicio, ctx.fin, dict(ctx.filtros), ctx.sin_datos)
            for filtro in args[1:]:
                self._aplicar_filtro(filtro, nuevo)
            return self.evaluar(args[0], nuevo)

        if nombre in ("TOTALYTD", "TOTALMTD"):
            if len(args) != 2:
                raise ErrorDax(f"{nombre}(expresion, Tabla[fecha]).")
            interno = "DATESYTD" if nombre == "TOTALYTD" else "DATESMTD"
            return self._funcion("CALCULATE", [args[0], ("fn", interno, [args[1]])], ctx)

        if nombre in ("DATEADD", "SAMEPERIODLASTYEAR", "DATESYTD", "DATESMTD",
                      "DATESINPERIOD", "ALL", "LASTDATE"):
            raise ErrorDax(f"{nombre} solo puede usarse como filtro dentro de CALCULATE.")

        raise ErrorDax(f"La funcion {nombre} no esta soportada en este tablero.")

    def _aplicar_filtro(self, filtro, ctx: Contexto):
        """Modifica el contexto como lo haria un argumento de CALCULATE."""
        if filtro[0] == "fn":
            nombre, args = filtro[1], filtro[2]

            if nombre == "ALL":
                for arg in args or []:
                    col = self._columna(arg)
                    ctx.filtros.pop(col, None)
                    if col == ctx.columna_fecha:
                        ctx.inicio = ctx.fin = None
                if not args:
                    ctx.filtros.clear()
                    ctx.inicio = ctx.fin = None
                return

            if ctx.columna_fecha is None:
                raise ErrorDax(f"{nombre} necesita una columna de fecha en el archivo.")
            self._columna(args[0]) if args else None
            inicio, fin = self._ventana(ctx)

            if nombre == "DATEADD":
                n = int(self.evaluar(args[1], ctx))
                unidad = UNIDADES.get(str(self.evaluar(args[2], ctx)).upper())
                if not unidad:
                    raise ErrorDax("DATEADD usa DAY, MONTH, QUARTER o YEAR.")
                ctx.inicio, ctx.fin = _desplazar(inicio, n, unidad), _desplazar(fin, n, unidad)
                self._cubierto(ctx)
            elif nombre == "SAMEPERIODLASTYEAR":
                ctx.inicio, ctx.fin = _desplazar(inicio, -1, "Y"), _desplazar(fin, -1, "Y")
                self._cubierto(ctx)
            elif nombre == "DATESYTD":
                ultimo = fin - pd.Timedelta(days=1)
                ctx.inicio, ctx.fin = pd.Timestamp(ultimo.year, 1, 1), fin
            elif nombre == "DATESMTD":
                ultimo = fin - pd.Timedelta(days=1)
                ctx.inicio, ctx.fin = pd.Timestamp(ultimo.year, ultimo.month, 1), fin
            elif nombre == "DATESINPERIOD":
                if len(args) != 4:
                    raise ErrorDax("DATESINPERIOD(Tabla[fecha], LASTDATE(Tabla[fecha]), -n, MONTH).")
                n = int(self.evaluar(args[2], ctx))
                unidad = UNIDADES.get(str(self.evaluar(args[3], ctx)).upper(), "M")
                if n < 0:
                    ctx.inicio, ctx.fin = _desplazar(fin, n, unidad), fin
                else:
                    ctx.inicio, ctx.fin = inicio, _desplazar(inicio, n, unidad)
            else:
                raise ErrorDax(f"{nombre} no se admite como filtro.")
            return

        if filtro[0] == "bin" and filtro[1] in ("=", "<>", ">", "<", ">=", "<=", "IN"):
            col = self._columna(filtro[2])
            if filtro[1] == "IN":
                valores = [self.evaluar(v, ctx) for v in filtro[3][1]]
                ctx.filtros[col] = lambda df, c=col, v=valores: _comparable(df[c], v[0]).isin(v)
                return
            valor = self.evaluar(filtro[3], ctx)
            op = filtro[1]
            ctx.filtros[col] = lambda df, c=col, v=valor, o=op: _comparar(_comparable(df[c], v), o, v)
            return

        raise ErrorDax(f"Filtro no soportado en CALCULATE: {_texto(filtro)}.")

    def _cubierto(self, ctx: Contexto):
        primera = ctx.base[ctx.columna_fecha].min()
        if pd.isna(primera) or ctx.inicio < primera.normalize() - pd.Timedelta(days=3):
            ctx.sin_datos = True

    def _ventana(self, ctx: Contexto):
        if ctx.inicio is not None:
            return ctx.inicio, ctx.fin
        fechas = ctx.base[ctx.columna_fecha].dropna()
        return fechas.min().normalize(), fechas.max().normalize() + pd.Timedelta(days=1)


def _comparable(serie: pd.Series, muestra):
    if isinstance(muestra, (int, float)):
        return pd.to_numeric(serie, errors="coerce")
    return serie.astype(str)


def _comparar(serie, op, valor):
    return {"=": serie == valor, "<>": serie != valor, ">": serie > valor,
            "<": serie < valor, ">=": serie >= valor, "<=": serie <= valor}[op]


def _texto(nodo) -> str:
    if nodo[0] in ("col", "ref"):
        return f"[{nodo[1]}]"
    if nodo[0] == "fn":
        return f"{nodo[1]}(…)"
    return str(nodo[1]) if len(nodo) > 1 else nodo[0]


def numero_valido(valor) -> bool:
    return valor is not None and not (isinstance(valor, float) and math.isnan(valor))


_RESALTE = re.compile(
    r"(?P<txt>\"(?:[^\"]|\"\")*\")|(?P<tabla>'(?:[^']|'')+')|(?P<ref>\[[^\]]+\])"
    r"|(?P<fn>\b[A-Z][A-Z0-9_]*(?=\s*\())|(?P<num>\b\d+(?:\.\d+)?\b)"
)


def resaltar(texto: str) -> Markup:
    """Colorea funciones, referencias, tablas y literales de una formula."""
    salida, pos = [], 0
    for m in _RESALTE.finditer(texto):
        salida.append(escape(texto[pos:m.start()]))
        salida.append(Markup(f'<span class="dax-{m.lastgroup}">') + escape(m.group()) + Markup("</span>"))
        pos = m.end()
    salida.append(escape(texto[pos:]))
    return Markup("").join(salida)
