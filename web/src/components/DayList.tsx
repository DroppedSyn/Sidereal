// Daily's left pane (plan §10.2): a list of days on wide screens, a dropdown under 720 px.
import { NavLink, useNavigate } from 'react-router-dom';
import type { DaySummary } from '../api/types';

interface Props {
  days: DaySummary[];
  selected: string | undefined;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

function countsText(d: DaySummary): string {
  return `${d.counts.top} top · ${d.counts.relevant} relevant · ${d.counts.side} side`;
}

export default function DayList({ days, selected, hasMore, loadingMore, onLoadMore }: Props) {
  const navigate = useNavigate();
  const more = hasMore ? (
    <button type="button" className="link-button daylist-more" disabled={loadingMore}
      onClick={onLoadMore}>
      {loadingMore ? 'Loading…' : 'Load older days'}
    </button>
  ) : null;
  return (
    <div className="daylist">
      <label className="dayselect">
        <span className="sr-only">Day</span>
        <select value={selected ?? ''}
          onChange={(e) => navigate(`/daily/${encodeURIComponent(e.target.value)}`)}>
          {selected === undefined ? <option value="">Choose a day</option> : null}
          {days.map((d) => (
            <option key={d.day} value={d.day}>
              {d.label} ({countsText(d)})
            </option>
          ))}
        </select>
      </label>
      <nav className="daylist-pane" aria-label="Days">
        <ol>
          {days.map((d) => (
            <li key={d.day}>
              <NavLink to={`/daily/${encodeURIComponent(d.day)}`} className="day-row">
                <span className="day-label">{d.label}</span>
                <span className="day-counts">{countsText(d)}</span>
              </NavLink>
            </li>
          ))}
        </ol>
        {more}
      </nav>
      <div className="dayselect">{more}</div>
    </div>
  );
}
