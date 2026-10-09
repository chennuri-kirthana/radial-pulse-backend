#!/bin/sh
# Lambda start script for the ZIP package (Python 3.12 runtime + AWS Lambda Web Adapter layer).
#
# The function handler is this file (`run.sh`). With AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap the
# adapter runs it, waits until AWS_LWA_READINESS_CHECK_PATH (/health) answers, then forwards each
# API Gateway request to uvicorn as plain HTTP on 127.0.0.1:AWS_LWA_PORT.
#
# Same server and flags as the Dockerfile CMD, but listening on localhost only: the adapter is the
# only client, so it is also the only proxy whose X-Forwarded-* headers are trusted.
# No settings or secrets here: they come from the Lambda environment.
set -eu

TASK_ROOT="${LAMBDA_TASK_ROOT:-/var/task}"
cd "$TASK_ROOT"
# Packaged dependencies first, so they win over the copies inside the Lambda runtime (e.g. boto3).
export PYTHONPATH="${TASK_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

exec python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "${AWS_LWA_PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips=127.0.0.1 \
  --no-server-header
