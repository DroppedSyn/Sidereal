// Focus areas (M27): list with tier, keywords and state; edit, add, delete.
import { useState } from 'react';
import { useDeleteFocus, useFocusAreas } from '../../api/settings';
import { ErrorNote, Loading } from '../Status';
import FocusAreaForm from './FocusAreaForm';

export default function FocusAreas() {
  const { data, isPending, isError, error, refetch } = useFocusAreas();
  const remove = useDeleteFocus();
  const [editing, setEditing] = useState<string | null>(null); // a key, or '' for a new one

  let body;
  if (isPending) body = <Loading what="Loading focus areas" />;
  else if (isError) body = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else {
    body = (
      <ul className="settings-list">
        {data.map((f) => (
          <li key={f.key} className={f.enabled ? undefined : 'setting-disabled'}>
            {editing === f.key ? (
              <FocusAreaForm area={f} onDone={() => setEditing(null)} />
            ) : (
              <>
                <div className="setting-head">
                  <strong>{f.name}</strong> <span className="badge">{f.tier}</span>
                  {f.enabled ? null : <span className="badge">disabled</span>}
                  <span className="setting-key">{f.key}</span>
                </div>
                <p className="setting-desc">{f.description}</p>
                <p className="setting-keywords">
                  {f.keywords.length ? f.keywords.join(', ') : 'no keywords'}
                </p>
                <div className="form-actions">
                  <button type="button" className="action-button" aria-label={`Edit ${f.name}`}
                    onClick={() => setEditing(f.key)}>Edit</button>
                  <button type="button" className="action-button" aria-label={`Delete ${f.name}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(`Delete the focus area “${f.name}”?`)) remove.mutate(f.key);
                    }}>Delete</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <section className="settings-section" aria-labelledby="focus-title">
      <h3 id="focus-title">Focus areas</h3>
      <p className="settings-note">
        Changes apply from the next scan. A deleted default area comes back with{' '}
        <code>sidereal init</code>; disable it instead to keep it off.
      </p>
      {body}
      {remove.isError ? (
        <p role="alert" className="action-error">Could not delete: {remove.error.message}</p>
      ) : null}
      {editing === '' ? (
        <FocusAreaForm onDone={() => setEditing(null)} />
      ) : (
        <button type="button" className="button" onClick={() => setEditing('')}>Add focus area</button>
      )}
    </section>
  );
}
