# TaskFlow

Aplicación web de gestión de tareas personales con un módulo de análisis de
datos. Construida enteramente en Python: FastAPI en el servidor, Jinja2 con
HTMX en la interfaz, pandas para el análisis y MongoDB como única base de datos.

No hay JavaScript propio más allá del canal de eventos: la interactividad la
resuelve HTMX pidiendo fragmentos de HTML al servidor.

## Funcionalidades

**Cuentas**
- Registro e ingreso con contraseñas hasheadas
- Sesión con inactividad deslizante de 30 minutos y duración máxima de 12 horas
- Cada usuario ve únicamente lo suyo: la pertenencia se verifica en la consulta

**Tareas**
- Crear, completar, filtrar, buscar y eliminar
- Categorías, prioridades y fechas límite

**Analítica de tareas**
- Cumplimiento, tiempo medio de cierre y tareas vencidas
- Serie semanal de creadas frente a completadas
- Distribución por estado, prioridad y categoría
- Filtros por rango de fechas, categoría y prioridad que recalculan sin recargar

**Análisis de archivos**
- Carga de CSV, Excel y JSON
- Perfilado automático: tipos, nulos, valores únicos y estadísticas descriptivas
- Explorador de gráficos con siete tipos y cinco funciones de agregación
- Vista previa de las primeras filas

**Tiempo real**
- Los indicadores se actualizan solos cuando cambia algo, sin recargar

## Stack

| Capa | Tecnología |
|---|---|
| Servidor y API | FastAPI, Uvicorn |
| Interfaz | Jinja2, HTMX, Tailwind CSS |
| Tiempo real | Server-Sent Events |
| Base de datos | MongoDB, con GridFS para archivos |
| Análisis | pandas |
| Formato interno | Parquet |
| Gráficos | Plotly, renderizado en el servidor |
| Sesiones | JWT en cookie httponly |
| Contraseñas | bcrypt con pimiento |

## Conexiones externas

| Servicio | Uso | Obligatorio |
|---|---|---|
| MongoDB | Persistencia y almacenamiento de archivos | Sí |

No requiere ningún otro servicio, cuenta ni clave de API.

## Estructura

```
backend/
├── requirements.txt
└── app/
    ├── main.py              Punto de entrada, middleware y barrido periódico
    ├── config.py            Carga del .env y límites
    ├── database.py          Conexión, índices y GridFS
    ├── security.py          Hasheo de contraseñas y sesiones
    ├── dependencias.py      Identificación del usuario
    ├── esquemas.py          Modelos de entrada y salida
    ├── repositorio.py       Acceso a datos de tareas
    ├── analitica.py         Cálculos sobre tareas con pandas
    ├── datos.py             Carga, perfilado y almacenamiento de archivos
    ├── graficos.py          Construcción de gráficos
    ├── eventos.py           Canal de eventos en vivo
    ├── comandos/            Generador de datos de ejemplo
    ├── routers/
    │   ├── api.py           API REST
    │   ├── web.py           Páginas de tareas y analítica
    │   ├── datasets.py      Módulo de análisis de archivos
    │   └── eventos.py       Canal SSE
    ├── templates/           Plantillas Jinja2
    └── static/              Hoja de estilos
```

## Requisitos

- Python 3.11 o superior
- Una base MongoDB accesible

## Instalación

```bash
git clone https://github.com/lariasca1994/taskflow.git
cd taskflow

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
source .venv/bin/activate         # Linux o macOS

pip install -r backend/requirements.txt
cp .env.example .env
```

Si PowerShell bloquea la activación del entorno:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

### Configuración

El `.env` necesita la cadena de conexión a MongoDB y dos secretos **distintos
entre sí**. Genera cada uno por separado:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- `JWT_SECRET` firma las sesiones
- `PASSWORD_PEPPER` se mezcla con las contraseñas antes de hashearlas

`PASSWORD_PEPPER` no debe cambiarse una vez existan cuentas: invalidaría todas
las contraseñas.

Los límites del módulo de análisis también se configuran ahí. La plantilla
indica el nombre y el propósito de cada variable.

## Ejecución

```bash
cd backend
uvicorn app.main:app --reload
```

El `cd backend` es necesario: las rutas de plantillas y archivos estáticos se
resuelven desde ahí.

