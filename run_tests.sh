#!/usr/bin/env bash

set -euo pipefail

VENV_DIR=".venv"
REQUIREMENTS_FILE="requirements_nl_test.txt"

POSTGRES_SERVICE="svc/postgres"
POSTGRES_LOCAL_PORT=5433
POSTGRES_REMOTE_PORT=5432
POSTGRES_DB="notifynl"
POSTGRES_USER="notify"
POSTGRES_PASSWORD="notify"

MINIO_SERVICE="svc/minio"
MINIO_LOCAL_PORT=9000
MINIO_REMOTE_PORT=9000

PORT_FORWARD_PID=""
MINIO_PORT_FORWARD_PID=""

cleanup() {
    if [[ -n "$PORT_FORWARD_PID" ]]; then
        echo "Stopping kubectl port-forward (pid $PORT_FORWARD_PID)..."
        kill "$PORT_FORWARD_PID" 2>/dev/null || true
    fi
    if [[ -n "$MINIO_PORT_FORWARD_PID" ]]; then
        echo "Stopping MinIO kubectl port-forward (pid $MINIO_PORT_FORWARD_PID)..."
        kill "$MINIO_PORT_FORWARD_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "==> Step 1: Activating virtual environment"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Virtual environment not found, creating one at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Step 2: Installing requirements from $REQUIREMENTS_FILE"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r "$REQUIREMENTS_FILE"

echo "==> Step 3: Generating app/version.py"
make generate-version-file

echo "==> Step 4: Port-forwarding Postgres from Minikube ($POSTGRES_SERVICE -> localhost:$POSTGRES_LOCAL_PORT)"
kubectl port-forward "$POSTGRES_SERVICE" "${POSTGRES_LOCAL_PORT}:${POSTGRES_REMOTE_PORT}" \
    >/tmp/port-forward.log 2>&1 &
PORT_FORWARD_PID=$!

# Give the port-forward a moment to establish, then confirm it's up
sleep 2
if ! kill -0 "$PORT_FORWARD_PID" 2>/dev/null; then
    echo "ERROR: kubectl port-forward failed to start. Log output:"
    cat /tmp/port-forward.log
    exit 1
fi
echo "Port-forward running with pid $PORT_FORWARD_PID"

echo "==> Step 5: Port-forwarding MinIO from Minikube ($MINIO_SERVICE -> localhost:$MINIO_LOCAL_PORT)"
kubectl port-forward "$MINIO_SERVICE" "${MINIO_LOCAL_PORT}:${MINIO_REMOTE_PORT}" \
    >/tmp/minio-port-forward.log 2>&1 &
MINIO_PORT_FORWARD_PID=$!

sleep 2
if ! kill -0 "$MINIO_PORT_FORWARD_PID" 2>/dev/null; then
    echo "ERROR: MinIO kubectl port-forward failed to start. Log output:"
    cat /tmp/minio-port-forward.log
    exit 1
fi
echo "MinIO port-forward running with pid $MINIO_PORT_FORWARD_PID"

echo "==> Step 6: Exporting environment variables"
export NOTIFY_ENVIRONMENT=demo
export AWS_EC2_METADATA_DISABLED=true
export SQLALCHEMY_DATABASE_URI="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_LOCAL_PORT}/${POSTGRES_DB}"
export MINIO_URL="http://localhost:${MINIO_LOCAL_PORT}"

echo "    NOTIFY_ENVIRONMENT=$NOTIFY_ENVIRONMENT"
echo "    AWS_EC2_METADATA_DISABLED=$AWS_EC2_METADATA_DISABLED"
echo "    SQLALCHEMY_DATABASE_URI=$SQLALCHEMY_DATABASE_URI"
echo "    MINIO_URL=$MINIO_URL"

echo "==> Step 7: Running pytest"
# Any arguments passed to this script are forwarded straight to pytest.

if [[ $# -eq 0 ]]; then
    pytest
else
    pytest "$@"
fi

echo "==> Done."
