#!/usr/bin/env bash
set -euo pipefail

DREAM_DIR="${HOME}/dream"
LOG_DIR="${DREAM_DIR}/logs"
SERVER_LOG="${LOG_DIR}/dream_server.log"
MCP_LOG="${LOG_DIR}/dream_mcp.log"

mkdir -p "${LOG_DIR}"
cd "${DREAM_DIR}"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
  echo "Loaded environment from ${DREAM_DIR}/.env"
else
  echo "Warning: ${DREAM_DIR}/.env not found"
fi

echo "Stopping old Dream processes ..."
"${DREAM_DIR}/stop_dream.sh" || true
sleep 1

echo "Starting Dream server ..."
nohup python3 "${DREAM_DIR}/dream_server.py" >> "${SERVER_LOG}" 2>&1 &
SERVER_PID=$!

sleep 2

if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
  echo "Dream server failed to start. Check ${SERVER_LOG}"
  exit 1
fi

echo "Dream server started with PID ${SERVER_PID}"

echo "Starting Dream MCP server ..."
nohup python3 "${DREAM_DIR}/dream_mcp_server.py" >> "${MCP_LOG}" 2>&1 &
MCP_PID=$!

sleep 2

if ! kill -0 "${MCP_PID}" 2>/dev/null; then
  echo "Dream MCP server failed to start. Check ${MCP_LOG}"
  exit 1
fi

echo "Dream MCP server started with PID ${MCP_PID}"
echo
echo "Logs:"
echo "  ${SERVER_LOG}"
echo "  ${MCP_LOG}"
echo
echo "Recent server log lines:"
tail -n 10 "${SERVER_LOG}" || true
echo
echo "Recent MCP log lines:"
tail -n 10 "${MCP_LOG}" || true
