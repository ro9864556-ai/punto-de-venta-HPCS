#!/usr/bin/env bash
# Inicia el punto de venta (Linux / macOS)
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Instalando por primera vez..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python app.py
