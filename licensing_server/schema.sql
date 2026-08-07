-- server/schema.sql
-- SQLite schema for the Commerce Manager licensing server.
-- Run once via server/db.py:init_db()

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,          -- uuid4
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,             -- argon2id hash
    full_name       TEXT,
    is_admin        INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,          -- uuid4
    customer_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id       TEXT NOT NULL,             -- hashed fingerprint from device.py
    first_seen_at   INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1, -- flips to 0 on admin "Reset Device"
    UNIQUE (customer_id, device_id)
);

CREATE TABLE IF NOT EXISTS licenses (
    id              TEXT PRIMARY KEY,          -- uuid4, == license_id in signed payload
    customer_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id       TEXT NOT NULL,             -- fingerprint this license is bound to
    license_type    TEXT NOT NULL CHECK (license_type IN ('trial', 'professional')),
    status          TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'revoked'))
                        DEFAULT 'active',
    features        TEXT NOT NULL,             -- JSON array, mirrors signed payload
    issued_at       INTEGER NOT NULL,
    expires_at      INTEGER,                   -- NULL == perpetual (professional)
    issued_by       TEXT NOT NULL,              -- admin username or 'self-service'
    signature       TEXT NOT NULL,             -- base64 Ed25519 signature (audit copy)
    payload_json    TEXT NOT NULL,             -- exact signed payload (audit copy)
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_licenses_customer ON licenses(customer_id);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);

CREATE TABLE IF NOT EXISTS license_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id      TEXT REFERENCES licenses(id) ON DELETE SET NULL,
    customer_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
    event_type      TEXT NOT NULL,             -- login, issue_trial, issue_paid,
                                                -- reactivate, device_reset, disable,
                                                -- revoke, validation_failed
    detail          TEXT,                      -- free-form JSON, e.g. {"ip": "...", "device_id": "..."}
    ip_address      TEXT,
    created_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_customer ON license_logs(customer_id);

CREATE TABLE IF NOT EXISTS server_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON license_logs(created_at);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token           TEXT PRIMARY KEY,
    admin_user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL
);
