-- MemberGuide SQLite contract v2. Applied by backend.core.db, including migrations.
-- bookings are stored in appointments (the name used by plan section 8).
-- Enable foreign_keys on EVERY connection; only the backend opens this database.
-- UTC timestamps use YYYY-MM-DDTHH:MM:SSZ; coverage dates use YYYY-MM-DD
-- interpreted in America/New_York. Code validates real dates and canonical format.
PRAGMA foreign_keys = ON;

CREATE TABLE plans (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL UNIQUE,
    network TEXT NOT NULL,
    specialist_referral_required INTEGER NOT NULL DEFAULT 1
        CHECK (specialist_referral_required IN (0, 1))
);

CREATE TABLE members (
    id TEXT PRIMARY KEY NOT NULL,
    full_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    member_digits TEXT NOT NULL CHECK (
        length(member_digits) = 4 AND member_digits NOT GLOB '*[^0-9]*'
    ),
    birth_month INTEGER NOT NULL CHECK (birth_month BETWEEN 1 AND 12),
    plan_id TEXT NOT NULL REFERENCES plans(id),
    coverage_start TEXT NOT NULL,
    coverage_end TEXT NOT NULL,
    CHECK (coverage_start <= coverage_end),
    -- Unique synthetic identity pair avoids ambiguous last-four/month matches.
    UNIQUE (member_digits, birth_month)
);

CREATE TABLE plan_sections (
    id TEXT PRIMARY KEY NOT NULL, -- e.g. GOLD-PREV, the evidence_id
    plan_id TEXT NOT NULL REFERENCES plans(id),
    topic TEXT NOT NULL CHECK (topic IN ('preventive', 'referral', 'plan_change')),
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (plan_id, topic)
);

CREATE TABLE providers (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    specialty TEXT NOT NULL,
    zip TEXT NOT NULL CHECK (length(zip) = 5 AND zip NOT GLOB '*[^0-9]*'),
    phone TEXT NOT NULL,
    accepting_new_patients INTEGER NOT NULL CHECK (accepting_new_patients IN (0, 1))
);

-- A provider can participate in multiple networks (P4 is METRO and VALUE).
-- A member's network is obtained through members.plan_id -> plans.network.
CREATE TABLE provider_networks (
    provider_id TEXT NOT NULL REFERENCES providers(id),
    network TEXT NOT NULL,
    PRIMARY KEY (provider_id, network)
);

CREATE TABLE slots (
    id TEXT PRIMARY KEY NOT NULL,
    provider_id TEXT NOT NULL REFERENCES providers(id),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    visit_type TEXT NOT NULL DEFAULT 'new_patient' CHECK (visit_type = 'new_patient'),
    modality TEXT NOT NULL DEFAULT 'in_person' CHECK (modality = 'in_person'),
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'booked', 'blocked')),
    -- Seeded occupancy need not invent a real member or appointment.
    -- blocked means the simulation button took it; booked may also be fixture occupancy.
    occupancy_reason TEXT CHECK (
        occupancy_reason IN ('seeded_occupancy', 'simulated_other_caller', 'appointment')
    ),
    seed_state TEXT NOT NULL DEFAULT 'open' CHECK (seed_state IN ('open', 'booked')),
    CHECK (starts_at < ends_at),
    CHECK (julianday(starts_at) IS NOT NULL AND julianday(ends_at) IS NOT NULL),
    CHECK (abs((julianday(ends_at) - julianday(starts_at)) * 86400 - 1800) < 0.001),
    CHECK (strftime('%M', starts_at) IN ('00', '30') AND strftime('%S', starts_at) = '00'),
    CHECK (
        (state = 'open' AND occupancy_reason IS NULL)
        OR (state = 'booked' AND occupancy_reason IS NOT NULL AND occupancy_reason IN ('seeded_occupancy', 'appointment'))
        OR (state = 'blocked' AND occupancy_reason IS NOT NULL AND occupancy_reason = 'simulated_other_caller')
    ),
    UNIQUE (provider_id, starts_at),
    UNIQUE (id, provider_id)
);

