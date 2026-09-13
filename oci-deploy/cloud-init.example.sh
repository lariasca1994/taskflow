#!/bin/bash
# ==========================================================================
# TaskFlow — arranque automatico de la VM Always Free (OCI)
# --------------------------------------------------------------------------
# Este script corre UNA sola vez, la primera vez que enciende la instancia
# (es el "user-data" de cloud-init). Deja la app corriendo sola como un
# servicio systemd que se reinicia solo si falla o si la VM se reinicia.
#
# COPIA este archivo como cloud-init.sh (ya esta en .gitignore) y reemplaza
# los cuatro valores marcados con "_AQUI" por los reales antes de lanzar la
# instancia. Nunca subas cloud-init.sh a git ni lo pegues en el chat.
# ==========================================================================
set -e

apt-get update
apt-get install -y python3-venv python3-pip git

id -u taskflow &>/dev/null || useradd -m -s /bin/bash taskflow

sudo -u taskflow git clone https://github.com/lariasca1994/taskflow.git /home/taskflow/app

# --------------------------------------------------------------------- .env
# Un solo proceso de Uvicorn (ver mas abajo en el .service): el canal de
# eventos en vivo (SSE) guarda sus suscriptores en memoria del proceso, asi
# que con mas de un worker los eventos no llegarian a todos los clientes.
cat > /home/taskflow/app/.env <<'EOF'
MONGO_URI=mongodb+srv://taskflow_app:PASSWORD_AQUI@taskflow-cluster.qhejhen.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=taskflow

JWT_SECRET=JWT_SECRET_AQUI
PASSWORD_PEPPER=PASSWORD_PEPPER_AQUI

SESION_INACTIVIDAD_MIN=30
SESION_MAXIMA_HORAS=12

ARCHIVO_MAX_MB=10
ARCHIVO_MAX_FILAS=500000
ARCHIVOS_POR_USUARIO=5
ARCHIVO_HORAS_VIDA=24
EOF
chown taskflow:taskflow /home/taskflow/app/.env
chmod 600 /home/taskflow/app/.env

# --------------------------------------------------------------- dependencias
sudo -u taskflow bash -c "
    cd /home/taskflow/app &&
    python3 -m venv .venv &&
    .venv/bin/pip install --upgrade pip &&
    .venv/bin/pip install -r backend/requirements.txt
"

# ------------------------------------------------------------ cuenta admin
# Mismo patron que gestor-casos-qa/PRPagos: correo fijo del administrador,
# contrasena elegida aqui una sola vez (minimo 10 caracteres).
sudo -u taskflow bash -c "
    cd /home/taskflow/app/backend &&
    /home/taskflow/app/.venv/bin/python -m app.comandos.crear_admin \
        ariascluisf@proton.me \"Luis Felipe Arias\" ADMIN_PASSWORD_AQUI
"

# --------------------------------------------------------------- systemd
cat > /etc/systemd/system/taskflow.service <<'EOF'
[Unit]
Description=TaskFlow (FastAPI + Uvicorn, un solo proceso por el canal SSE)
After=network.target

[Service]
Type=simple
User=taskflow
WorkingDirectory=/home/taskflow/app/backend
ExecStart=/home/taskflow/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now taskflow.service
