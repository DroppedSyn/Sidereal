// Add or edit one source (M27). Options are edited as JSON (adapter-specific: article_hosts,
// include_regex, queries, …); the server validates them per kind. "Test feed" fetches the URL
// through the server's URL guard and shows how many entries it parsed; nothing is saved.
import { useState, type FormEvent } from 'react';
import { useSaveSource, useTestFeed } from '../../api/settings';
import type { SourceConfig, SourceIn, SourceKind } from '../../api/types';

const KINDS: SourceKind[] = ['rss', 'msrc', 'cisa_kev', 'hn_algolia'];

/** The options object, or an error text when the JSON is not an object. */
export function parseOptions(text: string): Record<string, unknown> | string {
  if (text.trim() === '') return {};
  try {
    const value: unknown = JSON.parse(text);
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    // fall through
  }
  return 'Options must be a JSON object, e.g. {"article_hosts": ["example.com"]}.';
}

interface Props {
  source?: SourceConfig; // absent → a new source
  onDone: () => void;
}

export default function SourceForm({ source, onDone }: Props) {
  const isNew = source === undefined;
  const [key, setKey] = useState(source?.key ?? '');
  const [kind, setKind] = useState<SourceKind>((source?.kind as SourceKind | undefined) ?? 'rss');
  const [name, setName] = useState(source?.name ?? '');
  const [url, setUrl] = useState(source?.url ?? '');
  const [weight, setWeight] = useState(String(source?.weight ?? 1));
  const [maxItems, setMaxItems] = useState(String(source?.max_items ?? 50));
  const [enabled, setEnabled] = useState(source?.enabled ?? true);
  const [options, setOptions] = useState(JSON.stringify(source?.options ?? {}, null, 2));
  const [localError, setLocalError] = useState('');
  const save = useSaveSource();
  const test = useTestFeed();

  function build(): SourceIn | null {
    const parsed = parseOptions(options);
    if (typeof parsed === 'string') {
      setLocalError(parsed);
      return null;
    }
    setLocalError('');
    return { key, kind, name, url, enabled, weight: Number(weight), max_items: Number(maxItems),
      options: parsed };
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const body = build();
    if (body) save.mutate({ source: body, id: source?.id ?? null }, { onSuccess: onDone });
  }

  function runTest() {
    const body = build();
    if (body) test.mutate({ kind, url, max_items: body.max_items, options: body.options });
  }

  const label = isNew ? 'New source' : `Edit ${source.name}`;
  return (
    <form className="settings-form" aria-label={label} onSubmit={submit}>
      {isNew ? (
        <div className="field-row">
          <label className="field">
            <span>Key (a-z, 0-9, -)</span>
            <input value={key} required maxLength={40} onChange={(e) => setKey(e.target.value)} />
          </label>
          <label className="field">
            <span>Kind</span>
            <select value={kind} onChange={(e) => setKind(e.target.value as SourceKind)}>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
        </div>
      ) : null}
      <label className="field">
        <span>Name</span>
        <input value={name} required maxLength={100} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span>Feed URL (http or https)</span>
        <input type="url" value={url} required onChange={(e) => setUrl(e.target.value)} />
      </label>
      <div className="field-row">
        <label className="field">
          <span>Weight (0.5 to 1.5)</span>
          <input type="number" min={0.5} max={1.5} step={0.05} value={weight}
            onChange={(e) => setWeight(e.target.value)} />
        </label>
        <label className="field">
          <span>Max items per fetch</span>
          <input type="number" min={1} max={500} step={1} value={maxItems}
            onChange={(e) => setMaxItems(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>Options (JSON)</span>
        <textarea className="mono" rows={4} value={options} spellCheck={false}
          onChange={(e) => setOptions(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enabled
      </label>
      <div className="form-actions">
        <button type="submit" className="button" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="action-button" disabled={test.isPending} onClick={runTest}>
          {test.isPending ? 'Testing…' : 'Test feed'}
        </button>
        <button type="button" className="link-button" onClick={onDone}>Cancel</button>
      </div>
      {localError ? <p role="alert" className="action-error">{localError}</p> : null}
      {save.isError ? <p role="alert" className="action-error">Not saved: {save.error.message}</p> : null}
      {test.isError ? <p role="alert" className="action-error">Test failed: {test.error.message}</p> : null}
      {test.data ? (
        <div className="feed-test" role="status">
          {test.data.ok ? (
            <p>Feed OK: {test.data.entries} entries, {test.data.items} kept after filters.</p>
          ) : (
            <p className="status-error">Feed not usable: {test.data.error}</p>
          )}
          {test.data.titles.length ? (
            <ul>{test.data.titles.map((t, i) => <li key={i}>{t}</li>)}</ul>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
