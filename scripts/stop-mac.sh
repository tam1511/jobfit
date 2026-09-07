#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="jobfit"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
echo "JobFit stopped."
