// The muted sources and keywords, each with an Unmute button (M24).
import { useMutes, useRemoveMute } from '../api/feedback';
import { ErrorNote, Loading } from './Status';

export default function MutesList() {
  const { data, isPending, isError, error, refetch } = useMutes();
  const remove = useRemoveMute();
  let body;
  if (isPending) body = <Loading what="Loading mutes" />;
  else if (isError) body = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else if (data.length === 0) body = <p className="status-note">Nothing muted.</p>;
  else {
    body = (
      <ul className="mutes-list">
        {data.map((m) => (
          <li key={m.id}>
            <span className="badge">{m.kind}</span> <span className="mute-value">{m.value}</span>{' '}
            <button type="button" className="link-button" aria-label={`Unmute ${m.kind} ${m.value}`}
              onClick={() => remove.mutate(m.id)}>
              Unmute
            </button>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <section className="mutes" aria-labelledby="mutes-title">
      <h3 id="mutes-title" className="mutes-title">Muted</h3>
      {body}
      {remove.isError ? (
        <p role="alert" className="action-error">Could not unmute: {remove.error.message}</p>
      ) : null}
    </section>
  );
}
