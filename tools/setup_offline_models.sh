#!/bin/bash
# Run in Codex Cloud setup phase, or a disposable local Linux environment.
# Requires an installed Ollama binary. Does not modify an existing daemon.
set -euo pipefail
command -v ollama >/dev/null || { echo "Install Ollama from https://ollama.com/download first"; exit 1; }
command -v curl >/dev/null
export OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=4096
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.cache/orbit-ollama/models}"
if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Existing Ollama daemon detected; stop it or use a dedicated environment."
  exit 1
fi
mkdir -p "$OLLAMA_MODELS"
log="$(mktemp)"
ollama serve >"$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; rm -f "$log"' EXIT
for i in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:11434/api/version
ollama pull qwen2.5-coder:1.5b
ollama pull qwen2.5:1.5b
ollama list
echo "Model files prepared at $OLLAMA_MODELS. Daemon will stop at end of setup."
