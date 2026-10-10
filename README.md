# TaskFlow

<p>
  <a href="https://taskflow-812302804238.us-central1.run.app/"><img src="docs/demo-badge.svg" alt="Abrir la demo en vivo" height="32"></a>
  <a href="https://frontend-nine-topaz-99.vercel.app"><img src="https://portafolio-status.onrender.com/api/status/taskflow/badge.svg" alt="Estado en vivo del proyecto" height="32"></a>
  <a href="https://d4i3vsgw7xwmh.cloudfront.net"><img src="https://portafolio-status.onrender.com/api/status/taskflow/qa-badge.svg" alt="Fecha y resultado de la última prueba E2E" height="32"></a>
</p>

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white)
![HTMX](https://img.shields.io/badge/HTMX-3D72D7?style=for-the-badge&logo=htmx&logoColor=white)
![Pandas](https://img.shields.io/badge/pandas-150458?style=for-the-badge&logo=pandas&logoColor=white)
![Google Cloud Run](https://img.shields.io/badge/Google_Cloud_Run-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)

## Contenido

1. [Presentación](#1-presentación)
2. [Estructura del proyecto](#2-estructura-del-proyecto)
3. [Arquitectura](#3-arquitectura)
4. [Plataformas y su función](#4-plataformas-y-su-función)
5. [Cómo usar la plataforma](#5-cómo-usar-la-plataforma)
6. [Instalación para pruebas](#6-instalación-para-pruebas)
7. [Autor y licencia](#7-autor-y-licencia)

---

## 1. Presentación

Aplicación web de gestión de tareas personales con un módulo de análisis de
datos. Construida enteramente en Python: FastAPI en el servidor, Jinja2 con
HTMX en la interfaz, pandas para el análisis y MongoDB como única base de datos.

No hay JavaScript propio más allá del canal de eventos: la interactividad la
resuelve HTMX pidiendo fragmentos de HTML al servidor.

### En pocas palabras

- **Qué hace:** es una lista de tareas con fechas, prioridades y categorías, más
  un panel que muestra cómo vas: cuántas cumples, cuánto tardas en cerrarlas y
  cuáles están vencidas. Los números se actualizan solos, sin recargar.
- **Extra:** puedes subir un CSV, Excel o JSON y la app lo describe
  automáticamente (tipos de dato, vacíos, estadísticas) y te deja graficarlo.
- **Cómo probarlo:** entra a la [demo](https://taskflow-812302804238.us-central1.run.app/),
  crea una cuenta y agrega un par de tareas. Para correrlo en tu equipo, ve a
  [Instalación para pruebas](#6-instalación-para-pruebas).

### Demo en vivo

**Aplicación:** [abrir la demo en vivo](https://taskflow-812302804238.us-central1.run.app/)

### Funcionalidades

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

### Stack

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

---

## 2. Estructura del proyecto

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

---

## 3. Arquitectura

<p align="center">
  <img src="docs/arquitectura.svg" alt="Diagrama de arquitectura: FastAPI en Google Cloud Run con páginas HTMX, sesión JWT, analítica con pandas, análisis de archivos, eventos en vivo y barrido horario; MongoDB Atlas con GridFS" width="100%">
</p>

- Una sola app FastAPI sirve las páginas Jinja2 + HTMX y la API REST,
  protegidas por una sesión JWT en cookie.
- La **analítica** se calcula con pandas y los gráficos se generan en el
  servidor con Plotly.
- Los archivos subidos se convierten a **Parquet** y se guardan en **GridFS**;
  un barrido horario borra los que llevan 24 horas sin uso.
- Los **eventos en vivo** (Server-Sent Events) avisan al navegador cuando
  cambia una tarea, para que los indicadores se actualicen solos.

### Decisiones de diseño

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

### Seguridad

#### Contraseñas

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

#### Resto

- Sesión en cookie `httponly`: JavaScript no puede leer el token
- Inactividad deslizante de 30 minutos y expiración absoluta de 12 horas
- Pertenencia verificada en el filtro de la consulta, no en la vista
- Validación de archivos por extensión, tamaño y número de filas
- Formatos que ejecutan código al deserializar, como pickle, rechazados
- Cuota de archivos por cuenta
- Búsquedas con la entrada escapada antes de construir la expresión regular
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options` y `Referrer-Policy`

### Limitación conocida

El registro de suscriptores del canal de eventos vive en memoria del proceso.
Con un único proceso de Uvicorn funciona correctamente; con varios trabajadores,
un evento generado en uno no alcanzaría a los clientes conectados a otro. La
solución sería un intermediario como Redis, descartado para no añadir una
dependencia externa a un proyecto que debe levantarse con un solo comando.

---

## 4. Plataformas y su función

| Plataforma | Función en el proyecto |
|---|---|
| ![Google Cloud Run](https://img.shields.io/badge/Google_Cloud_Run-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white) | Corre la app FastAPI: páginas Jinja2 + HTMX, API REST y canal de eventos en vivo. |
| ![MongoDB](https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white) | MongoDB Atlas guarda usuarios, tareas y archivos (estos últimos en GridFS). Es el único servicio externo: no requiere otra cuenta ni clave de API. |
| ![qa-evidencia](https://img.shields.io/badge/qa--evidencia-2EAD33?style=for-the-badge&logo=playwright&logoColor=white) | Prueba la demo automáticamente dos veces al día y publica la evidencia. |

---

## 5. Cómo usar la plataforma

### 5.1 Crear una cuenta

1. En la página de inicio, pulsa **Crear cuenta**.
2. Completa **Nombre**, **Correo electrónico** y **Contraseña**.
3. Pulsa **Crear cuenta**. La cuenta queda lista para usar de inmediato.

### 5.2 Iniciar sesión

1. Pulsa **Ya tengo cuenta** o **Ingresar** en el menú.
2. Escribe **Correo electrónico** y **Contraseña** y pulsa **Ingresar**.
3. El menú superior muestra **Tareas**, **Analítica**, **Datos**, **API ↗** y
   **Salir**.

La sesión se cierra tras 30 minutos sin actividad y, en cualquier caso, a las 12
horas.

### 5.3 Gestionar tareas

1. En **Tareas**, escribe en **¿Qué necesitas hacer?** y, si quieres, completa:

   | Campo | Dato |
   |---|---|
   | Categoría | Texto libre para agrupar tareas |
   | Prioridad | Baja, media o alta |
   | Fecha límite | Fecha de vencimiento |
   | Descripción | Detalle de la tarea |

2. Pulsa **Agregar**: la tarea aparece en la lista sin recargar la página.
3. En cada tarea, el botón de estado la marca como completada (o la devuelve a
   pendiente) y el de eliminar la borra.
4. Para encontrar tareas, usa **Filtrar**: busca por título, elige estado
   (Pendientes, En progreso, Completadas) o categoría y pulsa **Aplicar**.
   **Limpiar** quita los filtros.

### 5.4 Ver la analítica

1. Abre **Analítica**.
2. Filtra por **Desde** / **Hasta**, **Categoría** y **Prioridad**: los gráficos
   se recalculan sin recargar.
3. El panel muestra cumplimiento, tiempo medio de cierre, tareas vencidas,
   **Creadas frente a completadas**, **Distribución por estado**, **Estado por
   prioridad** y **Categorías**.

### 5.5 Analizar un archivo

1. Abre **Datos** y pulsa **Selecciona un archivo** (CSV, Excel o JSON).
2. La app lo procesa y lo agrega a tu lista con su número de filas y columnas.
3. Ábrelo para ver la **Vista previa** y el **Perfil de columnas** (tipos, nulos,
   valores únicos y estadísticas).
4. En el **Explorador de gráficos** elige:
   - **Gráfico:** barras, líneas, área, torta, dispersión, caja o histograma.
   - **Agrupar por** y **Medida:** las columnas a cruzar.
   - **Función:** cantidad de registros, suma, promedio, máximo o mínimo.

Límites del módulo de análisis:

| Concepto | Valor |
|---|---|
| Formatos | CSV, XLSX, JSON |
| Tamaño máximo | 10 MB |
| Filas máximas | 500.000 |
| Archivos por usuario | 5 |
| Caducidad | 24 h sin uso, o al cerrar sesión |

El JSON debe ser un arreglo de objetos. Las estructuras anidadas se rechazan con
un aviso: no existe una forma única de convertirlas a tabla.

### 5.6 Usar la API

**API ↗** abre la documentación interactiva de la API REST (`/docs`), con la
misma sesión de la interfaz.

---

## 6. Instalación para pruebas

### Requisitos

- Python 3.11 o superior
- Una base MongoDB accesible

### Instalación

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

### Ejecución

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

### Datos de ejemplo

El panel de analítica necesita historia para que la serie semanal tenga forma.
Tras crear una cuenta:

```bash
cd backend
python -m app.comandos.generar_ejemplo tu@correo.com 180
```

Genera tareas repartidas en varios meses, con sesgo hacia fechas recientes y
tiempos de cierre verosímiles.

### Despliegue

La aplicación corre en Google Cloud Run, con MongoDB Atlas
como base de datos.

---

## 7. Autor y licencia

**Luis Felipe Arias Carriazo**
[GitHub](https://github.com/lariasca1994) · [LinkedIn](https://linkedin.com/in/lfac1)

Licencia: MIT.
