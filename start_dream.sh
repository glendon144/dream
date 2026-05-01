#!/bin/bash
# Start Dream Capsule REST + MCP servers
# REST stays private on 8181; MCP SSE stays on 8001 for Claude/tunnels.
cd ~/dream

PYTHON_BIN="${DREAM_PYTHON_BIN:-$HOME/.venvs/dream/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

port_listening() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnH "sport = :${port}" | grep -q .
        return
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
        return
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -an 2>/dev/null | grep -Eq "[.:]${port} .*LISTEN"
        return
    fi
    return 1
}

# REST server
if ! port_listening 8181; then
    nohup "$PYTHON_BIN" -m uvicorn dream_server:app --host 127.0.0.1 --port 8181 > ~/dream/rest.log 2>&1 &
    echo $! > ~/dream/rest.pid
    echo 'REST server started'
else
    echo 'REST server already running'
fi

# MCP SSE server
if ! port_listening 8001; then
    DREAM_TRANSPORT=sse DREAM_SSE_HOST=127.0.0.1 DREAM_SSE_PORT=8001 DREAM_BASE_URL=http://127.0.0.1:8181 DREAM_AGENT_NAME=claude-mcp \
        nohup "$PYTHON_BIN" ~/dream/dream_mcp_server.py >> ~/dream/mcp.log 2>&1 &
    echo $! > ~/dream/mcp.pid
    echo 'MCP server started'
else
    echo 'MCP server already running'
fi
