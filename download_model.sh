#!/usr/bin/env bash
# Download the model weight file for this submission (Qwen2.5-3B-Instruct, GGUF Q4_K_M).
#
# Rules:
#   - Must be idempotent (safe to run multiple times).
#   - Must download without any credentials (public URL only).
#   - The output path must match `_runtime.model_path` in metadata.json.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$HERE/model"
MODEL_FILE="$MODEL_DIR/qwen2.5-3b-instruct-q4_k_m.gguf"

# ── Public model weight URL (official Qwen GGUF release on Hugging Face) ────
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
# ───────────────────────────────────────────────────────────────────────────

mkdir -p "$MODEL_DIR"

if [[ -f "$MODEL_FILE" ]]; then
  echo "model already present at $MODEL_FILE — skipping download"
  exit 0
fi

echo "downloading $MODEL_URL → $MODEL_FILE (~1.9 GB)…"

if command -v curl > /dev/null 2>&1; then
  curl -L --fail --progress-bar -o "$MODEL_FILE.partial" "$MODEL_URL"
elif command -v wget > /dev/null 2>&1; then
  wget --show-progress -O "$MODEL_FILE.partial" "$MODEL_URL"
else
  echo "error: neither curl nor wget found" >&2
  exit 1
fi

# Verify the download actually completed — a dropped connection or proxy
# truncation can end curl/wget "successfully" with a partial file, which
# llama.cpp then fails on much later with an opaque "tensor data not within
# file bounds" error instead of a clear download error here. Compare against
# the server's own Content-Length before trusting the file.
EXPECTED_SIZE="$(curl -sI -L "$MODEL_URL" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-length"{s=$2} END{print s}')"
ACTUAL_SIZE="$(stat -f%z "$MODEL_FILE.partial" 2>/dev/null || stat -c%s "$MODEL_FILE.partial")"
if [[ -n "$EXPECTED_SIZE" && "$ACTUAL_SIZE" != "$EXPECTED_SIZE" ]]; then
  echo "error: downloaded file size ($ACTUAL_SIZE bytes) does not match Content-Length ($EXPECTED_SIZE bytes) — download was truncated" >&2
  rm -f "$MODEL_FILE.partial"
  exit 1
fi

mv "$MODEL_FILE.partial" "$MODEL_FILE"
echo "done: $MODEL_FILE ($ACTUAL_SIZE bytes, verified against Content-Length)"
