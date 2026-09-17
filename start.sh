#!/usr/bin/env bash
# Lancement combiné : API FastAPI (webhooks) + bot Telegram (polling) dans un seul service.
set -uo pipefail

PORT="${PORT:-8000}"

echo "[start] API FastAPI sur :$PORT"
uvicorn main:app --host 0.0.0.0 --port "$PORT" &
API_PID=$!

echo "[start] Worker Telegram (polling)"
python telegram_bot.py &
TG_PID=$!

term() {
  echo "[start] arrêt des process..."
  kill "$API_PID" "$TG_PID" 2>/dev/null || true
  wait "$API_PID" "$TG_PID" 2>/dev/null || true
  exit 0
}
trap term SIGTERM SIGINT

# Si l'un des deux meurt, on arrête tout → Railway redémarre le conteneur.
wait -n "$API_PID" "$TG_PID"
echo "[start] un process s'est arrêté → arrêt du conteneur"
term
