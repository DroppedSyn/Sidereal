// Daily: the day list on the left, the selected day's sub-gazette on the right (plan §10.2).
import { useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { useMarkDayRead } from '../api/feedback';
import { useDay, useDays } from '../api/hooks';
import type { DaySummary } from '../api/types';
import DayList from '../components/DayList';
import RunTimeline from '../components/RunTimeline';
import { ErrorNote, Loading } from '../components/Status';
import StorySections from '../components/StorySections';

function DayView({ day, now }: { day: string; now?: Date }) {
  const [includeDrop, setIncludeDrop] = useState(false);
  const { data, isPending, isError, error, refetch } = useDay(day, includeDrop);
  const markRead = useMarkDayRead(day);
  if (isPending) return <Loading what="Loading the day" />;
  if (isError) return <ErrorNote error={error} onRetry={() => void refetch()} />;
  return (
    <article className="day-view">
      <header className="page-header">
        <h2 className="page-title">{data.label}</h2>
        {data.headline ? <p className="day-headline">{data.headline}</p> : null}
        <button type="button" className="link-button" disabled={markRead.isPending}
          onClick={() => markRead.mutate()}>
          Mark day read
        </button>
        {markRead.isError ? (
          <p role="alert" className="action-error">Could not mark the day read: {markRead.error.message}</p>
        ) : null}
      </header>
      {data.overview ? <p className="day-overview">{data.overview}</p> : null}
      <RunTimeline runs={data.runs} />
      <StorySections sections={data.sections} counts={data.counts} includeDrop={includeDrop}
        onToggleDrop={() => setIncludeDrop((v) => !v)} now={now} />
    </article>
  );
}

export default function DailyPage({ now }: { now?: Date }) {
  const { day } = useParams();
  const daysQuery = useDays();
  const days: DaySummary[] = daysQuery.data?.pages.flat() ?? [];
  if (day === undefined && days[0] !== undefined) {
    return <Navigate to={`/daily/${days[0].day}`} replace />;
  }
  let left;
  if (daysQuery.isPending) left = <Loading what="Loading days" />;
  else if (daysQuery.isError) left = <ErrorNote error={daysQuery.error} />;
  else {
    left = (
      <DayList days={days} selected={day} hasMore={daysQuery.hasNextPage}
        loadingMore={daysQuery.isFetchingNextPage} onLoadMore={() => void daysQuery.fetchNextPage()} />
    );
  }
  return (
    <div className="page daily">
      <aside className="daily-left">{left}</aside>
      <div className="daily-right">
        {day !== undefined ? (
          <DayView key={day} day={day} now={now} />
        ) : daysQuery.isSuccess ? (
          <p className="status-note">No days yet. Stories appear here after the first scan.</p>
        ) : null}
      </div>
    </div>
  );
}
