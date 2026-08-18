#!/bin/sh
# Startup wrapper for the "ollama" Docker Compose service.
#
# The base ollama/ollama image only starts the API server; it does not pull
# any model on its own. This script starts the server, waits for it to
# accept requests, pulls the configured models (so the compose healthcheck,
# which greps `ollama list` for both of them, can go healthy), and then hands
# control back to the server process so the container keeps running.
#
# Two models are pulled: the general-purpose OLLAMA_MODEL (application-
# content generation) and the smaller OLLAMA_MODEL_CV_PARSING (CV analysis
# only - see backend/app/core/config.py and the ce-debug investigation,
# 2026-08-18, for why CV parsing needs a faster, separately-tuned model on
# CPU-only Ollama). Without pulling both here, a fresh deployment's first CV
# upload would fail with "model not found" even though the app itself never
# calls `ollama pull`.
set -eu

MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"
CV_PARSING_MODEL="${OLLAMA_MODEL_CV_PARSING:-qwen2.5:3b-instruct}"

echo "[ollama-entrypoint] starting ollama server..."
ollama serve &
SERVER_PID=$!

echo "[ollama-entrypoint] waiting for ollama server to become responsive..."
until ollama list >/dev/null 2>&1; do
  sleep 1
done

echo "[ollama-entrypoint] pulling model: ${MODEL}"
ollama pull "${MODEL}"

if [ "${CV_PARSING_MODEL}" != "${MODEL}" ]; then
  echo "[ollama-entrypoint] pulling CV-parsing model: ${CV_PARSING_MODEL}"
  ollama pull "${CV_PARSING_MODEL}"
else
  echo "[ollama-entrypoint] CV-parsing model matches the general model, already pulled"
fi

echo "[ollama-entrypoint] models ready, handing off to server process"
wait "${SERVER_PID}"
