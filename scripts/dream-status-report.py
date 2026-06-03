#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DREAM_DIR = Path(os.getenv("DREAM_DIR", str(SCRIPT_DIR.parent))).resolve()
DEFAULT_DREAM_ENV_FILE = DREAM_DIR / ".env"
if os.getenv("DREAM_ENV_FILE"):
    DREAM_ENV_FILE = Path(os.environ["DREAM_ENV_FILE"]).expanduser()
elif DEFAULT_DREAM_ENV_FILE.exists():
    DREAM_ENV_FILE = DEFAULT_DREAM_ENV_FILE
else:
    fallback_env = Path.home() / "dream" / ".env"
    DREAM_ENV_FILE = fallback_env if fallback_env.exists() else DEFAULT_DREAM_ENV_FILE

if not os.getenv("DREAM_API_TOKEN") and DREAM_ENV_FILE.exists():
    for line in DREAM_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

DREAM_REST_URL = os.getenv("DREAM_REST_URL", "http://127.0.0.1:8181").rstrip("/")
DREAM_API_TOKEN = os.getenv("DREAM_API_TOKEN")

headers = {"Accept": "application/json"}
if DREAM_API_TOKEN:
    headers["Authorization"] = f"Bearer {DREAM_API_TOKEN}"

req = urllib.request.Request(f"{DREAM_REST_URL}/server_status", headers=headers)
with urllib.request.urlopen(req, timeout=8) as resp:
    data = json.loads(resp.read().decode("utf-8", "replace"))

summary = {
    "service": data.get("service"),
    "app_version": data.get("app_version"),
    "protocol_version": data.get("protocol_version"),
    "bundle_version": data.get("bundle_version"),
    "db_path": data.get("db_path"),
    "schema_path": data.get("schema_path"),
    "capsule_count": data.get("capsule_count"),
    "agent_count": data.get("agent_count"),
    "latest_capsule_created_at": data.get("latest_capsule_created_at"),
    "server_status": data.get("server_status"),
    "recent": data.get("recent"),
    "docs": data.get("docs"),
    "openapi": data.get("openapi"),
}

json.dump(summary, sys.stdout, indent=2)
sys.stdout.write("\n")
