// Week (M29): the weekly digest. Left: weeks with a digest (plus this week so far); right: the
// selected week's headline, overview, Markdown export and print, then its TOP and Relevant.
import { Navigate, NavLink, useNavigate, useParams } from 'react-router-dom';
import { useWeek, useWeeks } from '../api/hooks';
import type { WeekSummary } from '../api/types';
import BucketSection from '../components/BucketSection';
import { ErrorNote, Loading } from '../components/Status';
import { currentWeek, paragraphs } from '../lib/week';

const WEEK_KEY = /^\d{4}-W\d{2}$/;

interface Entry {
  week: string;
  label: string;
  note: string;
}

function entries(weeks: WeekSummary[], thisWeek: string): Entry[] {
  const out: Entry[] = weeks.map((w) => ({ week: w.week, label: w.label, note: w.headline }));
  if (!weeks.some((w) => w.week === thisWeek)) {
    out.unshift({ week: thisWeek, label: 'This week so far', note: thisWeek });
  }
  return out;
}

function WeekList({ items, selected }: { items: Entry[]; selected: string | undefined }) {
  const navigate = useNavigate();
  return (
    <div className="daylist">
      <label className="dayselect">
        <span className="sr-only">Week</span>
        <select value={selected ?? ''} onChange={(e) => navigate(`/week/${e.target.value}`)}>
          {selected !== undefined && !items.some((i) => i.week === selected) ? (
            <option value={selected}>{selected}</option>
          ) : null}
          {items.map((i) => (
            <option key={i.week} value={i.week}>{i.label}</option>
          ))}
        </select>
      </label>
      <nav className="daylist-pane" aria-label="Weeks">
        <ol>
          {items.map((i) => (
            <li key={i.week}>
              <NavLink to={`/week/${i.week}`} className="day-row">
                <span className="day-label">{i.label}</span>
                <span className="day-counts">{i.note}</span>
              </NavLink>
            </li>
          ))}
        </ol>
      </nav>
    </div>
  );
}

function WeekView({ week, now }: { week: string; now?: Date }) {
  const { data, isPending, isError, error, refetch } = useWeek(week);
  if (isPending) return <Loading what="Loading the week" />;
  if (isError) return <ErrorNote error={error} onRetry={() => void refetch()} />;
  return (
    <article className="week-view">
      <header className="page-header">
        <h2 className="page-title">{data.label}</h2>
        {data.headline ? <p className="day-headline">{data.headline}</p> : null}
        <div className="week-actions">
          <a className="link-button" href={`/api/weeks/${encodeURIComponent(week)}/export.md`} download>
            Export Markdown
          </a>
          <button type="button" className="link-button" onClick={() => window.print()}>
            Print or save as PDF
          </button>
        </div>
      </header>
      {data.overview ? (
        <div className="week-overview">
          {paragraphs(data.overview).map((p, i) => (
            <p key={i} className="day-overview">{p}</p>
          ))}
        </div>
      ) : (
        <p className="status-note">No weekly overview yet: Sunday&apos;s scans write it.</p>
      )}
      <div className="sections">
        <BucketSection title="TOP" bucket="top" stories={data.sections.top} variant="lead"
          emptyMessage="Nothing reached TOP this week." now={now} />
        <BucketSection title="Relevant" bucket="relevant" stories={data.sections.relevant}
          emptyMessage="Nothing relevant this week." now={now} />
      </div>
    </article>
  );
}

export default function WeekPage({ now }: { now?: Date }) {
  const { week } = useParams();
  const weeksQuery = useWeeks();
  const thisWeek = currentWeek(now);
  if (week === undefined) {
    if (weeksQuery.isPending) return <Loading what="Loading weeks" />;
    const newest = weeksQuery.data?.[0]?.week ?? thisWeek;
    return <Navigate to={`/week/${newest}`} replace />;
  }
  let left;
  if (weeksQuery.isPending) left = <Loading what="Loading weeks" />;
  else if (weeksQuery.isError) left = <ErrorNote error={weeksQuery.error} />;
  else left = <WeekList items={entries(weeksQuery.data, thisWeek)} selected={week} />;
  return (
    <div className="page daily week">
      <aside className="daily-left week-left">{left}</aside>
      <div className="daily-right">
        {WEEK_KEY.test(week) ? (
          <WeekView key={week} week={week} now={now} />
        ) : (
          <p className="status-note" role="alert">Not a week: use the form 2026-W48.</p>
        )}
      </div>
    </div>
  );
}