CREATE TABLE calls (
    id TEXT PRIMARY KEY NOT NULL,
    room TEXT NOT NULL UNIQUE, -- POST /calls retry key
    status TEXT NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'finalized')),
    created_at TEXT NOT NULL,
    finalized_at TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (
        verification_status IN ('unverified', 'verified', 'locked')
    ),
    verification_attempts INTEGER NOT NULL DEFAULT 0 CHECK (verification_attempts BETWEEN 0 AND 3),
    member_id TEXT REFERENCES members(id),
    request_version INTEGER NOT NULL DEFAULT 0 CHECK (request_version >= 0),
    specialty TEXT CHECK (specialty IN ('primary care', 'cardiology', 'dermatology')),
    operation TEXT NOT NULL DEFAULT 'book' CHECK (operation IN ('book', 'reschedule')),
    reschedule_appointment_id TEXT,
    zip TEXT CHECK (length(zip) = 5 AND zip NOT GLOB '*[^0-9]*'),
    selected_provider_id TEXT REFERENCES providers(id),
    -- Small snapshots keep this prototype independent of a second cache/service.
    -- providers_json = Provider[], excluded_json = Excluded[], evidence_json = Evidence[].
    providers_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(providers_json)),
    excluded_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(excluded_json)),
    evidence_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(evidence_json)),
    -- availability_query_json = availability request or null; offered_slots_json = Slot[].
    availability_query_json TEXT CHECK (
        availability_query_json IS NULL OR json_valid(availability_query_json)
    ),
    offered_slots_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(offered_slots_json)),
    current_draft_id TEXT REFERENCES drafts(id),
    first_request TEXT, -- first stated need, used for summary; never last goodbye
    unanswered_count INTEGER NOT NULL DEFAULT 0 CHECK (unanswered_count >= 0),
    tool_failure_count INTEGER NOT NULL DEFAULT 0 CHECK (tool_failure_count >= 0),
    summary_json TEXT CHECK (summary_json IS NULL OR json_valid(summary_json)),
    CHECK (
        (verification_status = 'verified' AND member_id IS NOT NULL)
        OR (verification_status IN ('unverified', 'locked') AND member_id IS NULL)
    ),
    CHECK ((status = 'live' AND finalized_at IS NULL) OR (status = 'finalized' AND finalized_at IS NOT NULL)),
    UNIQUE (id, member_id),
    FOREIGN KEY (reschedule_appointment_id, member_id) REFERENCES appointments(id, member_id),
    CHECK ((operation = 'book' AND reschedule_appointment_id IS NULL)
        OR (operation = 'reschedule' AND reschedule_appointment_id IS NOT NULL AND member_id IS NOT NULL))
);

