Dream service control scripts

Files:
- stop_dream.sh
- restart_dream.sh

Suggested installation:
    cp stop_dream.sh ~/dream/
    cp restart_dream.sh ~/dream/
    chmod +x ~/dream/stop_dream.sh ~/dream/restart_dream.sh

Usage:
    cd ~/dream
    ./stop_dream.sh
    ./restart_dream.sh

What restart_dream.sh does:
- changes into ~/dream
- loads ~/dream/.env if present
- stops old dream_server.py and dream_mcp_server.py processes
- starts fresh copies in the background with nohup
- writes logs under ~/dream/logs/

Notes:
- This restart script manages the Dream REST server and Dream MCP server in ~/dream.
- It does not restart the Flask client in ~/src/dream-client.
- If you want, I can also give you matching scripts for the Flask client.
