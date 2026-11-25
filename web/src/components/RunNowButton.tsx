// Manual run (POST /api/runs, which sends X-Sidereal: 1 via apiPost).
import { ApiError } from '../api/client';
import { useStartRun } from '../api/hooks';

function failure(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return 'A scan is already running.';
  if (error instanceof Error) return `Could not start a scan: ${error.message}`;
  return 'Could not start a scan.';
}

export default function RunNowButton() {
  const start = useStartRun();
  return (
    <div className="run-now">
      <button type="button" className="button" disabled={start.isPending}
        onClick={() => start.mutate()}>
        {start.isPending ? 'Starting…' : 'Run now'}
      </button>
      <span role="status" className="run-now-status">
        {start.isSuccess ? 'Scan started.' : start.isError ? failure(start.error) : ''}
      </span>
    </div>
  );
}
