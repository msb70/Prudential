#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLED_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
PYTHON_BIN="${CODEX_PYTHON:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$BUNDLED_PYTHON" ]]; then
    PYTHON_BIN="$BUNDLED_PYTHON"
  else
    PYTHON_BIN="python3"
  fi
fi

export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m dashboard.server \
  --host "${HOST:-127.0.0.1}" \
  --port "${PORT:-8765}" \
  --excel "$ROOT_DIR/Data/listadopolizasexcel_20260420_174106.xlsx"
