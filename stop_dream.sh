#!/usr/bin/env bash
set -u

DREAM_DIR="${HOME}/dream"

echo "Stopping Dream services from ${DREAM_DIR} ..."

patterns=(
  "${DREAM_DIR}/dream_server.py"
  "${DREAM_DIR}/dream_mcp_server.py"
  "python3 dream_server.py"
  "python dream_server.py"
  "uvicorn dream_server:app"
  "python3 dream_mcp_server.py"
  "python dream_mcp_server.py"
)

found=0

for pattern in "${patterns[@]}"; do
  if pgrep -af "$pattern" >/dev/null 2>&1; then
    found=1
    echo "Found processes matching: $pattern"
    pgrep -af "$pattern" || true
    pkill -TERM -f "$pattern" || true
  fi
done

if [ "$found" -eq 0 ]; then
  echo "No matching Dream processes found."
  exit 0
fi

sleep 2

for pattern in "${patterns[@]}"; do
  if pgrep -af "$pattern" >/dev/null 2>&1; then
    echo "Still running after TERM; sending KILL for: $pattern"
    pgrep -af "$pattern" || true
    pkill -KILL -f "$pattern" || true
  fi
done

echo "Dream services stopped."
