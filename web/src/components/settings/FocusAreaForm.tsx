// Add or edit one focus area (M27). Keywords are typed comma-separated; the server trims,
// lower-cases and de-duplicates them and refuses empty ones (422, shown below the form).
import { useState, type FormEvent } from 'react';
import { useSaveFocus } from '../../api/settings';
import type { FocusArea, FocusTier } from '../../api/types';

const TIERS: FocusTier[] = ['primary', 'secondary', 'side'];

export function splitKeywords(text: string): string[] {
  return text.split(',').map((k) => k.trim()).filter((k) => k !== '');
}

interface Props {
  area?: FocusArea; // absent → a new area
  onDone: () => void;
}

export default function FocusAreaForm({ area, onDone }: Props) {
  const isNew = area === undefined;
  const [key, setKey] = useState(area?.key ?? '');
  const [name, setName] = useState(area?.name ?? '');
  const [tier, setTier] = useState<FocusTier>(area?.tier ?? 'secondary');
  const [description, setDescription] = useState(area?.description ?? '');
  const [keywords, setKeywords] = useState((area?.keywords ?? []).join(', '));
  const [enabled, setEnabled] = useState(area?.enabled ?? true);
  const save = useSaveFocus();

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(
      { isNew, area: { key, name, tier, description, keywords: splitKeywords(keywords), enabled } },
      { onSuccess: onDone },
    );
  }

  const label = isNew ? 'New focus area' : `Edit ${area.name}`;
  return (
    <form className="settings-form" aria-label={label} onSubmit={submit}>
      {isNew ? (
        <label className="field">
          <span>Key (a-z, 0-9, -)</span>
          <input value={key} required maxLength={40} onChange={(e) => setKey(e.target.value)} />
        </label>
      ) : null}
      <label className="field">
        <span>Name</span>
        <input value={name} required maxLength={80} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        <span>Tier</span>
        <select value={tier} onChange={(e) => setTier(e.target.value as FocusTier)}>
          {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <label className="field">
        <span>Description (goes into the prompts, at least 40 characters)</span>
        <textarea value={description} rows={4} maxLength={2000}
          onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="field">
        <span>Keywords (comma-separated)</span>
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)} />
      </label>
      <label className="check">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enabled
      </label>
      <div className="form-actions">
        <button type="submit" className="button" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="link-button" onClick={onDone}>Cancel</button>
      </div>
      {save.isError ? <p role="alert" className="action-error">Not saved: {save.error.message}</p> : null}
    </form>
  );
}
