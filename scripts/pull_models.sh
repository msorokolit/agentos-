#!/usr/bin/env bash
# Pull default models into the Ollama container.
# Models are tunable via env: CHAT_MODEL, EMBED_MODEL.
#
# Defaults are intentionally small/CPU-friendly; switch to larger models
# in `.env` when running with GPU.

set -euo pipefail

CHAT_MODEL="${CHAT_MODEL:-qwen2.5:7b-instruct}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

echo "Pulling chat model:  $CHAT_MODEL"
docker compose exec -T ollama ollama pull "$CHAT_MODEL"

echo "Pulling embed model: $EMBED_MODEL"
docker compose exec -T ollama ollama pull "$EMBED_MODEL"

echo "Models present:"
docker compose exec -T ollama ollama list
