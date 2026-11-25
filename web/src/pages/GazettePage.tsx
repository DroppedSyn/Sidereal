// The front page: the rolling last 24 hours (plan §10.2).
import { useState } from 'react';
import { useGazette } from '../api/hooks';
import { ErrorNote, Loading } from '../components/Status';
import StorySections from '../components/StorySections';
import { formatDate, formatTime } from '../lib/format';

export default function GazettePage({ now }: { now?: Date }) {
  const [includeDrop, setIncludeDrop] = useState(false);
  const { data, isPending, isError, error, refetch } = useGazette(includeDrop);
  return (
    <div className="page gazette">
      <header className="page-header">
        <h2 className="page-title">The Gazette</h2>
        {data ? (
          <p className="page-sub">
            Last 24 hours · {formatDate(data.generated_at)} · updated {formatTime(data.generated_at)}
          </p>
        ) : null}
      </header>
      {isPending ? (
        <Loading what="Loading the gazette" />
      ) : isError ? (
        <ErrorNote error={error} onRetry={() => void refetch()} />
      ) : (
        <StorySections sections={data.sections} counts={data.counts} includeDrop={includeDrop}
          onToggleDrop={() => setIncludeDrop((v) => !v)} now={now} />
      )}
    </div>
  );
}