CREATE TABLE turns (
    call_id TEXT NOT NULL REFERENCES calls(id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    client_turn_id TEXT NOT NULL, -- same delivery retry never creates a newer yes
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    received_at TEXT NOT NULL, -- assigned by backend, never client supplied
    PRIMARY KEY (call_id, seq),
    UNIQUE (call_id, client_turn_id)
);

CREATE TABLE drafts (
    id TEXT PRIMARY KEY NOT NULL,
    call_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES providers(id),
    slot_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    request_version INTEGER NOT NULL CHECK (request_version >= 1),
    status TEXT NOT NULL CHECK (status IN ('slot', 'preview', 'armed', 'booked', 'invalidated')),
    token TEXT UNIQUE, -- null until preview; opaque and never spoken
    details_hash TEXT CHECK (details_hash IS NULL OR length(details_hash) = 64),
    read_back TEXT,
    preview_user_seq INTEGER CHECK (preview_user_seq >= 0), -- 0 means no user turn
    armed_seq INTEGER CHECK (armed_seq >= 0), -- latest user sequence at arming
    armed_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT 'book' CHECK (operation IN ('book', 'reschedule')),
    reschedule_appointment_id TEXT,
    source_appointment_version INTEGER CHECK (source_appointment_version >= 1),
    referral_id TEXT,
    FOREIGN KEY (call_id, member_id) REFERENCES calls(id, member_id),
    FOREIGN KEY (slot_id, provider_id) REFERENCES slots(id, provider_id),
    FOREIGN KEY (reschedule_appointment_id, member_id) REFERENCES appointments(id, member_id),
    FOREIGN KEY (referral_id, member_id) REFERENCES referrals(id, member_id),
    UNIQUE (call_id, revision),
    CHECK ((operation = 'book' AND reschedule_appointment_id IS NULL AND source_appointment_version IS NULL)
        OR (operation = 'reschedule' AND reschedule_appointment_id IS NOT NULL AND source_appointment_version IS NOT NULL)),
    CHECK (
        status NOT IN ('preview', 'armed', 'booked')
        OR (token IS NOT NULL AND details_hash IS NOT NULL AND read_back IS NOT NULL AND preview_user_seq IS NOT NULL)
    ),
    CHECK (
        status NOT IN ('armed', 'booked')
        OR (armed_seq IS NOT NULL AND armed_at IS NOT NULL AND expires_at IS NOT NULL AND armed_at < expires_at)
    )
);

CREATE TABLE appointments (
    id TEXT PRIMARY KEY NOT NULL,
    call_id TEXT UNIQUE, -- voice: one committed action per call; fixture: null
    member_id TEXT NOT NULL REFERENCES members(id),
    provider_id TEXT NOT NULL REFERENCES providers(id),
    slot_id TEXT NOT NULL,
    draft_id TEXT UNIQUE REFERENCES drafts(id),
    confirmation TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'completed', 'cancelled', 'rescheduled')),
    starts_at TEXT NOT NULL, -- committed snapshot; code checks equality to slots
    ends_at TEXT NOT NULL,
    consent_turn_seq INTEGER,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'voice' CHECK (source IN ('voice', 'synthetic_fixture')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    referral_id TEXT,
    replaces_appointment_id TEXT UNIQUE,
    UNIQUE (id, member_id),
    FOREIGN KEY (call_id, member_id) REFERENCES calls(id, member_id),
    FOREIGN KEY (slot_id, provider_id) REFERENCES slots(id, provider_id),
    FOREIGN KEY (call_id, consent_turn_seq) REFERENCES turns(call_id, seq),
    FOREIGN KEY (referral_id, member_id) REFERENCES referrals(id, member_id),
    FOREIGN KEY (replaces_appointment_id, member_id) REFERENCES appointments(id, member_id),
    CHECK (replaces_appointment_id IS NULL OR replaces_appointment_id <> id),
    CHECK ((source = 'voice' AND call_id IS NOT NULL AND draft_id IS NOT NULL AND consent_turn_seq IS NOT NULL)
        OR (source = 'synthetic_fixture' AND call_id IS NULL AND draft_id IS NULL AND consent_turn_seq IS NULL)),
    CHECK (starts_at < ends_at),
    CHECK (julianday(starts_at) IS NOT NULL AND julianday(ends_at) IS NOT NULL),
    CHECK (abs((julianday(ends_at) - julianday(starts_at)) * 86400 - 1800) < 0.001)
);

-- A caller-reported recommendation is not a verified formal referral.
-- Validity on the visit date, specialty, PCP identity and source visit completion
-- are checked by backend policy, not inferred from the status alone.
CREATE TABLE referrals (
    id TEXT PRIMARY KEY NOT NULL,
    member_id TEXT NOT NULL REFERENCES members(id),
    referring_provider_id TEXT REFERENCES providers(id),
    referring_appointment_id TEXT,
    specialty TEXT NOT NULL CHECK (specialty IN ('cardiology', 'dermatology')),
    status TEXT NOT NULL CHECK (status IN ('reported', 'verified', 'revoked')),
    valid_from TEXT,
    valid_until TEXT,
    source TEXT NOT NULL CHECK (source IN ('synthetic_fixture', 'pcp_record', 'caller_report')),
    created_at TEXT NOT NULL,
    UNIQUE (id, member_id),
    FOREIGN KEY (referring_appointment_id, member_id) REFERENCES appointments(id, member_id),
    CHECK ((valid_from IS NULL AND valid_until IS NULL)
        OR (valid_from IS NOT NULL AND valid_until IS NOT NULL AND valid_from <= valid_until
            AND date(valid_from) IS NOT NULL AND date(valid_until) IS NOT NULL)),
    CHECK (status <> 'verified' OR (valid_from IS NOT NULL AND valid_until IS NOT NULL
        AND referring_provider_id IS NOT NULL AND referring_appointment_id IS NOT NULL)),
    CHECK (source <> 'caller_report' OR status = 'reported')
);
CREATE INDEX referrals_member_specialty ON referrals(member_id, specialty, status, valid_until);

