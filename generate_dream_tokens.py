#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def make_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def upsert_env_line(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Dream API/Admin tokens and write them into a .env file."
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file to update (default: .env)",
    )
    parser.add_argument(
        "--server-name",
        default="",
        help="Optional server name prefix, e.g. inspiron -> DREAM_INSPIRON_API_TOKEN",
    )
    parser.add_argument(
        "--bytes",
        type=int,
        default=32,
        help="Random bytes per token before URL-safe encoding (default: 32)",
    )
    parser.add_argument(
        "--print-export",
        action="store_true",
        help="Also print shell export commands you can eval or paste into your shell.",
    )
    args = parser.parse_args()

    api_token = make_token(args.bytes)
    admin_token = make_token(args.bytes)

    server_prefix = ""
    if args.server_name.strip():
        normalized = "".join(ch if ch.isalnum() else "_" for ch in args.server_name.upper())
        server_prefix = f"DREAM_{normalized}_"
    else:
        server_prefix = "DREAM_"

    api_key = f"{server_prefix}API_TOKEN"
    admin_key = f"{server_prefix}ADMIN_TOKEN"

    env_path = Path(args.env_file)
    existing = []
    if env_path.exists():
        existing = env_path.read_text(encoding="utf-8").splitlines()

    updated = upsert_env_line(existing, api_key, api_token)
    updated = upsert_env_line(updated, admin_key, admin_token)

    if updated and updated[-1] != "":
        text = "\n".join(updated) + "\n"
    else:
        text = "\n".join(updated)
    env_path.write_text(text, encoding="utf-8")

    print(f"Wrote tokens to {env_path}")
    print(f"{api_key}={api_token}")
    print(f"{admin_key}={admin_token}")

    if args.print_export:
        print("\nPaste these into your shell if you want them in the current session too:\n")
        print(f"export {api_key}='{api_token}'")
        print(f"export {admin_key}='{admin_token}'")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
