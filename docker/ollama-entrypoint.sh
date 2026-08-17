#!/bin/sh
# Startup wrapper for the "ollama" Docker Compose service.
#
# The base ollama/ollama image only starts the API server; it does not pull
# any model on its own. This script starts the server, waits for it to
# accept requests, pulls the configured model (so the compose healthcheck,
# which greps `ollama list` for that model, can go healthy), and then hands
# control back to the server process so the container keeps running.
set -eu

MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"

echo "[ollama-entrypoint] starting ollama server..."
ollama serve &
SERVER_PID=$!

echo "[ollama-entrypoint] waiting for ollama server to become responsive..."
until ollama list >/dev/null 2>&1; do
  sleep 1
done

echo "[ollama-entrypoint] pulling model: ${MODEL}"
ollama pull "${MODEL}"

echo "[ollama-entrypoint] model ready, handing off to server process"
wait "${SERVER_PID}"
