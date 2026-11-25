-- M24 feedback (plan §16 M24). Numbered 0003: 0002 is auth (M25 landed first).
-- One row per (story, kind). 'up' and 'down' are exclusive (feedback_repo.set_vote).
-- ON DELETE CASCADE: retention (stories_repo.delete_dropped_before) deletes stories.
CREATE TABLE feedback (
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('up','down','read','hide')),
  at TEXT NOT NULL,
  PRIMARY KEY (story_id, kind)
);
CREATE INDEX feedback_kind ON feedback(kind);

CREATE TABLE mutes (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('source','keyword')),
  value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(kind, value)
);
