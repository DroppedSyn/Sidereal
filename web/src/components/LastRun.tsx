// "Last scan 13:02 · next ~17:00", marked when the last run failed (plan §10.2).
import { useLastRun } from '../api/hooks';
import { formatDateTime, formatTime, nextScheduledRun } from '../lib/format';

export default function LastRun({ now }: { now?: Date }) {
  const { data: run, isPending, isError } = useLastRun();
  const next = formatTime(nextScheduledRun(now ?? new Date()));
  if (isPending) return <p className="last-run">Checking scans…</p>;
  if (isError) return <p className="last-run last-run-failed">Scan status unavailable</p>;
  if (run === null) return <p className="last-run">No scans yet · next ~{next}</p>;
  const at = formatTime(run.started_at);
  const title = `${formatDateTime(run.started_at)} · ${run.trigger} · ${run.status}`;
  if (run.status === 'running') {
    return (
      <p className="last-run last-run-running" title={title}>
        Scan running since {at}
      </p>
    );
  }
  const failed = run.status === 'failed';
  return (
    <p className={failed ? 'last-run last-run-failed' : 'last-run'} title={title}>
      Last scan {at}
      {failed ? ' failed' : run.status === 'partial' ? ' (partial)' : ''} · next ~{next}
    </p>
  );
}
