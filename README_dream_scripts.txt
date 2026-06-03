Dream service control and Phase 1 ops scripts

Files:
- stop_dream.sh
- restart_dream.sh
- scripts/dream-healthcheck.sh
- scripts/dream-smoke-test.sh
- scripts/dream-status-report.py

Suggested installation / usage:
    cd ~/src/dream
    chmod +x stop_dream.sh restart_dream.sh \
        scripts/dream-healthcheck.sh scripts/dream-smoke-test.sh scripts/dream-status-report.py

Service control:
    ./stop_dream.sh
    ./restart_dream.sh

Phase 1 ops checks:
    ./scripts/dream-healthcheck.sh
    ./scripts/dream-smoke-test.sh
    ./scripts/dream-status-report.py

Environment overrides:
- DREAM_REST_URL (default: http://127.0.0.1:8181)
- DREAM_MCP_SSE_URL (default: http://127.0.0.1:8001/sse)
- DREAM_API_TOKEN (optional bearer token for protected REST endpoints)
- DREAM_SMOKE_QUERY (default: Dream)

What restart_dream.sh does:
- changes into ~/dream
- loads ~/dream/.env if present
- stops old dream_server.py and dream_mcp_server.py processes
- starts fresh copies in the background with nohup
- writes logs under ~/dream/logs/

Notes:
- This restart script manages the Dream REST server and Dream MCP server in ~/dream.
- It does not restart the Flask client in ~/src/dream-client.
- The new Phase 1 scripts are read-only checks intended for local appliance health and smoke testing.
