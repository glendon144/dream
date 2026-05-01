#!/usr/bin/env python3
"""
dream_mcp_server.py — MCP server for the Dream Capsule Server

Exposes all Dream Capsule REST endpoints as MCP tools so Claude (and other
MCP-compatible agents) can read and write capsules natively every session.

Requirements:
    pip install mcp httpx

Usage:
    # Run alongside dream_server.py (which must already be running):
    python dream_mcp_server.py

    # Or with a custom base URL:
    DREAM_BASE_URL=http://127.0.0.1:8181 python dream_mcp_server.py

    # With SSE transport (for remote/tunneled access):
    DREAM_TRANSPORT=sse DREAM_SSE_PORT=8001 python dream_mcp_server.py

Registering in Claude.ai:
    1. Expose this server publicly (see README below).
    2. Go to Claude.ai → Settings → Integrations → Add Integration.
    3. Enter the public HTTPS URL (e.g. https://xyz.ngrok.io/sse or
       https://xyz.trycloudflare.com/sse).
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel.server import NotificationOptions
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DREAM_BASE_URL = os.getenv("DREAM_BASE_URL", "http://127.0.0.1:8181").rstrip("/")
DREAM_TRANSPORT = os.getenv("DREAM_TRANSPORT", "stdio")   # "stdio" or "sse"
DREAM_SSE_HOST  = os.getenv("DREAM_SSE_HOST", "127.0.0.1")
DREAM_SSE_PORT  = int(os.getenv("DREAM_SSE_PORT", "8001"))
DREAM_AGENT     = os.getenv("DREAM_AGENT_NAME", "claude-mcp")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dream_mcp")

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=DREAM_BASE_URL, timeout=15.0)


async def _get(path: str, **params) -> dict:
    async with _client() as c:
        r = await c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict) -> dict:
    async with _client() as c:
        r = await c.post(path, json=body)
        r.raise_for_status()
        return r.json()


def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, indent=2))])


def _err(msg: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=f"ERROR: {msg}")], isError=True)

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("dream-capsule-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ── Capsule read ────────────────────────────────────────────────────
        Tool(
            name="dream_list_recent",
            description=(
                "List the most recent Dream Capsules stored on the server. "
                "Returns id, type, summary, confidence, scope, trust_level, agent, and timestamp."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max capsules to return (1–200, default 20).",
                        "default": 20,
                    }
                },
            },
        ),
        Tool(
            name="dream_get_capsule",
            description="Retrieve a single Dream Capsule by its integer ID, including full body.",
            inputSchema={
                "type": "object",
                "required": ["capsule_id"],
                "properties": {
                    "capsule_id": {
                        "type": "integer",
                        "description": "The integer ID of the capsule.",
                    }
                },
            },
        ),
        Tool(
            name="dream_search",
            description=(
                "Search Dream Capsules by keyword and/or filters. "
                "Searches summary and body text. Returns matching capsule summaries."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":        {"type": "string",  "description": "Keyword to search for in summary and body."},
                    "capsule_type": {"type": "string",  "description": "Filter by type: distill | transformation | dream | weave | recovery"},
                    "scope":        {"type": "string",  "description": "Filter by scope: private | shared | public"},
                    "source_agent": {"type": "string",  "description": "Filter by agent name."},
                    "trust_level":  {"type": "string",  "description": "Filter by trust level: local | trusted | federated | quarantined | deprecated"},
                    "limit":        {"type": "integer", "description": "Max results (1–200, default 20).", "default": 20},
                },
            },
        ),
        Tool(
            name="dream_recover_context",
            description=(
                "Semantic-style context recovery: search capsules by query, ranked by confidence then recency. "
                "Use this to recall relevant knowledge before responding to complex questions."
            ),
            inputSchema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query":       {"type": "string",  "description": "What context to recover."},
                    "limit":       {"type": "integer", "description": "Max results (1–100, default 10).", "default": 10},
                    "scope":       {"type": "string",  "description": "Optional scope filter: private | shared | public"},
                    "trust_level": {"type": "string",  "description": "Optional trust level filter."},
                },
            },
        ),
        Tool(
            name="dream_get_ancestry",
            description=(
                "Get the provenance graph for a capsule: its parent capsule and all linked capsules. "
                "Useful for tracing how a piece of knowledge was derived."
            ),
            inputSchema={
                "type": "object",
                "required": ["capsule_id"],
                "properties": {
                    "capsule_id": {"type": "integer", "description": "The capsule to inspect."}
                },
            },
        ),
        # ── Capsule write ───────────────────────────────────────────────────
        Tool(
            name="dream_store_capsule",
            description=(
                "Store a new Dream Capsule. Use this to persist important knowledge, "
                "observations, distillations, or context for future sessions. "
                f"The source_agent defaults to '{DREAM_AGENT}'."
            ),
            inputSchema={
                "type": "object",
                "required": ["capsule_type", "summary", "source_system", "key_facts"],
                "properties": {
                    "capsule_type":   {"type": "string",  "description": "distill | transformation | dream | weave | recovery"},
                    "summary":        {"type": "string",  "description": "Short description of what this capsule contains."},
                    "source_system":  {"type": "string",  "description": "Where this knowledge came from (e.g. 'claude-session', 'web-search')."},
                    "key_facts":      {"type": "array",   "items": {"type": "string"}, "description": "List of key facts to store."},
                    "themes":         {"type": "array",   "items": {"type": "string"}, "description": "Thematic tags."},
                    "entities":       {"type": "array",   "items": {"type": "string"}, "description": "Named entities mentioned."},
                    "source_references": {"type": "array","items": {"type": "string"}, "description": "URLs, doc names, or other references."},
                    "open_questions": {"type": "array",   "items": {"type": "string"}, "description": "Unresolved questions."},
                    "contradictions": {"type": "array",   "items": {"type": "string"}, "description": "Known contradictions."},
                    "recovery_hints": {"type": "array",   "items": {"type": "string"}, "description": "Hints to help retrieve this capsule later."},
                    "emotional_tone": {"type": "string",  "description": "Optional emotional tone of the content."},
                    "confidence":     {"type": "number",  "description": "Confidence score 0.0–1.0 (default 0.7).", "default": 0.7},
                    "retention":      {"type": "string",  "description": "ephemeral | normal | durable | permanent (default normal)."},
                    "scope":          {"type": "string",  "description": "private | shared | public (default private)."},
                    "trust_level":    {"type": "string",  "description": "local | trusted | federated (default local)."},
                    "source_agent":   {"type": "string",  "description": f"Agent name (default: {DREAM_AGENT})."},
                    "parent_capsule_id": {"type": "integer", "description": "Optional parent capsule ID for lineage tracking."},
                },
            },
        ),
        Tool(
            name="dream_link_capsules",
            description="Create a typed relationship link between two capsules.",
            inputSchema={
                "type": "object",
                "required": ["from_capsule_id", "to_capsule_id", "link_type"],
                "properties": {
                    "from_capsule_id": {"type": "integer", "description": "Source capsule ID."},
                    "to_capsule_id":   {"type": "integer", "description": "Target capsule ID."},
                    "link_type":       {"type": "string",  "description": "derived_from | contradicts | supports | extends | recovers | dreams_over"},
                    "weight":          {"type": "number",  "description": "Link weight 0.0–1.0 (default 1.0).", "default": 1.0},
                },
            },
        ),
        # ── Agent management ────────────────────────────────────────────────
        Tool(
            name="dream_list_agents",
            description="List all registered agents on the Dream Capsule Server.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="dream_upsert_agent",
            description="Register or update an agent record on the Dream Capsule Server.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name":       {"type": "string", "description": "Agent name (unique identifier)."},
                    "kind":       {"type": "string", "description": "Agent kind/type (e.g. 'llm', 'human', 'script')."},
                    "trust_tier": {"type": "string", "description": "local | trusted | federated | admin | quarantined (default local)."},
                    "status":     {"type": "string", "description": "active | restricted | revoked (default active)."},
                    "public_key": {"type": "string", "description": "Optional PEM public key for signature verification."},
                },
            },
        ),
        # ── Server health ───────────────────────────────────────────────────
        Tool(
            name="dream_server_status",
            description="Check Dream Capsule Server health and get discovery info.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        # ── dream_list_recent ──────────────────────────────────────────────
        if name == "dream_list_recent":
            limit = arguments.get("limit", 20)
            data = await _get("/list_recent_capsules", limit=limit)
            return _ok(data)

        # ── dream_get_capsule ──────────────────────────────────────────────
        elif name == "dream_get_capsule":
            cid = arguments["capsule_id"]
            data = await _get(f"/get_capsule/{cid}")
            return _ok(data)

        # ── dream_search ───────────────────────────────────────────────────
        elif name == "dream_search":
            body = {
                "query":        arguments.get("query"),
                "capsule_type": arguments.get("capsule_type"),
                "scope":        arguments.get("scope"),
                "source_agent": arguments.get("source_agent"),
                "trust_level":  arguments.get("trust_level"),
                "limit":        arguments.get("limit", 20),
            }
            data = await _post("/search_capsules", body)
            return _ok(data)

        # ── dream_recover_context ──────────────────────────────────────────
        elif name == "dream_recover_context":
            body = {
                "query":       arguments["query"],
                "limit":       arguments.get("limit", 10),
                "scope":       arguments.get("scope"),
                "trust_level": arguments.get("trust_level"),
            }
            data = await _post("/recover_context", body)
            return _ok(data)

        # ── dream_get_ancestry ─────────────────────────────────────────────
        elif name == "dream_get_ancestry":
            cid = arguments["capsule_id"]
            data = await _get(f"/ancestry/{cid}")
            return _ok(data)

        # ── dream_store_capsule ────────────────────────────────────────────
        elif name == "dream_store_capsule":
            body_fields = {
                "source_system":     arguments["source_system"],
                "source_references": arguments.get("source_references", []),
                "key_facts":         arguments.get("key_facts", []),
                "themes":            arguments.get("themes", []),
                "entities":          arguments.get("entities", []),
                "relationships":     [],
                "open_questions":    arguments.get("open_questions", []),
                "contradictions":    arguments.get("contradictions", []),
                "recovery_hints":    arguments.get("recovery_hints", []),
                "emotional_tone":    arguments.get("emotional_tone"),
                "stylistic_profile": None,
                "domain_metadata":   {},
            }
            payload = {
                "capsule_type":   arguments["capsule_type"],
                "summary":        arguments["summary"],
                "body":           body_fields,
                "confidence":     arguments.get("confidence", 0.7),
                "retention":      arguments.get("retention", "normal"),
                "scope":          arguments.get("scope", "private"),
                "trust_level":    arguments.get("trust_level", "local"),
                "review_status":  "unreviewed",
                "source_agent":   arguments.get("source_agent", DREAM_AGENT),
            }
            if arguments.get("parent_capsule_id"):
                payload["parent_capsule_id"] = arguments["parent_capsule_id"]

            data = await _post("/store_capsule", payload)
            return _ok(data)

        # ── dream_link_capsules ────────────────────────────────────────────
        elif name == "dream_link_capsules":
            payload = {
                "from_capsule_id": arguments["from_capsule_id"],
                "to_capsule_id":   arguments["to_capsule_id"],
                "link_type":       arguments["link_type"],
                "weight":          arguments.get("weight", 1.0),
            }
            data = await _post("/link_capsules", payload)
            return _ok(data)

        # ── dream_list_agents ──────────────────────────────────────────────
        elif name == "dream_list_agents":
            data = await _get("/list_agents")
            return _ok(data)

        # ── dream_upsert_agent ─────────────────────────────────────────────
        elif name == "dream_upsert_agent":
            payload = {
                "name":       arguments["name"],
                "kind":       arguments.get("kind"),
                "trust_tier": arguments.get("trust_tier", "local"),
                "status":     arguments.get("status", "active"),
                "public_key": arguments.get("public_key"),
            }
            data = await _post("/upsert_agent", payload)
            return _ok(data)

        # ── dream_server_status ────────────────────────────────────────────
        elif name == "dream_server_status":
            data = await _get("/")
            return _ok(data)

        else:
            return _err(f"Unknown tool: {name}")

    except httpx.ConnectError:
        return _err(
            f"Could not connect to Dream Capsule Server at {DREAM_BASE_URL}. "
            "Is dream_server.py running?"
        )
    except httpx.HTTPStatusError as e:
        return _err(f"HTTP {e.response.status_code}: {e.response.text}")
    except Exception as e:
        log.exception("Unexpected error in tool %s", name)
        return _err(str(e))


# ---------------------------------------------------------------------------
# Transport — stdio (default) or SSE
# ---------------------------------------------------------------------------

async def run_stdio():
    from mcp.server.stdio import stdio_server
    log.info("Starting Dream MCP server (stdio transport)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dream-capsule-server",
                server_version="0.3.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def run_sse():
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route
    import uvicorn

    sse = SseServerTransport("/messages/")
    init_options = InitializationOptions(
        server_name="dream-capsule-server",
        server_version="0.3.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], init_options)
        return Response()

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    log.info("Starting Dream MCP server (SSE transport) on %s:%d", DREAM_SSE_HOST, DREAM_SSE_PORT)
    log.info("Dream REST base URL: %s", DREAM_BASE_URL)
    log.info("Register this URL in Claude.ai: https://<your-tunnel>/sse")
    config = uvicorn.Config(starlette_app, host=DREAM_SSE_HOST, port=DREAM_SSE_PORT)
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()


if __name__ == "__main__":
    if DREAM_TRANSPORT == "sse":
        asyncio.run(run_sse())
    else:
        asyncio.run(run_stdio())


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------
# QUICK START
# ------------------------------------
# 1. Install deps:
#       pip install mcp httpx uvicorn starlette
#
# 2. Start the Dream Capsule REST server (in one terminal):
#       ./start_dream_server   (or: uvicorn dream_server:app --reload)
#
# 3. Start this MCP server in SSE mode (in another terminal):
#       DREAM_TRANSPORT=sse python dream_mcp_server.py
#
# 4. Expose it publicly — pick one tunnel option:
#
#    A) Cloudflare Tunnel (best for double-NAT, free, no account needed for temp URLs):
#          brew install cloudflare/cloudflare/cloudflared   (Mac)
#          cloudflared tunnel --url http://127.0.0.1:8001
#       → Gives you: https://random-words.trycloudflare.com
#       → Your MCP URL: https://random-words.trycloudflare.com/sse
#
#    B) ngrok (free tier, requires account):
#          ngrok http 8001
#       → Your MCP URL: https://abc123.ngrok.io/sse
#
#    C) Tailscale Funnel (if you use Tailscale):
#          tailscale funnel 8001
#       → Your MCP URL: https://<device>.tailnet-name.ts.net/sse
#
# 5. Register in Claude.ai:
#       Settings → Integrations → Add custom integration
#       Name: Dream Capsule Server
#       URL:  https://<your-tunnel>/sse
#
# ENVIRONMENT VARIABLES
# ------------------------------------
# DREAM_BASE_URL    URL of the REST server (default: http://127.0.0.1:8181)
# DREAM_TRANSPORT   "stdio" or "sse" (default: stdio)
# DREAM_SSE_HOST    Bind host for SSE transport (default: 127.0.0.1). Use 0.0.0.0 only when you intentionally need remote reachability.
# DREAM_SSE_PORT    Port for SSE transport (default: 8001)
# DREAM_AGENT_NAME  Default agent name for stored capsules (default: claude-mcp)
#
# MAKING IT PERMANENT
# ------------------------------------
# For a tunnel that survives reboots, set up a Cloudflare Named Tunnel:
#   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/
# Or run ngrok as a background service with a reserved domain (paid plan).
