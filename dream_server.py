#!/usr/bin/env python3

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, validator

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dream_capsules.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
PROTOCOL_VERSION = "dccp-1976-0.1"
BUNDLE_VERSION = "dream-bundle-0.1"

ALLOWED_CAPSULE_TYPES = {"distill", "transformation", "dream", "weave", "recovery"}
ALLOWED_RETENTION = {"ephemeral", "normal", "durable", "permanent"}
ALLOWED_SCOPE = {"private", "shared", "public"}
ALLOWED_TRUST = {"local", "trusted", "federated", "quarantined", "deprecated"}
ALLOWED_REVIEW = {"unreviewed", "reviewed", "human-approved"}
ALLOWED_AGENT_TIERS = {"local", "trusted", "federated", "admin", "quarantined"}
ALLOWED_AGENT_STATUS = {"active", "restricted", "revoked"}

app = FastAPI(title="Dream Capsule Server", version="0.2.0")


def model_dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_choice(name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def fail_http(status_code: int, detail: str) -> None:
    raise HTTPException(status_code=status_code, detail=detail)


def get_signing_secret(key_id: Optional[str]) -> Optional[str]:
    if key_id:
        env_name = f"DREAM_SIGNING_KEY_{key_id.upper()}"
        value = os.getenv(env_name)
        if value:
            return value
    return os.getenv("DREAM_SHARED_SECRET")


def sign_value(value: Any, key_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    secret = get_signing_secret(key_id)
    if not secret:
        return None, None
    payload = stable_json(value).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return digest, "hmac-sha256"


def verify_signature(value: Any, signature: Optional[str], key_id: Optional[str]) -> bool:
    if not signature:
        return False
    expected, _ = sign_value(value, key_id)
    if not expected:
        return False
    return hmac.compare_digest(expected, signature)


def is_loopback_request(request: Request) -> bool:
    if request.client is None:
        return True
    return request.client.host in {"127.0.0.1", "::1", "localhost"}


class DreamCapsuleBody(BaseModel):
    source_system: str
    source_references: List[str] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    recovery_hints: List[str] = Field(default_factory=list)
    emotional_tone: Optional[str] = None
    stylistic_profile: Optional[str] = None
    domain_metadata: Dict[str, Any] = Field(default_factory=dict)


class CapsuleIn(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    capsule_type: str
    summary: str
    body: DreamCapsuleBody
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    retention: str = "normal"
    scope: str = "private"
    trust_level: str = "local"
    review_status: str = "unreviewed"
    source_agent: str
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    parent_capsule_id: Optional[int] = None
    supersedes_capsule_id: Optional[int] = None
    lineage: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    signing_key_id: Optional[str] = None

    @validator("protocol_version")
    def validate_protocol_version(cls, value: str) -> str:
        if not value:
            raise ValueError("protocol_version is required")
        return value

    @validator("capsule_type")
    def validate_capsule_type(cls, value: str) -> str:
        return check_choice("capsule_type", value, ALLOWED_CAPSULE_TYPES)

    @validator("retention")
    def validate_retention(cls, value: str) -> str:
        return check_choice("retention", value, ALLOWED_RETENTION)

    @validator("scope")
    def validate_scope(cls, value: str) -> str:
        return check_choice("scope", value, ALLOWED_SCOPE)

    @validator("trust_level")
    def validate_trust_level(cls, value: str) -> str:
        return check_choice("trust_level", value, ALLOWED_TRUST)

    @validator("review_status")
    def validate_review_status(cls, value: str) -> str:
        return check_choice("review_status", value, ALLOWED_REVIEW)


class SearchIn(BaseModel):
    query: Optional[str] = None
    capsule_type: Optional[str] = None
    scope: Optional[str] = None
    source_agent: Optional[str] = None
    trust_level: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=200)


class LinkIn(BaseModel):
    from_capsule_id: int
    to_capsule_id: int
    link_type: str
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


class RecoverIn(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    scope: Optional[str] = None
    trust_level: Optional[str] = None


class AgentUpsertIn(BaseModel):
    name: str
    kind: Optional[str] = None
    public_key: Optional[str] = None
    trust_tier: str = "local"
    status: str = "active"

    @validator("trust_tier")
    def validate_trust_tier(cls, value: str) -> str:
        return check_choice("trust_tier", value, ALLOWED_AGENT_TIERS)

    @validator("status")
    def validate_status(cls, value: str) -> str:
        return check_choice("status", value, ALLOWED_AGENT_STATUS)


class CapsuleBundleIn(BaseModel):
    bundle: Dict[str, Any]
    source_agent: Optional[str] = None


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema)
        apply_migrations(conn)
        conn.commit()


def apply_migrations(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "agents", "trust_tier", "TEXT DEFAULT 'local'")
    ensure_column(conn, "agents", "status", "TEXT DEFAULT 'active'")
    ensure_column(conn, "capsules", "protocol_version", "TEXT DEFAULT 'dccp-1976-0.1'")
    ensure_column(conn, "capsules", "trust_level", "TEXT DEFAULT 'local'")
    ensure_column(conn, "capsules", "review_status", "TEXT DEFAULT 'unreviewed'")
    ensure_column(conn, "capsules", "signature", "TEXT")
    ensure_column(conn, "capsules", "signature_algorithm", "TEXT")
    ensure_column(conn, "capsules", "signer_key_id", "TEXT")
    ensure_column(conn, "capsules", "signed_at", "TEXT")
    ensure_column(conn, "capsules", "origin_capsule_uuid", "TEXT")
    ensure_column(conn, "capsules", "import_bundle_hash", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_capsules_scope_trust ON capsules(scope, trust_level)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_capsules_origin_uuid ON capsules(origin_capsule_uuid)"
    )


def ensure_column(
    conn: sqlite3.Connection, table_name: str, column_name: str, definition: str
) -> None:
    columns = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_access(
    conn: sqlite3.Connection,
    agent_id: Optional[int],
    action: str,
    capsule_id: Optional[int],
    remote_addr: Optional[str],
    request_payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO access_log (agent_id, action, capsule_id, remote_addr, request_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (agent_id, action, capsule_id, remote_addr, stable_json(request_payload)),
    )


def get_agent(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()


def get_or_create_agent(
    conn: sqlite3.Connection,
    name: str,
    *,
    kind: Optional[str] = None,
    public_key: Optional[str] = None,
    trust_tier: str = "local",
    status: str = "active",
) -> sqlite3.Row:
    row = get_agent(conn, name)
    if row:
        return row
    conn.execute(
        """
        INSERT INTO agents (name, kind, public_key, trust_tier, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, kind, public_key, trust_tier, status),
    )
    row = get_agent(conn, name)
    assert row is not None
    return row


def get_or_create_source(
    conn: sqlite3.Connection,
    source_type: Optional[str],
    source_ref: Optional[str],
    body_hash: str,
) -> Optional[int]:
    if not source_type and not source_ref:
        return None
    row = conn.execute(
        "SELECT id FROM sources WHERE source_type = ? AND source_ref IS ?",
        (source_type or "unknown", source_ref),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO sources (source_type, source_ref, hash) VALUES (?, ?, ?)",
        (source_type or "unknown", source_ref, body_hash),
    )
    return cur.lastrowid


def enforce_capsule_write_policy(
    *,
    request: Request,
    scope: str,
    agent_row: sqlite3.Row,
    signature_valid: bool,
) -> None:
    if agent_row["status"] == "revoked":
        fail_http(403, "Agent is revoked and may not write capsules")
    if scope == "private":
        return
    if agent_row["trust_tier"] in {"admin", "trusted"}:
        return
    if is_loopback_request(request) and agent_row["trust_tier"] in {"local", "federated"}:
        return
    if signature_valid and agent_row["trust_tier"] == "federated":
        return
    fail_http(
        403,
        "Shared or public capsule writes require a trusted agent, loopback-local write, or a verified federated signature",
    )


def build_capsule_record(payload: CapsuleIn) -> dict[str, Any]:
    body_dict = model_dump(payload.body)
    body_text = stable_json(body_dict)
    return {
        "protocol_version": payload.protocol_version,
        "capsule_type": payload.capsule_type,
        "summary": payload.summary,
        "body": body_dict,
        "confidence": payload.confidence,
        "retention": payload.retention,
        "scope": payload.scope,
        "trust_level": payload.trust_level,
        "review_status": payload.review_status,
        "lineage": payload.lineage or {},
        "metadata": payload.metadata or {},
        "content_hash": stable_hash(body_text),
    }


def sign_capsule_record(
    record: dict[str, Any], signing_key_id: Optional[str]
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    signature, algorithm = sign_value(record, signing_key_id)
    if not signature:
        return None, None, None
    return signature, algorithm, signing_key_id or "default"


def serialize_capsule_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field in ("body", "lineage_json", "metadata_json"):
        if data.get(field):
            try:
                data[field] = json.loads(data[field])
            except json.JSONDecodeError:
                pass
    return data


def build_bundle(
    capsule_row: sqlite3.Row, links: list[sqlite3.Row], sign_bundle: bool
) -> dict[str, Any]:
    capsule = serialize_capsule_row(capsule_row)
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "exported_at": now_utc(),
        "capsule": capsule,
        "links": [dict(link) for link in links],
    }
    if sign_bundle:
        payload = dict(bundle)
        signature, algorithm = sign_value(payload, capsule.get("signer_key_id"))
        if signature and algorithm:
            bundle["signature"] = signature
            bundle["signature_algorithm"] = algorithm
    return bundle


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.post("/upsert_agent")
async def upsert_agent(payload: AgentUpsertIn):
    with db() as conn:
        existing = get_agent(conn, payload.name)
        if existing:
            conn.execute(
                """
                UPDATE agents
                SET kind = ?, public_key = ?, trust_tier = ?, status = ?
                WHERE name = ?
                """,
                (
                    payload.kind,
                    payload.public_key,
                    payload.trust_tier,
                    payload.status,
                    payload.name,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO agents (name, kind, public_key, trust_tier, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.kind,
                    payload.public_key,
                    payload.trust_tier,
                    payload.status,
                ),
            )
        row = get_agent(conn, payload.name)
        assert row is not None
        return {"ok": True, "agent": dict(row)}


@app.get("/list_agents")
async def list_agents():
    with db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM agents ORDER BY name")]
    return {"ok": True, "results": rows}


@app.post("/store_capsule")
async def store_capsule(payload: CapsuleIn, request: Request):
    record = build_capsule_record(payload)
    capsule_uuid = str(uuid.uuid4())
    signature, signature_algorithm, signer_key_id = sign_capsule_record(
        record, payload.signing_key_id
    )

    with db() as conn:
        agent_row = get_or_create_agent(conn, payload.source_agent)
        enforce_capsule_write_policy(
            request=request,
            scope=payload.scope,
            agent_row=agent_row,
            signature_valid=signature is not None,
        )
        source_id = get_or_create_source(
            conn, payload.source_type, payload.source_ref, record["content_hash"]
        )

        cur = conn.execute(
            """
            INSERT INTO capsules (
                capsule_uuid, protocol_version, capsule_type, summary, body,
                confidence, retention, scope, trust_level, review_status,
                source_agent_id, source_id, parent_capsule_id, supersedes_capsule_id,
                lineage_json, metadata_json, content_hash, signature,
                signature_algorithm, signer_key_id, signed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capsule_uuid,
                payload.protocol_version,
                payload.capsule_type,
                payload.summary,
                stable_json(record["body"]),
                payload.confidence,
                payload.retention,
                payload.scope,
                payload.trust_level,
                payload.review_status,
                agent_row["id"],
                source_id,
                payload.parent_capsule_id,
                payload.supersedes_capsule_id,
                stable_json(payload.lineage or {}),
                stable_json(payload.metadata or {}),
                record["content_hash"],
                signature,
                signature_algorithm,
                signer_key_id,
                now_utc() if signature else None,
            ),
        )
        capsule_id = cur.lastrowid

        if payload.parent_capsule_id:
            conn.execute(
                """
                INSERT INTO capsule_links (from_capsule_id, to_capsule_id, link_type)
                VALUES (?, ?, ?)
                """,
                (capsule_id, payload.parent_capsule_id, "derived_from"),
            )

        log_access(
            conn,
            agent_row["id"],
            "store",
            capsule_id,
            request.client.host if request.client else None,
            model_dump(payload),
        )

    return {"ok": True, "capsule_id": capsule_id, "capsule_uuid": capsule_uuid}


@app.post("/import_capsule_bundle")
async def import_capsule_bundle(payload: CapsuleBundleIn, request: Request):
    bundle = payload.bundle
    if bundle.get("bundle_version") != BUNDLE_VERSION:
        fail_http(400, "Unsupported bundle_version")

    capsule = bundle.get("capsule")
    if not isinstance(capsule, dict):
        fail_http(400, "Bundle is missing a capsule object")

    body = capsule.get("body")
    if not isinstance(body, dict):
        fail_http(400, "Bundle capsule body must be an object")

    try:
        body_model = DreamCapsuleBody(**body)
        capsule_model = CapsuleIn(
            protocol_version=capsule.get("protocol_version", PROTOCOL_VERSION),
            capsule_type=capsule["capsule_type"],
            summary=capsule["summary"],
            body=body_model,
            confidence=capsule.get("confidence", 0.5),
            retention=capsule.get("retention", "normal"),
            scope=capsule.get("scope", "private"),
            trust_level=capsule.get("trust_level", "federated"),
            review_status=capsule.get("review_status", "unreviewed"),
            source_agent=payload.source_agent or capsule.get("agent_name") or "imported-agent",
            source_type="bundle",
            source_ref=capsule.get("capsule_uuid"),
            lineage=capsule.get("lineage_json") or {},
            metadata=capsule.get("metadata_json") or {},
        )
    except Exception as exc:
        fail_http(400, f"Invalid bundle capsule payload: {exc}")
        raise

    record = build_capsule_record(capsule_model)
    if record["content_hash"] != capsule.get("content_hash"):
        fail_http(400, "Bundle content_hash does not match the capsule body")

    signer_key_id = capsule.get("signer_key_id")
    verification_payload = {
        "bundle_version": bundle["bundle_version"],
        "exported_at": bundle.get("exported_at"),
        "capsule": capsule,
        "links": bundle.get("links", []),
    }
    signature_valid = verify_signature(
        verification_payload, bundle.get("signature"), signer_key_id
    )
    bundle_hash = stable_hash(stable_json(verification_payload))

    with db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM capsules
            WHERE origin_capsule_uuid = ? OR import_bundle_hash = ?
            """,
            (capsule.get("capsule_uuid"), bundle_hash),
        ).fetchone()
        if existing:
            return {"ok": True, "duplicate": True, "capsule_id": existing["id"]}

        agent_row = get_or_create_agent(
            conn,
            capsule_model.source_agent,
            trust_tier="federated" if signature_valid else "quarantined",
            status="active",
        )
        enforce_capsule_write_policy(
            request=request,
            scope=capsule_model.scope,
            agent_row=agent_row,
            signature_valid=signature_valid,
        )
        source_id = get_or_create_source(
            conn, capsule_model.source_type, capsule_model.source_ref, record["content_hash"]
        )
        cur = conn.execute(
            """
            INSERT INTO capsules (
                capsule_uuid, protocol_version, capsule_type, summary, body,
                confidence, retention, scope, trust_level, review_status,
                source_agent_id, source_id, lineage_json, metadata_json,
                content_hash, signature, signature_algorithm, signer_key_id,
                signed_at, origin_capsule_uuid, import_bundle_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                capsule_model.protocol_version,
                capsule_model.capsule_type,
                capsule_model.summary,
                stable_json(record["body"]),
                capsule_model.confidence,
                capsule_model.retention,
                capsule_model.scope,
                capsule_model.trust_level,
                "reviewed" if signature_valid else "unreviewed",
                agent_row["id"],
                source_id,
                stable_json(capsule_model.lineage or {}),
                stable_json(capsule_model.metadata or {}),
                record["content_hash"],
                capsule.get("signature"),
                capsule.get("signature_algorithm"),
                signer_key_id,
                capsule.get("signed_at"),
                capsule.get("capsule_uuid"),
                bundle_hash,
            ),
        )
        capsule_id = cur.lastrowid

        for link in bundle.get("links", []):
            conn.execute(
                """
                INSERT INTO capsule_links (from_capsule_id, to_capsule_id, link_type, weight, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    capsule_id,
                    capsule_id,
                    link.get("link_type", "imported_link"),
                    link.get("weight", 1.0),
                    stable_json({"imported": True, "original": link}),
                ),
            )

        log_access(
            conn,
            agent_row["id"],
            "import_bundle",
            capsule_id,
            request.client.host if request.client else None,
            {"bundle_version": bundle["bundle_version"], "signature_valid": signature_valid},
        )

    return {"ok": True, "capsule_id": capsule_id, "signature_valid": signature_valid}


@app.get("/export_capsule/{capsule_id}")
async def export_capsule(capsule_id: int, sign_bundle: bool = True):
    with db() as conn:
        capsule = conn.execute(
            """
            SELECT c.*, a.name AS agent_name
            FROM capsules c
            LEFT JOIN agents a ON a.id = c.source_agent_id
            WHERE c.id = ?
            """,
            (capsule_id,),
        ).fetchone()
        if not capsule:
            fail_http(404, "Capsule not found")

        links = conn.execute(
            """
            SELECT id, from_capsule_id, to_capsule_id, link_type, weight, metadata_json, created_at
            FROM capsule_links
            WHERE from_capsule_id = ? OR to_capsule_id = ?
            ORDER BY id
            """,
            (capsule_id, capsule_id),
        ).fetchall()
        return {"ok": True, "bundle": build_bundle(capsule, links, sign_bundle)}


@app.get("/get_capsule/{capsule_id}")
async def get_capsule(capsule_id: int, request: Request):
    with db() as conn:
        row = conn.execute(
            """
            SELECT c.*, a.name AS agent_name
            FROM capsules c
            LEFT JOIN agents a ON a.id = c.source_agent_id
            WHERE c.id = ?
            """,
            (capsule_id,),
        ).fetchone()
        if not row:
            fail_http(404, "Capsule not found")
        log_access(
            conn,
            row["source_agent_id"],
            "get",
            capsule_id,
            request.client.host if request.client else None,
            {"capsule_id": capsule_id},
        )
        return serialize_capsule_row(row)


@app.post("/search_capsules")
async def search_capsules(payload: SearchIn, request: Request):
    sql = """
        SELECT c.id, c.capsule_uuid, c.protocol_version, c.capsule_type, c.summary,
               c.confidence, c.scope, c.trust_level, c.review_status, c.created_at,
               a.name AS agent_name
        FROM capsules c
        LEFT JOIN agents a ON a.id = c.source_agent_id
        WHERE 1=1
    """
    params: List[Any] = []
    if payload.query:
        sql += " AND (c.summary LIKE ? OR c.body LIKE ?)"
        q = f"%{payload.query}%"
        params.extend([q, q])
    if payload.capsule_type:
        sql += " AND c.capsule_type = ?"
        params.append(payload.capsule_type)
    if payload.scope:
        sql += " AND c.scope = ?"
        params.append(payload.scope)
    if payload.source_agent:
        sql += " AND a.name = ?"
        params.append(payload.source_agent)
    if payload.trust_level:
        sql += " AND c.trust_level = ?"
        params.append(payload.trust_level)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(payload.limit)

    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        log_access(
            conn,
            None,
            "search",
            None,
            request.client.host if request.client else None,
            model_dump(payload),
        )
    return {"ok": True, "results": rows}


@app.post("/link_capsules")
async def link_capsules(payload: LinkIn, request: Request):
    with db() as conn:
        conn.execute(
            """
            INSERT INTO capsule_links (from_capsule_id, to_capsule_id, link_type, weight, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.from_capsule_id,
                payload.to_capsule_id,
                payload.link_type,
                payload.weight,
                stable_json(payload.metadata or {}),
            ),
        )
        log_access(
            conn,
            None,
            "link",
            payload.from_capsule_id,
            request.client.host if request.client else None,
            model_dump(payload),
        )
    return {"ok": True}


@app.post("/recover_context")
async def recover_context(payload: RecoverIn, request: Request):
    sql = """
        SELECT id, capsule_uuid, capsule_type, summary, confidence, scope, trust_level, created_at
        FROM capsules
        WHERE (summary LIKE ? OR body LIKE ?)
    """
    params: List[Any] = [f"%{payload.query}%", f"%{payload.query}%"]
    if payload.scope:
        sql += " AND scope = ?"
        params.append(payload.scope)
    if payload.trust_level:
        sql += " AND trust_level = ?"
        params.append(payload.trust_level)
    sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
    params.append(payload.limit)

    with db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        log_access(
            conn,
            None,
            "recover",
            None,
            request.client.host if request.client else None,
            model_dump(payload),
        )
    return {"ok": True, "recovered": rows}


@app.get("/list_recent_capsules")
async def list_recent_capsules(limit: int = 20):
    limit = max(1, min(limit, 200))
    with db() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT c.id, c.capsule_uuid, c.protocol_version, c.capsule_type, c.summary,
                       c.confidence, c.scope, c.trust_level, c.review_status,
                       c.created_at, a.name AS agent_name
                FROM capsules c
                LEFT JOIN agents a ON a.id = c.source_agent_id
                ORDER BY c.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    return {"ok": True, "results": rows}


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "Dream Capsule Server",
        "protocol_version": PROTOCOL_VERSION,
        "bundle_version": BUNDLE_VERSION,
        "docs": "/docs",
        "recent": "/list_recent_capsules",
        "agents": "/list_agents",
    }


@app.get("/ancestry/{capsule_id}")
async def ancestry(capsule_id: int):
    with db() as conn:
        capsule = conn.execute(
            """
            SELECT id, capsule_uuid, origin_capsule_uuid, capsule_type, summary,
                   parent_capsule_id, trust_level, review_status, created_at
            FROM capsules
            WHERE id = ?
            """,
            (capsule_id,),
        ).fetchone()
        if not capsule:
            fail_http(404, "Capsule not found")

        parent = None
        if capsule["parent_capsule_id"] is not None:
            parent = conn.execute(
                """
                SELECT id, capsule_uuid, capsule_type, summary, parent_capsule_id, created_at
                FROM capsules
                WHERE id = ?
                """,
                (capsule["parent_capsule_id"],),
            ).fetchone()

        links = conn.execute(
            """
            SELECT id, from_capsule_id, to_capsule_id, link_type, weight, metadata_json, created_at
            FROM capsule_links
            WHERE from_capsule_id = ? OR to_capsule_id = ?
            ORDER BY id
            """,
            (capsule_id, capsule_id),
        ).fetchall()

        return {
            "ok": True,
            "capsule": dict(capsule),
            "parent": dict(parent) if parent else None,
            "links": [dict(row) for row in links],
        }
