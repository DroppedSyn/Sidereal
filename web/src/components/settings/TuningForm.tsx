// Scoring, budget and triage overrides (M27). Each editable key shows the effective value; an
// empty field means "use the config file". Saving replaces all overrides at once; the server
// checks bounds and the thresholds' order (top > relevant > side).
import { useState, type FormEvent } from 'react';
import { useSaveOverrides } from '../../api/settings';
import type { Overrides, SettingsView } from '../../api/types';

type Drafts = Record<string, Record<string, string>>;

function initialDrafts(view: SettingsView): Drafts {
  const out: Drafts = {};
  for (const [section, keys] of Object.entries(view.editable)) {
    out[section] = {};
    for (const key of keys) {
      const value = view.overrides[section]?.[key];
      out[section][key] = value === undefined || value === null ? '' : String(value);
    }
  }
  return out;
}

/** Overrides to send: only filled-in fields, as numbers (an unparsable one stays a string so
 * the server refuses it with a clear message). */
export function toOverrides(drafts: Drafts): Partial<Overrides> {
  const out: Record<string, Record<string, number | string>> = {};
  for (const [section, fields] of Object.entries(drafts)) {
    out[section] = {};
    for (const [key, text] of Object.entries(fields)) {
      if (text.trim() === '') continue;
      const n = Number(text);
      out[section][key] = Number.isFinite(n) ? n : text;
    }
  }
  return out as Partial<Overrides>;
}

function effective(view: SettingsView, section: string, key: string): string {
  const sec = view.config[section] as Record<string, unknown> | undefined;
  return String(sec?.[key] ?? '');
}

export default function TuningForm({ view }: { view: SettingsView }) {
  const [drafts, setDrafts] = useState<Drafts>(() => initialDrafts(view));
  const save = useSaveOverrides();

  function set(section: string, key: string, value: string) {
    setDrafts((d) => ({ ...d, [section]: { ...d[section], [key]: value } }));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(toOverrides(drafts), { onSuccess: (v) => setDrafts(initialDrafts(v)) });
  }

  return (
    <section className="settings-section" aria-labelledby="tuning-title">
      <h3 id="tuning-title">Scoring and budget</h3>
      <p className="settings-note">
        Leave a field empty to use the config file. New values apply from the next scan; stories
        already placed keep their bucket until <code>sidereal rescore</code>.
      </p>
      <form className="settings-form" aria-label="Scoring and budget" onSubmit={submit}>
        {Object.entries(view.editable).map(([section, keys]) => (
          <fieldset key={section} className="tuning-group">
            <legend>{section}</legend>
            {keys.map((key) => (
              <label key={key} className="field tuning-field">
                <span>{key}</span>
                <input inputMode="decimal" value={drafts[section]?.[key] ?? ''}
                  placeholder={effective(view, section, key)}
                  aria-label={`${section}.${key}`}
                  onChange={(e) => set(section, key, e.target.value)} />
              </label>
            ))}
          </fieldset>
        ))}
        <div className="form-actions">
          <button type="submit" className="button" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save overrides'}
          </button>
          <button type="button" className="link-button" disabled={save.isPending}
            onClick={() => save.mutate({ scoring: {}, budget: {}, triage: {} },
              { onSuccess: (v) => setDrafts(initialDrafts(v)) })}>
            Reset all to the file
          </button>
        </div>
        {save.isError ? <p role="alert" className="action-error">Not saved: {save.error.message}</p> : null}
        {save.isSuccess ? <p role="status" className="settings-note">Saved.</p> : null}
      </form>
    </section>
  );
}
