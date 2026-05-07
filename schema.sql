PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT,
    public_key TEXT,
    trust_tier TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,         -- session, document, url, opml, transcript, manual
    source_ref TEXT,                   -- external id, filename, URL, doc id, etc.
    hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS capsules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capsule_uuid TEXT NOT NULL UNIQUE,
    protocol_version TEXT NOT NULL DEFAULT 'dccp-1976-0.1',
    capsule_type TEXT NOT NULL,        -- distill, transformation, dream, weave, recovery
    summary TEXT NOT NULL,
    body TEXT NOT NULL,                -- DCCP JSON body
    confidence REAL DEFAULT 0.5,
    retention TEXT DEFAULT 'normal',   -- ephemeral, normal, durable, permanent
    scope TEXT DEFAULT 'private',      -- private, shared, public
    trust_level TEXT DEFAULT 'local',  -- local, trusted, federated, quarantined, deprecated
    review_status TEXT DEFAULT 'unreviewed',
    source_agent_id INTEGER,
    source_id INTEGER,
    parent_capsule_id INTEGER,
    supersedes_capsule_id INTEGER,
    lineage_json TEXT,                 -- explicit ancestry details
    metadata_json TEXT,                -- tags, embedding refs, doc refs, etc.
    content_hash TEXT,
    signature TEXT,
    signature_algorithm TEXT,
    signer_key_id TEXT,
    signed_at TEXT,
    origin_capsule_uuid TEXT,
    import_bundle_hash TEXT,
    ttl_seconds INTEGER,              -- optional TTL in seconds from ingestion time
    expires_at TEXT,                  -- computed UTC expiry timestamp; NULL means retain indefinitely
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_agent_id) REFERENCES agents(id),
    FOREIGN KEY (source_id) REFERENCES sources(id),
    FOREIGN KEY (parent_capsule_id) REFERENCES capsules(id),
    FOREIGN KEY (supersedes_capsule_id) REFERENCES capsules(id)
);

CREATE TABLE IF NOT EXISTS capsule_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_capsule_id INTEGER NOT NULL,
    to_capsule_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,           -- derived_from, contradicts, supports, extends, recovers, dreams_over
    weight REAL DEFAULT 1.0,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_capsule_id) REFERENCES capsules(id) ON DELETE CASCADE,
    FOREIGN KEY (to_capsule_id) REFERENCES capsules(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER,
    action TEXT NOT NULL,              -- store, get, search, recover, link, import_bundle
    capsule_id INTEGER,
    remote_addr TEXT,
    request_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    FOREIGN KEY (capsule_id) REFERENCES capsules(id)
);

CREATE INDEX IF NOT EXISTS idx_capsules_type ON capsules(capsule_type);
CREATE INDEX IF NOT EXISTS idx_capsules_created_at ON capsules(created_at);
CREATE INDEX IF NOT EXISTS idx_capsules_agent ON capsules(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_capsules_expires_at ON capsules(expires_at);
CREATE INDEX IF NOT EXISTS idx_capsule_links_from ON capsule_links(from_capsule_id);
CREATE INDEX IF NOT EXISTS idx_capsule_links_to ON capsule_links(to_capsule_id);
CREATE INDEX IF NOT EXISTS idx_access_log_agent ON access_log(agent_id);
