-- 0001_init.sql
CREATE TABLE sources (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,              -- 'azure-updates'
  name TEXT NOT NULL,
  kind TEXT NOT NULL,                    -- 'rss' | 'cisa_kev' | 'hn_algolia' | 'msrc'
  url TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  weight REAL NOT NULL DEFAULT 1.0,      -- 0.5 .. 1.5, multiplies source bonus (§8)
  max_items INTEGER NOT NULL DEFAULT 50, -- per fetch, newest first
  options_json TEXT NOT NULL DEFAULT '{}',
  etag TEXT, last_modified TEXT,
  last_fetch_at TEXT, last_ok_at TEXT, last_error TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  zero_item_runs INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE focus_areas (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('primary','secondary','side')),
  description TEXT NOT NULL,             -- goes into prompts
  keywords_json TEXT NOT NULL,           -- prefilter positive terms
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL, finished_at TEXT,
  trigger TEXT NOT NULL,                 -- 'timer' | 'manual' | 'catchup'
  status TEXT NOT NULL,                  -- 'running'|'ok'|'partial'|'failed'|'skipped'
  stats_json TEXT NOT NULL DEFAULT '{}', -- per stage counts + durations (§9.4)
  error TEXT
);
CREATE TABLE stories (                   -- the unit the UI shows: one event, ≥1 items
  id INTEGER PRIMARY KEY,
  lead_item_id INTEGER,                  -- set after first item insert
  title TEXT NOT NULL,
  day TEXT NOT NULL,                     -- local YYYY-MM-DD of first_seen_at
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  first_run_id INTEGER NOT NULL REFERENCES runs(id),
  state TEXT NOT NULL,                   -- 'new'|'filtered'|'triaged_out'|'assessed'|'assess_failed'
  filter_reason TEXT,
  triage_relevance INTEGER,              -- 0..3
  score REAL, bucket TEXT CHECK (bucket IN ('top','relevant','side','drop')),
  cve_ids_json TEXT NOT NULL DEFAULT '[]',
  flags_json TEXT NOT NULL DEFAULT '{}'  -- {"kev":true,"exploited":true,"cvss":9.8}
);
CREATE INDEX stories_day ON stories(day, bucket, score DESC);
CREATE INDEX stories_seen ON stories(first_seen_at);
CREATE TABLE items (                     -- one per source article
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  story_id INTEGER NOT NULL REFERENCES stories(id),
  guid TEXT, url TEXT NOT NULL, canonical_url TEXT NOT NULL,
  title TEXT NOT NULL, title_norm TEXT NOT NULL,
  author TEXT, published_at TEXT,        -- NULL if the feed gave none
  first_seen_at TEXT NOT NULL, run_id INTEGER NOT NULL REFERENCES runs(id),
  excerpt TEXT NOT NULL DEFAULT '',      -- plain text ≤ 1500 chars
  content_text TEXT,                     -- enrichment, plain text ≤ 20000 chars; pruned (§12.4)
  content_status TEXT,                   -- NULL|'ok'|'blocked'|'failed'|'skipped'
  UNIQUE(source_id, guid),
  UNIQUE(canonical_url)
);
CREATE TABLE assessments (
  story_id INTEGER PRIMARY KEY REFERENCES stories(id),
  model TEXT NOT NULL, prompt_version TEXT NOT NULL,
  relevance INTEGER NOT NULL, urgency INTEGER NOT NULL,
  actionability INTEGER NOT NULL, novelty INTEGER NOT NULL,   -- each 0..3
  tags_json TEXT NOT NULL, summary TEXT NOT NULL, why TEXT NOT NULL,
  raw_json TEXT NOT NULL, duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE day_digests (
  day TEXT PRIMARY KEY, overview TEXT NOT NULL, headline TEXT NOT NULL,
  story_ids_json TEXT NOT NULL,   -- TOP/Relevant story ids the digest was built from (M12b)
  model TEXT NOT NULL, run_id INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