| Recurso | Dirección |
|---|---|
| Aplicación | `http://127.0.0.1:8000` |
| Documentación de la API | `http://127.0.0.1:8000/docs` |
| Estado del servicio | `http://127.0.0.1:8000/api/health` |

## Datos de ejemplo

El panel de analítica necesita historia para que la serie semanal tenga forma.
Tras crear una cuenta:

```bash
cd backend
python -m app.comandos.generar_ejemplo tu@correo.com 180
```

Genera tareas repartidas en varios meses, con sesgo hacia fechas recientes y
tiempos de cierre verosímiles.

## Límites del módulo de análisis

| Concepto | Valor |
|---|---|
| Formatos | CSV, XLSX, JSON |
| Tamaño máximo | 10 MB |
| Filas máximas | 500.000 |
| Archivos por usuario | 5 |
| Caducidad | 24 h sin uso, o al cerrar sesión |

El JSON debe ser un arreglo de objetos. Las estructuras anidadas se rechazan con
un aviso: no existe una forma única de convertirlas a tabla.

## Decisiones de diseño

**Parquet como formato interno.** El archivo que sube el usuario se lee una sola
vez y se guarda convertido. Parquet es columnar y comprimido, así que cargar dos
columnas cuesta milisegundos frente a releer y reinterpretar el original en cada
cambio de filtro. Es lo que hace viable un explorador interactivo.

**Los archivos viven en GridFS**, no en disco. La aplicación no depende del
sistema de archivos local, así que funciona igual en un servicio con
almacenamiento efímero.

**La agregación se hace en pandas y no en la base.** El volumen por usuario es
reducido, y trabajar sobre un DataFrame permite operaciones de series de tiempo
—remuestreo semanal, medias— que en Mongo exigirían tuberías bastante más largas
y difíciles de leer.

**Los gráficos se renderizan en el servidor** y viajan como HTML. El navegador
solo los dibuja.

**Server-Sent Events y no WebSockets.** El flujo va en un solo sentido y SSE
reconecta por su cuenta. Además, `EventSource` no admite cabeceras propias, de
modo que la autenticación viaja necesariamente en la cookie de sesión: es la
razón por la que la sesión se guarda así y no en almacenamiento del navegador.

**Doble caducidad de los archivos.** Se borran al cerrar sesión, pero casi nadie
pulsa "Salir": un barrido horario elimina los que lleven 24 horas sin uso, para
que nada quede huérfano.

## Seguridad

### Contraseñas

Se **hashean**, no se cifran. El cifrado es reversible: en una filtración
bastaría la clave para recuperarlas en claro. El hash es de una sola vía.

Tres capas:

| Capa | Qué aporta |
|---|---|
| Pimiento (HMAC-SHA256) | Un secreto que vive en la configuración, no en la base. Sin él, un volcado robado no sirve ni para probar contraseñas comunes |
| bcrypt con sal única | Dos usuarios con la misma contraseña producen hashes distintos |
| Coste 12 | Cada verificación cuesta unos 250 ms: irrelevante para el usuario, prohibitivo para la fuerza bruta |

El pimiento resuelve además el límite de 72 bytes de bcrypt, que trunca en
silencio las contraseñas más largas: el HMAC produce siempre una entrada de
longitud fija.

Las cuentas creadas con un esquema anterior se actualizan solas en el siguiente
ingreso, sin obligar a nadie a restablecer su contraseña.

### Resto

- Sesión en cookie `httponly`: JavaScript no puede leer el token
- Inactividad deslizante de 30 minutos y expiración absoluta de 12 horas
- Pertenencia verificada en el filtro de la consulta, no en la vista
- Validación de archivos por extensión, tamaño y número de filas
- Formatos que ejecutan código al deserializar, como pickle, rechazados
- Cuota de archivos por cuenta
- Búsquedas con la entrada escapada antes de construir la expresión regular
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`

## Limitación conocida

El registro de suscriptores del canal de eventos vive en memoria del proceso.
Con un único proceso de Uvicorn funciona correctamente; con varios trabajadores,
un evento generado en uno no alcanzaría a los clientes conectados a otro. La
solución sería un intermediario como Redis, descartado para no añadir una
dependencia externa a un proyecto que debe levantarse con un solo comando.

## Licencia

MIT