// The day's runs as status-coloured dots; status is also text, never colour alone.
import type { DayRun } from '../api/types';
import { formatDateTime, formatTime } from '../lib/format';

export default function RunTimeline({ runs }: { runs: DayRun[] }) {
  if (runs.length === 0) return <p className="timeline-empty">No scans this day.</p>;
  return (
    <ol className="timeline" aria-label="Scans this day">
      {runs.map((r) => (
        <li key={r.id} className={`timeline-run run-${r.status}`}
          title={`${formatDateTime(r.started_at)} · ${r.trigger} · ${r.status}`}>
          <span className="dot" aria-hidden="true" />
          <span className="timeline-time">{formatTime(r.started_at)}</span>
          {r.status === 'ok' ? (
            <span className="sr-only">ok</span>
          ) : (
            <span className="timeline-status">{r.status}</span>
          )}
        </li>
      ))}
    </ol>
  );
}
