Added optional capsule TTL support.
Existing live database required manual ALTER TABLE for ttl_seconds and expires_at,
plus manual creation of idx_capsules_expires_at.
