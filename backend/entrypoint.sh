#!/bin/sh
# Container entrypoint.
#
# The exam endpoint speaks the OpenAI protocol only, while Claude Code speaks
# Anthropic. We start a local LiteLLM proxy that translates Anthropic
# /v1/messages  ->  OpenAI /v1/chat/completions, then point Claude Code at it.
set -e

: "${EXAM_BASE_URL:?EXAM_BASE_URL is required (OpenAI-compatible base url)}"
: "${EXAM_API_KEY:?EXAM_API_KEY is required}"
: "${EXAM_MODEL:=linext-5.3-luna}"
: "${LITELLM_MASTER_KEY:=sk-workbench}"
export LITELLM_MASTER_KEY
# Use the bundled model price map; skip the remote fetch (faster, offline-safe).
export LITELLM_LOCAL_MODEL_COST_MAP=True

cat > /tmp/litellm.yaml <<EOF
model_list:
  - model_name: ${EXAM_MODEL}
    litellm_params:
      model: openai/${EXAM_MODEL}
      api_base: ${EXAM_BASE_URL}
      api_key: os.environ/EXAM_API_KEY
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
litellm_settings:
  drop_params: true
EOF

echo "[entrypoint] starting LiteLLM proxy (model=${EXAM_MODEL})..."
litellm --config /tmp/litellm.yaml --port 4000 --host 127.0.0.1 &
LITELLM_PID=$!

# Wait for the proxy to accept requests (bounded).
i=0
while [ "$i" -lt 60 ]; do
  if python3 - <<'PY'
import sys, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:4000/health/liveliness", timeout=2)
except Exception:
    sys.exit(1)
PY
  then
    echo "[entrypoint] LiteLLM ready"
    break
  fi
  i=$((i + 1))
  sleep 1
done

# Point the Agent CLI at the local proxy.
export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export ANTHROPIC_AUTH_TOKEN="${LITELLM_MASTER_KEY}"
unset ANTHROPIC_API_KEY || true
unset ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL || true
export ANTHROPIC_MODEL="${EXAM_MODEL}"

# Shut the proxy down if the web server exits.
trap 'kill "$LITELLM_PID" 2>/dev/null || true' EXIT INT TERM

echo "[entrypoint] starting workbench on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
