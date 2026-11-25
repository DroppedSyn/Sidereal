-- M26 search (plan §16 M26). Numbered 0004: 0002 is auth, 0003 is feedback.
-- One FTS5 row per story, rowid = stories.id: the story title, the assessment's summary,
-- why and tags (space-joined), and every item excerpt of the story (space-joined).
-- Never items.content_text (article text stays out of the API, plan §10.1).
-- Kept in sync by triggers: each one rebuilds the affected story's row from the tables
-- (delete, then insert the current values), so the order of writes does not matter.
CREATE VIRTUAL TABLE story_search USING fts5(
  title, summary, why, tags, excerpt,
  tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER story_search_stories_ai AFTER INSERT ON stories BEGIN
  DELETE FROM story_search WHERE rowid = NEW.id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = NEW.id;
END;

CREATE TRIGGER story_search_stories_au AFTER UPDATE OF title ON stories BEGIN
  DELETE FROM story_search WHERE rowid = NEW.id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = NEW.id;
END;

CREATE TRIGGER story_search_stories_ad AFTER DELETE ON stories BEGIN
  DELETE FROM story_search WHERE rowid = OLD.id;
END;

CREATE TRIGGER story_search_assessments_ai AFTER INSERT ON assessments BEGIN
  DELETE FROM story_search WHERE rowid = NEW.story_id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = NEW.story_id;
END;

-- Also fires for save_assessment's upsert (INSERT … ON CONFLICT DO UPDATE).
CREATE TRIGGER story_search_assessments_au AFTER UPDATE ON assessments BEGIN
  DELETE FROM story_search WHERE rowid IN (OLD.story_id, NEW.story_id);
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id
  WHERE s.id IN (OLD.story_id, NEW.story_id);
END;

CREATE TRIGGER story_search_assessments_ad AFTER DELETE ON assessments BEGIN
  DELETE FROM story_search WHERE rowid = OLD.story_id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = OLD.story_id;
END;

CREATE TRIGGER story_search_items_ai AFTER INSERT ON items BEGIN
  DELETE FROM story_search WHERE rowid = NEW.story_id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = NEW.story_id;
END;

CREATE TRIGGER story_search_items_au AFTER UPDATE OF excerpt, story_id ON items BEGIN
  DELETE FROM story_search WHERE rowid IN (OLD.story_id, NEW.story_id);
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id
  WHERE s.id IN (OLD.story_id, NEW.story_id);
END;

CREATE TRIGGER story_search_items_ad AFTER DELETE ON items BEGIN
  DELETE FROM story_search WHERE rowid = OLD.story_id;
  INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
  SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
    COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
    COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
  FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id WHERE s.id = OLD.story_id;
END;

-- Backfill every existing story.
INSERT INTO story_search (rowid, title, summary, why, tags, excerpt)
SELECT s.id, s.title, COALESCE(a.summary, ''), COALESCE(a.why, ''),
  COALESCE((SELECT group_concat(j.value, ' ') FROM json_each(a.tags_json) AS j), ''),
  COALESCE((SELECT group_concat(i.excerpt, ' ') FROM items AS i WHERE i.story_id = s.id), '')
FROM stories AS s LEFT JOIN assessments AS a ON a.story_id = s.id;
