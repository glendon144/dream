#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DREAM_DIR="${DREAM_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
DEFAULT_DREAM_ENV_FILE="${DREAM_DIR}/.env"
if [ -n "${DREAM_ENV_FILE:-}" ]; then
    RESOLVED_DREAM_ENV_FILE="${DREAM_ENV_FILE}"
elif [ -f "${DEFAULT_DREAM_ENV_FILE}" ]; then
    RESOLVED_DREAM_ENV_FILE="${DEFAULT_DREAM_ENV_FILE}"
elif [ -f "${HOME}/dream/.env" ]; then
    RESOLVED_DREAM_ENV_FILE="${HOME}/dream/.env"
else
    RESOLVED_DREAM_ENV_FILE="${DEFAULT_DREAM_ENV_FILE}"
fi
if [ -z "${DREAM_API_TOKEN:-}" ] && [ -f "${RESOLVED_DREAM_ENV_FILE}" ]; then
    set -a
    # shellcheck disable=SC1090
    . "${RESOLVED_DREAM_ENV_FILE}"
    set +a
fi

DREAM_REST_URL="${DREAM_REST_URL:-http://127.0.0.1:8181}"
DREAM_MCP_SSE_URL="${DREAM_MCP_SSE_URL:-http://127.0.0.1:8001/sse}"
DREAM_API_TOKEN="${DREAM_API_TOKEN:-}"
SMOKE_QUERY="${DREAM_SMOKE_QUERY:-Dream}"

python3 - "$DREAM_REST_URL" "$DREAM_MCP_SSE_URL" "$DREAM_API_TOKEN" "$SMOKE_QUERY" <<'PY'
import json
import sys
import urllib.request

rest_url, mcp_url, token, smoke_query = sys.argv[1:5]
base_headers = {"Accept": "application/json"}
if token:
    base_headers["Authorization"] = f"Bearer {token}"

results = []


def fetch_json(path, *, method="GET", payload=None, extra_headers=None):
    headers = dict(base_headers)
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{rest_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def check(name, fn):
    try:
        detail = fn()
        results.append((name, True, detail))
        print(f"PASS {name} {detail}")
    except Exception as exc:
        results.append((name, False, str(exc)))
        print(f"FAIL {name} {exc}")


def status_check():
    data = fetch_json("/server_status")
    assert data.get("ok") is True
    return f"capsules={data.get('capsule_count')} latest={data.get('latest_capsule_created_at')}"


def recent_check():
    data = fetch_json("/list_recent_capsules?limit=2")
    assert data.get("ok") is True
    assert isinstance(data.get("results"), list)
    return f"recent_count={len(data['results'])}"


def search_check():
    data = fetch_json("/search_capsules", method="POST", payload={"query": smoke_query, "limit": 2})
    assert data.get("ok") is True
    assert isinstance(data.get("results"), list)
    return f"query={smoke_query!r} results={len(data['results'])}"


def recover_check():
    data = fetch_json("/recover_context", method="POST", payload={"query": smoke_query, "limit": 2})
    assert data.get("ok") is True
    assert isinstance(data.get("recovered"), list)
    return f"query={smoke_query!r} recovered={len(data['recovered'])}"


def openapi_check():
    data = fetch_json("/openapi.json")
    assert "paths" in data
    return f"paths={len(data['paths'])}"


def mcp_check():
    req = urllib.request.Request(mcp_url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        content_type = resp.headers.get("Content-Type", "")
        status = getattr(resp, "status", None) or resp.getcode()
    if status != 200:
        raise RuntimeError(f"unexpected status {status}")
    if "text/event-stream" not in content_type:
        raise RuntimeError(f"unexpected content-type {content_type!r}")
    return f"status={status} content_type={content_type}"


for name, fn in (
    ("server_status", status_check),
    ("list_recent_capsules", recent_check),
    ("search_capsules", search_check),
    ("recover_context", recover_check),
    ("openapi", openapi_check),
    ("mcp_sse", mcp_check),
):
    check(name, fn)

failed = [name for name, ok, _ in results if not ok]
if failed:
    print(f"SMOKE TEST FAILED: {', '.join(failed)}")
    sys.exit(1)

print("OK Dream smoke test passed")
PY
