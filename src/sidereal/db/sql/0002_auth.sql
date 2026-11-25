-- M25 auth (plan §11.2). Numbered 0002 (next free number): migrations apply in order and a file
-- numbered below the current version would never run, so later milestones take 0003+.
-- No row is ever inserted here: there is no default account (rule 8).

CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,          -- lower-case, checked in code
  pw_hash TEXT NOT NULL,                  -- Argon2id PHC string, never the password
  created_at TEXT NOT NULL,
  totp_secret TEXT,                       -- base32, NULL = no TOTP
  disabled INTEGER NOT NULL DEFAULT 0
);

-- id_hash = SHA-256 hex of the cookie token; the token itself is never stored.
CREATE TABLE sessions (
  id_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,               -- absolute limit (30 days)
  user_agent TEXT,
  ip TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);

-- One row per login attempt (rate limit, plan §11.2); pruned after a day.
CREATE TABLE login_attempts (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL,                 -- as submitted (normalised), user may not exist
  ip TEXT NOT NULL,
  at TEXT NOT NULL,
  ok INTEGER NOT NULL
);
CREATE INDEX login_attempts_user ON login_attempts(username, at);
CREATE INDEX login_attempts_ip ON login_attempts(ip, at);
