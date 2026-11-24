# Prompts

Versioned prompt text for the LLM stages (plan §7.3, §7.4): `triage.v1.txt`, `assess.v1.txt`,
`day_digest.v1.txt`, `week_digest.v1.txt` (the week digest is used from M29). Written by Claude
and changed only by Claude, measured with the golden set (plan §15). **pi never edits prompt
text**; `llm/prompts.py` only loads and renders these files.

## File format

1. An optional header: leading lines that start with `#`. The renderer strips every line from
   the top of the file while it starts with `#` (the first line not starting with `#` ends the
   header). Header lines are never sent to the model and may mention placeholders freely.
2. The system part.
3. A line that is exactly `=== USER ===` (exactly once per file).
4. The user part.

Both parts are stripped of leading/trailing whitespace and must be non-empty. Each part is then
rendered with `str.format_map(mapping)` where a missing key raises (`KeyError`). Placeholders are
`{name}`; literal braces would be doubled (`{{` / `}}`), but v1 prompts use none:
after rendering, no `{` or `}` may remain except inside inserted values (the test checks this).
Values are inserted as is (they are never formatted again), so braces inside article text are safe.

The prompt version is the file stem (`assess.v1`) and is stored with each result.
System parts contain no per-story values, so they stay identical within a run (Ollama can reuse
the prompt prefix); per-call values (`{today}`, the stories) are in the user part.

## Placeholders

All values are strings built by code. Every value that carries article-derived text
(`{items}`, `{article}`, `{stories}`) arrives already wrapped by code as
`<untrusted_article>\n…\n</untrusted_article>`, with any `untrusted_article` tag inside the
content neutralised (`<` → `‹` in the tag) before wrapping (plan §7.4).

| placeholder | used in | content |
|---|---|---|
| `{focus_areas}` | triage, assess (system) | enabled focus areas, one per line: `- key (tier): description` (description verbatim from the DB) |
| `{focus_keys}` | assess (system) | enabled focus keys, comma-separated, without `none` (e.g. `azure-networking, entra-identity`); the schema's `focus` enum is these keys plus `none` |
| `{today}` | triage, assess (user) | the run's local date, `YYYY-MM-DD` |
| `{count}` | triage (user) | number of stories in the batch |
| `{items}` | triage (user) | wrapped block, one story per line: `[id] title — source — excerpt` (excerpt ≤ 300 chars, one line) |
| `{article}` | assess (user) | wrapped block with lines `Title: …`, `Sources: …`, `Published: …`, `Excerpt: …` and, if enriched, `Article text: …` (capped, plan §7.2) |
| `{day_label}` | day_digest (user) | `timeutil.day_label(day)`, e.g. `Tuesday - 14.07.2026` |
| `{stories}` | day_digest, week_digest (user) | wrapped block, one story per line, TOP first then by score: day digest `[TOP] title: summary`; week digest `[TOP] 2026-07-14 — title: summary` |
| `{week_label}` | week_digest (user) | e.g. `Week 29, 13.07.2026 - 19.07.2026` |

Per file:
- `triage.v1`: `{focus_areas}`, `{today}`, `{count}`, `{items}`
- `assess.v1`: `{focus_areas}`, `{focus_keys}`, `{today}`, `{article}`
- `day_digest.v1`: `{day_label}`, `{stories}`
- `week_digest.v1`: `{week_label}`, `{stories}`

The JSON schemas themselves are sent via Ollama's `format` field (plan §7.3); the prompts only
describe the fields. Digests reply `{"overview": "...", "headline": "..."}`.

## Versioning

Never edit a `.vN` file after it has been used in a real run: copy it to `.vN+1`, change the
copy, measure it with `sidereal eval --prompt <name>.vN+1`, then switch the config. Before first
real use (M14) a `.v1` file may still be edited. `tests/test_prompt_files.py` checks the format
and the placeholder sets above; update both together.
