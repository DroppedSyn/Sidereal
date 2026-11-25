-- M28 notifications log (plan §16 M28). Numbered 0005: 0002 auth, 0003 feedback, 0004 search.
-- One row per (story, channel) once a send succeeded: the dispatcher never sends a story twice
-- on the same channel. Failures are not stored here (the run's stats and the log hold them), so
-- a failed story is retried on the next run while it is still recent.
CREATE TABLE notifications (
  story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('email','discord')),
  run_id INTEGER,
  sent_at TEXT NOT NULL,
  PRIMARY KEY (story_id, channel)
);
