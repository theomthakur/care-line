-- Additive migration. Existing calls have no grant and cannot be accessed by agents.
CREATE TABLE IF NOT EXISTS deployment_scope (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    organization TEXT NOT NULL,
    environment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS call_access (
    call_id TEXT PRIMARY KEY REFERENCES calls(id),
    owner_subject TEXT NOT NULL,
    key_hash TEXT NOT NULL CHECK (length(key_hash)=64)
);
CREATE TABLE IF NOT EXISTS identity_reviews (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(id),
    reviewer TEXT NOT NULL,
    policy TEXT NOT NULL,
    reference TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('verified','failed')),
    created_at TEXT NOT NULL,
    UNIQUE (call_id, reference)
);
CREATE TABLE IF NOT EXISTS legal_holds (
    call_id TEXT PRIMARY KEY REFERENCES calls(id),
    reference TEXT NOT NULL
);