-- Opt-in demo history is installed once per database. Reseeding returns the
-- original manifest and never restores a slot that a later caller booked.
CREATE TABLE demo_fixture_sets (
    id TEXT PRIMARY KEY NOT NULL,
    demo_date TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    created_at TEXT NOT NULL
);

-- Required defense against double booking even if an application guard fails.
CREATE UNIQUE INDEX one_booked_appointment_per_slot
    ON appointments(slot_id) WHERE status = 'booked';
CREATE INDEX appointments_member_interval ON appointments(member_id, starts_at, ends_at);
CREATE INDEX appointments_provider_interval ON appointments(provider_id, starts_at, ends_at);
CREATE INDEX slots_provider_start ON slots(provider_id, starts_at);
CREATE INDEX latest_user_turn ON turns(call_id, role, seq DESC);
CREATE INDEX calls_latest ON calls(created_at DESC, id DESC);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(id),
    name TEXT NOT NULL, -- ordered names project to State.events
    created_at TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(detail_json))
);
CREATE INDEX events_call_order ON events(call_id, id);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY NOT NULL,
    call_id TEXT NOT NULL REFERENCES calls(id),
    reference TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL CHECK (category IN (
        'caller_requested', 'knowledge_gap', 'verification_failed',
        'tool_failure', 'safety', 'policy_required', 'waitlist'
    )),
    detail TEXT NOT NULL,
    -- Explicit retry/incident identity; repeated triggers do not duplicate packets.
    dedupe_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
    packet_json TEXT NOT NULL CHECK (json_valid(packet_json)), -- Packet in api.md
    created_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK ((status = 'open' AND completed_at IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL)),
    UNIQUE (call_id, dedupe_key)
);

-- Cross-row booking rules belong in one BEGIN IMMEDIATE transaction, NOT a
-- separate preflight check: call membership/verification, current draft ownership,
-- token/hash, latest finalized user consent, timing, coverage on visit date,
-- provider network/new-patient status, latest offer set, open slot and intervals
-- for both member and provider. Update slot, draft, appointment and events together.
-- Hash canonical compact UTF-8 JSON with fixed field order and SHA-256:
-- [member_id, provider_id, slot_id, starts_at, ends_at, visit_type, modality].
-- IDs are stored strings; no local-time timestamps enter the hash.
-- Token replay finds appointments through drafts.token before live-call checks.
-- SQL constraints do not prove audible playout or semantic consent.
-- Draft/token mutation is forbidden once its appointment commits.
-- Rescheduling appends a replacement appointment (replaces_appointment_id),
-- marks the original rescheduled and increments its version, claims the new
-- slot and releases the old slot in ONE transaction after a new consent cycle.
-- Compare the draft's source_appointment_version at commit. On conflict, roll
-- back everything and keep the original booking. Recheck referral validity on
-- the NEW visit date. Same provider/visit type/modality for the first extension.
-- The pending-write barrier and per-call ordered ingress are backend duties.
--
-- Reset under that same barrier only when no call/write is active. Break the
-- circular reference first: set calls.current_draft_id = NULL, then delete tasks,
-- events, voice appointments, drafts, turns, calls. Calls and drafts now also
-- reference source appointments: clear/delete these references before parents.
-- Preserve synthetic_fixture appointments and their referrals. Reset their
-- statuses/versions and slots from the selected journey fixture manifest;
-- a generic DELETE FROM appointments is no longer a valid reset.
-- Restore other slots.state = seed_state,
-- occupancy_reason = NULL for open or seeded_occupancy for seeded booked slots.
-- Keep plans, members, plan_sections, providers, provider_networks and slot fixtures.
PRAGMA user_version = 2;
