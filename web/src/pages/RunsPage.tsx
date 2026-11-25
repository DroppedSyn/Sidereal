// Runs: a table with status, duration and a stat summary; a row expands to the full stats.
import { Fragment, useState } from 'react';
import { useRuns } from '../api/hooks';
import type { Run } from '../api/types';
import RunNowButton from '../components/RunNowButton';
import { ErrorNote, Loading } from '../components/Status';
import { formatDateTime, formatDuration } from '../lib/format';
import { summarizeStats } from '../lib/runStats';

function RunRow({ run, open, onToggle }: { run: Run; open: boolean; onToggle: () => void }) {
  return (
    <Fragment>
      <tr className={`run-row run-${run.status}`}>
        <td>
          <button type="button" className="link-button" aria-expanded={open} onClick={onToggle}>
            {formatDateTime(run.started_at)}
          </button>
        </td>
        <td>{run.trigger}</td>
        <td>
          <span className={`badge status-badge status-${run.status}`}>{run.status}</span>
        </td>
        <td>{formatDuration(run.duration_s)}</td>
        <td className="run-summary">{run.error ?? summarizeStats(run.stats)}</td>
      </tr>
      {open ? (
        <tr className="run-details">
          <td colSpan={5}>
            {run.error ? <p className="run-error">Error: {run.error}</p> : null}
            <pre className="stats-json">{JSON.stringify(run.stats, null, 2)}</pre>
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

export default function RunsPage() {
  const { data, isPending, isError, error, refetch } = useRuns();
  const [open, setOpen] = useState<number | null>(null);
  let body;
  if (isPending) body = <Loading what="Loading runs" />;
  else if (isError) body = <ErrorNote error={error} onRetry={() => void refetch()} />;
  else if (data.length === 0) body = <p className="status-note">No scans yet.</p>;
  else {
    body = (
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Trigger</th>
              <th scope="col">Status</th>
              <th scope="col">Duration</th>
              <th scope="col">Summary</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <RunRow key={r.id} run={r} open={open === r.id}
                onToggle={() => setOpen(open === r.id ? null : r.id)} />
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div className="page runs">
      <header className="page-header page-header-row">
        <h2 className="page-title">Runs</h2>
        <RunNowButton />
      </header>
      {body}
    </div>
  );
}
