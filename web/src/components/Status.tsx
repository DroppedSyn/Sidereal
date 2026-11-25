import { ApiError } from '../api/client';

export function Loading({ what = 'Loading' }: { what?: string }) {
  return (
    <p className="status-note" role="status">
      {what}…
    </p>
  );
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError ? error.message : error instanceof Error ? error.message : 'Unknown error';
  return (
    <div className="status-note status-error" role="alert">
      <p>Could not load this view: {message}</p>
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
