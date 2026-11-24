#!/bin/bash
# Disposable dedicated Linux Docker host. No production database or credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -ne 2 ] || [ "$2" != 'RUN LOCAL 24H SOAK' ]; then
  echo "Usage: bash tools/run_24h_soak.sh /absolute/new/report-dir 'RUN LOCAL 24H SOAK'" >&2; exit 2
fi
case "$1" in /*) ;; *) echo "Absolute new directory required" >&2; exit 2;; esac
umask 077
mkdir -- "$1"
out="$(cd "$1" && pwd)"
command -v docker >/dev/null
command -v timeout >/dev/null
name="orbit-soak-$$"
volume="$name-models"
cleanup(){ docker rm -f "$name" "$name-download" >/dev/null 2>&1 || true; docker volume rm "$volume" >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker pull ollama/ollama:latest
docker pull python:3.12-slim
ollama_image="$(docker image inspect ollama/ollama:latest --format '{{index .RepoDigests 0}}')"
python_image="$(docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}')"
printf '%s\n%s\n' "$ollama_image" "$python_image" > "$out/images.txt"
docker volume create "$volume" >/dev/null
docker run -d --name "$name-download" -e OLLAMA_NO_CLOUD=1 -v "$volume:/root/.ollama" "$ollama_image" >/dev/null
for i in $(seq 1 60); do if docker exec "$name-download" ollama list >/dev/null; then break; fi; sleep 1; done
docker exec "$name-download" ollama pull qwen2.5-coder:3b
docker exec "$name-download" ollama pull qwen2.5:3b
docker exec "$name-download" ollama list > "$out/models.txt"
docker rm -f "$name-download" >/dev/null
docker run -d --name "$name" --network none --memory 6g --memory-swap 6g --cpus 2 -e OLLAMA_NO_CLOUD=1 -e OLLAMA_NUM_PARALLEL=1 -e OLLAMA_MAX_LOADED_MODELS=1 -e OLLAMA_CONTEXT_LENGTH=8192 -v "$volume:/root/.ollama" "$ollama_image" >/dev/null
test "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$name")" = none
for i in $(seq 1 60); do if docker exec "$name" ollama list >/dev/null; then break; fi; sleep 1; done
# Record sampled Ollama memory and cgroup events throughout, not just final stats.
status=0
timeout --kill-after=30s 25h docker run --rm --name "$name-client" --user "$(id -u):$(id -g)" --network "container:$name" --mount "type=bind,src=$PWD,dst=/repo,readonly" --mount "type=bind,src=$out,dst=/report" -e PYTHONDONTWRITEBYTECODE=1 "$python_image" python /repo/tools/offline_stress.py --profile soak24h --report /report/soak.json --confirm 'RUN LOCAL 24H SOAK' > "$out/client.log" 2>&1 &
client=$!
while kill -0 "$client" 2>/dev/null; do
  if ! python tools/soak_container_sample.py "$name" "$out/container-samples.jsonl"; then status=2; docker rm -f "$name-client" >/dev/null 2>&1 || true; break; fi
  sleep 30
done
wait "$client" || status=2
docker rm -f "$name-client" >/dev/null 2>&1 || true
python tools/soak_container_sample.py "$name" "$out/container-samples.jsonl" || status=2
python tools/soak_acceptance.py "$out" || status=2
exit "$status"
