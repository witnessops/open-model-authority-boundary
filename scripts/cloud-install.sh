#!/usr/bin/env bash
# Idempotent environment bootstrap for the Open Model Authority Boundary.
# Creates a virtualenv and installs the package (with dev/test extras).
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

# The venv module needs ensurepip, which ships in the distro's python3-venv
# package. It is present in the prebuilt environment snapshot; this guard keeps
# the install self-healing if the script is ever run on a bare base image.
if ! "${PYTHON}" -c "import ensurepip" >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
    echo "ensurepip missing; installing python3-venv via apt..."
    sudo apt-get update -y
    sudo apt-get install -y "$(${PYTHON} -c 'import sys;print(f"python{sys.version_info.major}.{sys.version_info.minor}-venv")')" python3-venv
  fi
fi

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "${PYTHON}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
. "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip
pip install -e ".[dev]"

echo "Install complete. Python: $(python --version)"
