Updated Dream service control scripts

Files:
- stop_dream_updated.sh
- restart_dream_updated.sh

What changed:
- restart_dream_updated.sh now uses ~/.venvs/dream/bin/python explicitly
- Dream REST starts with uvicorn via the venv python
- Dream MCP starts with the same venv python
- stop_dream_updated.sh continues to stop uvicorn-based REST plus MCP

Suggested install:
    cp stop_dream_updated.sh ~/src/dream/stop_dream.sh
    cp restart_dream_updated.sh ~/src/dream/restart_dream.sh
    chmod +x ~/src/dream/stop_dream.sh ~/src/dream/restart_dream.sh

Then commit:
    cd ~/src/dream
    git add stop_dream.sh restart_dream.sh
    git commit -m "Use venv python in Dream service scripts"
    git push
