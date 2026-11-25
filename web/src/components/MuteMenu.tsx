// Mute one of the story's sources or a keyword (M24). Mutes apply to new stories at the next
// scan (prefilter); stories already shown stay until hidden.
import { useId, useState, type FormEvent } from 'react';
import { useAddMute } from '../api/feedback';
import type { Story } from '../api/types';

export default function MuteMenu({ story }: { story: Story }) {
  const add = useAddMute();
  const [keyword, setKeyword] = useState('');
  const inputId = useId();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const value = keyword.trim();
    if (!value) return;
    add.mutate({ kind: 'keyword', value }, { onSuccess: () => setKeyword('') });
  };
  let status = '';
  if (add.isSuccess) status = `Muted ${add.data.kind} “${add.data.value}” from the next scan.`;
  else if (add.isError) status = `Could not mute: ${add.error.message}`;
  return (
    <div className="mute-menu">
      <ul className="mute-sources">
        {story.sources.map((s) => (
          <li key={s.key}>
            <button type="button" className="action-button" disabled={add.isPending}
              onClick={() => add.mutate({ kind: 'source', value: s.key })}>
              Mute source {s.name}
            </button>
          </li>
        ))}
      </ul>
      <form className="mute-keyword" onSubmit={submit}>
        <label htmlFor={inputId}>Keyword</label>
        <input id={inputId} type="text" maxLength={200} value={keyword}
          onChange={(e) => setKeyword(e.target.value)} />
        <button type="submit" className="action-button" disabled={add.isPending || !keyword.trim()}>
          Mute keyword
        </button>
      </form>
      <p role="status" className="mute-status">{status}</p>
    </div>
  );
}
