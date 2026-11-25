-- M29 weekly digest (plan §16 M29): one LLM overview per ISO week ('YYYY-Www', Monday..Sunday
-- of local days in schedule.tz). story_ids_json = the TOP/Relevant ids the digest was built
-- from, so the runner rewrites it only when the week's set changed (as day_digests, M12b).
CREATE TABLE week_digests (
  week TEXT PRIMARY KEY,
  start_day TEXT NOT NULL,
  end_day TEXT NOT NULL,
  overview TEXT NOT NULL,
  headline TEXT NOT NULL,
  story_ids_json TEXT NOT NULL,
  model TEXT NOT NULL,
  run_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
