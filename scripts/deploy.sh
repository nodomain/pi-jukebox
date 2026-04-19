#!/usr/bin/env bash
# Deploy web dashboard to the Pi and restart the service.
# Run from the project root on your dev machine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values."
    exit 1
fi
source "${PROJECT_DIR}/.env"

HOST="${JUKEBOX_USER}@${JUKEBOX_HOST}"
REMOTE_DIR="/opt/jukebox"
TMP_DIR="/tmp/jukebox-deploy"

echo "==> Uploading web/ to ${HOST}:${TMP_DIR}"
ssh "${HOST}" "rm -rf ${TMP_DIR} && mkdir -p ${TMP_DIR}/templates"
scp -q "${PROJECT_DIR}/web/app.py"               "${HOST}:${TMP_DIR}/app.py"
scp -q "${PROJECT_DIR}/web/cava.conf"             "${HOST}:${TMP_DIR}/cava.conf"
scp -q "${PROJECT_DIR}/web/templates/index.html"  "${HOST}:${TMP_DIR}/templates/index.html"

echo "==> Deploying to ${REMOTE_DIR} and restarting service"
ssh "${HOST}" "\
    sudo rm -rf ${REMOTE_DIR}/__pycache__ && \
    sudo cp ${TMP_DIR}/app.py              ${REMOTE_DIR}/app.py && \
    sudo cp ${TMP_DIR}/cava.conf           ${REMOTE_DIR}/cava.conf && \
    sudo cp ${TMP_DIR}/templates/index.html ${REMOTE_DIR}/templates/index.html && \
    sudo systemctl restart jukebox-web && \
    rm -rf ${TMP_DIR}"

echo "==> Verifying service"
ssh "${HOST}" "sudo systemctl is-active jukebox-web"

echo "==> Done — http://${JUKEBOX_HOST}:5000"
