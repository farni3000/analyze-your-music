#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

MODE="--schedule"

for arg in "$@"; do
  case "$arg" in
    --once) MODE="" ;;
    -h|--help)
      echo "Usage: $0 [--once]"
      echo "  ohne Option: Scheduler-Loop (Freitags-Report)"
      echo "  --once:      einen Report jetzt erzeugen"
      exit 0
      ;;
    *) echo "Unbekannte Option: $arg" >&2; exit 1 ;;
  esac
done

if [ ! -d .venv ]; then
  echo "Erstelle virtuelle Umgebung …"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "Hinweis: .env fehlt – cp .env.example .env und API-Keys eintragen." >&2
fi

if [ -n "$MODE" ]; then
  exec .venv/bin/python -m src.main --schedule
else
  exec .venv/bin/python -m src.main
fi
