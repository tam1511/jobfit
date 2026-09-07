#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_NAME="jobfit:latest"
CONTAINER_NAME="jobfit"
VOLUME_NAME="jobfit-data"
PORT="${JOBFIT_PORT:-8000}"

docker build -t "$IMAGE_NAME" .
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$CONTAINER_NAME" \
  -p "${PORT}:8000" \
  -v "${VOLUME_NAME}:/data" \
  "$IMAGE_NAME"

echo "JobFit is running on http://localhost:${PORT}"
