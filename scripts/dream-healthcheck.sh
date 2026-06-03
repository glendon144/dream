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

python3 - "$DREAM_REST_URL" "$DREAM_MCP_SSE_URL" "$DREAM_API_TOKEN" <<'PY'
import json
import sys
import urllib.error
import urllib.request

rest_url, mcp_url, token = sys.argv[1:4]
headers = {"Accept": "application/json"}
if token:
    headers["Authorization"] = f"Bearer {token}"

failures = []


def check_rest():
    req = urllib.request.Request(f"{rest_url.rstrip('/')}/server_status", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    required = [
        "ok",
        "service",
        "app_version",
        "protocol_version",
        "bundle_version",
        "db_path",
        "schema_path",
        "capsule_count",
        "agent_count",
        "latest_capsule_created_at",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise RuntimeError(f"missing status keys: {', '.join(missing)}")
    print(
        f"PASS REST server_status service={data['service']} app={data['app_version']} capsules={data['capsule_count']}"
    )


def check_mcp():
    req = urllib.request.Request(mcp_url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        content_type = resp.headers.get("Content-Type", "")
        status = getattr(resp, "status", None) or resp.getcode()
    if status != 200:
        raise RuntimeError(f"unexpected MCP status {status}")
    if "text/event-stream" not in content_type:
        raise RuntimeError(f"unexpected MCP content-type {content_type!r}")
    print(f"PASS MCP sse status={status} content_type={content_type}")


for name, fn in (("REST", check_rest), ("MCP", check_mcp)):
    try:
        fn()
    except Exception as exc:
        failures.append(f"{name}: {exc}")
        print(f"FAIL {name} {exc}")

if failures:
    sys.exit(1)

print("OK Dream healthcheck passed")
PY
