#!/bin/bash
# SessionStart (Claude Code en la nube): prepara .venv con las dependencias de desarrollo
# y el CLI de graphify, para que funcionen ruff, pytest y la skill /graphify.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# El proyecto fija Python 3.12; si no está, se usa el python3 disponible.
PYTHON_BIN="$(command -v python3.12 || command -v python3)"
VENV=.venv

# Solo reinstala si cambió este script o algún archivo de dependencias desde la última
# instalación correcta. El hash vive dentro de .venv (ignorado por git).
hashes="$VENV/.session-start.sha256"
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  [ -x "$VENV/bin/python" ] || "$PYTHON_BIN" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r requirements-dev.txt -r requirements-tools.txt
  sha256sum .claude/hooks/session-start.sh requirements.txt requirements-dev.txt \
    requirements-tools.txt > "$hashes"
fi

# En cada sesión: el .venv primero en el PATH (ruff, pytest, graphify).
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$PWD/$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
