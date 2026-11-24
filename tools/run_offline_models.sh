#!/bin/bash
# Run after setup, with external agent network disabled if supported.
set -euo pipefail
cd "$(dirname "$0")/.."
export OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=4096
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.cache/orbit-ollama/models}"
command -v ollama >/dev/null
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Existing daemon detected; use an isolated environment."
  exit 1
fi
log="$(mktemp)"
ollama serve >"$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; rm -f "$log"' EXIT
for i in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null; then break; fi
  sleep 1
done
# No pull, no downloads, no cloud API in the verification phase.
python tools/offline_inference_smoke.py --workflow --report "${1:-offline-inference-report.json}" --confirm 'RUN LOCAL INFERENCE'
