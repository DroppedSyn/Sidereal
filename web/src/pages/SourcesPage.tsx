// Sources: health badge, last ok, last error, items in the last 7 days (plan §10.2).
import { useSources } from '../api/hooks';
import { ErrorNote, Loading } from '../components/Status';
import { formatDateTime } from '../lib/format';
import { safeHref } from '../lib/safeHref';

export default function SourcesPage() {
  const { data, isPending, isError, error, refetch } = useSources();
  let body;
  if (isPending) body = <Loading what="Loading sources" />;
  else if (isError) body = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else if (data.length === 0) body = <p className="status-note">No sources configured.</p>;
  else {
    body = (
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Health</th>
              <th scope="col">Last ok</th>
              <th scope="col" className="num">Items (7 days)</th>
              <th scope="col">Last error</th>
            </tr>
          </thead>
          <tbody>
            {data.map((s) => {
              const href = safeHref(s.url);
              return (
                <tr key={s.id} className={s.enabled ? undefined : 'source-disabled'}>
                  <td>
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer">{s.name}</a>
                    ) : (
                      s.name
                    )}
                    <span className="source-kind"> {s.kind}{s.enabled ? '' : ' · disabled'}</span>
                  </td>
                  <td>
                    <span className={`badge status-badge health-${s.health}`}>{s.health}</span>
                  </td>
                  <td>{s.last_ok_at ? formatDateTime(s.last_ok_at) : 'never'}</td>
                  <td className="num">{s.items_7d}</td>
                  <td className="source-error">{s.last_error ?? ''}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="page sources">
      <header className="page-header">
        <h2 className="page-title">Sources</h2>
      </header>
      {body}
    </div>
  );
}
