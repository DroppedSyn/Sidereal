// Sources (M27): enable/disable at a click, edit name, URL, weight, cap and options, add, test,
// and delete (only sources without items; the server answers 409 otherwise).
import { useState } from 'react';
import { useDeleteSource, useSaveSource, useSourceConfigs } from '../../api/settings';
import type { SourceConfig, SourceKind } from '../../api/types';
import { ErrorNote, Loading } from '../Status';
import SourceForm from './SourceForm';

function asInput(s: SourceConfig, enabled: boolean) {
  return { key: s.key, kind: s.kind as SourceKind, name: s.name, url: s.url, enabled,
    weight: s.weight, max_items: s.max_items, options: s.options };
}

export default function SourceSettings() {
  const { data, isPending, isError, error, refetch } = useSourceConfigs();
  const toggle = useSaveSource();
  const remove = useDeleteSource();
  const [editing, setEditing] = useState<number | 'new' | null>(null);

  let body;
  if (isPending) body = <Loading what="Loading sources" />;
  else if (isError) body = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else {
    body = (
      <ul className="settings-list">
        {data.map((s) => (
          <li key={s.id} className={s.enabled ? undefined : 'setting-disabled'}>
            {editing === s.id ? (
              <SourceForm source={s} onDone={() => setEditing(null)} />
            ) : (
              <div className="setting-head">
                <label className="check">
                  <input type="checkbox" checked={s.enabled} disabled={toggle.isPending}
                    aria-label={`${s.name} enabled`}
                    onChange={(e) => toggle.mutate({ id: s.id, source: asInput(s, e.target.checked) })} />
                  <strong>{s.name}</strong>
                </label>
                <span className="badge">{s.kind}</span>
                <span className="setting-key">weight {s.weight} · max {s.max_items}</span>
                <span className="setting-url">{s.url}</span>
                <span className="form-actions">
                  <button type="button" className="action-button" aria-label={`Edit ${s.name}`}
                    onClick={() => setEditing(s.id)}>Edit</button>
                  <button type="button" className="action-button" aria-label={`Delete ${s.name}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(`Delete the source “${s.name}”?`)) remove.mutate(s.id);
                    }}>Delete</button>
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <section className="settings-section" aria-labelledby="sources-settings-title">
      <h3 id="sources-settings-title">Sources</h3>
      <p className="settings-note">
        Changes apply from the next scan. Sources that already have stories cannot be deleted:
        disable them instead.
      </p>
      {body}
      {toggle.isError ? (
        <p role="alert" className="action-error">Could not save: {toggle.error.message}</p>
      ) : null}
      {remove.isError ? (
        <p role="alert" className="action-error">Could not delete: {remove.error.message}</p>
      ) : null}
      {editing === 'new' ? (
        <SourceForm onDone={() => setEditing(null)} />
      ) : (
        <button type="button" className="button" onClick={() => setEditing('new')}>Add source</button>
      )}
    </section>
  );
}
