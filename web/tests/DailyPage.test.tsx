import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DayDetail, DaySummary } from '../src/api/types';
import DailyPage from '../src/pages/DailyPage';
import { countsOf, makeSections, makeStory, mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const DAYS: DaySummary[] = [
  { day: '2026-07-14', label: 'Tuesday - 14.07.2026', counts: { top: 1, relevant: 0, side: 0 }, run_count: 4, headline: null },
  { day: '2026-07-12', label: 'Sunday - 12.07.2026', counts: { top: 0, relevant: 1, side: 0 }, run_count: 6, headline: 'Quiet Sunday' },
];

function detail(day: string, label: string, title: string, over: Partial<DayDetail> = {}): DayDetail {
  const sections = makeSections({ relevant: [makeStory({ title, day })] });
  return { day, label, overview: `Overview of ${day}.`, headline: `Headline ${day}`, sections,
    counts: countsOf(sections), runs: [
      { id: 1, started_at: `${day}T00:00:00Z`, finished_at: null, trigger: 'timer', status: 'ok' },
    ], ...over };
}

const page = <DailyPage />;

describe('DailyPage', () => {
  it('selects the newest day by default and replaces the URL', async () => {
    mockFetch({
      '/api/days?limit=60': DAYS,
      '/api/days/2026-07-14': detail('2026-07-14', 'Tuesday - 14.07.2026', 'Tuesday story'),
    });
    renderWith(page, { route: '/daily', path: '/daily/:day?' });
    expect(await screen.findByRole('heading', { level: 2, name: 'Tuesday - 14.07.2026' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/daily/2026-07-14');
    expect(screen.getByText('Headline 2026-07-14')).toBeInTheDocument();
    expect(screen.getByText('Overview of 2026-07-14.')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Scans this day' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'TOP 0' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Relevant 1' })).toHaveTextContent('Tuesday story');
    expect(screen.getByRole('region', { name: 'On the side 0' })).toBeInTheDocument();
  });

  it('deep-links to a day and switches days from the list', async () => {
    const fetch = mockFetch({
      '/api/days?limit=60': DAYS,
      '/api/days/2026-07-12': detail('2026-07-12', 'Sunday - 12.07.2026', 'Sunday story'),
      '/api/days/2026-07-14': detail('2026-07-14', 'Tuesday - 14.07.2026', 'Tuesday story', { overview: null, headline: null }),
    });
    renderWith(page, { route: '/daily/2026-07-12', path: '/daily/:day?' });
    expect(await screen.findByText('Sunday story')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: /Tuesday - 14\.07\.2026/ }));
    expect(await screen.findByText('Tuesday story')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/daily/2026-07-14');
    expect(screen.queryByText(/Overview of/)).toBeNull();
    expect(fetch.mock.calls.map((c) => c[0])).toContain('/api/days/2026-07-12');
  });

  it('shows an empty state when there are no days', async () => {
    mockFetch({ '/api/days?limit=60': [] });
    renderWith(page, { route: '/daily', path: '/daily/:day?' });
    expect(await screen.findByText(/No days yet/)).toBeInTheDocument();
  });

  it('shows loading and error states for the day', async () => {
    mockFetch({ '/api/days?limit=60': DAYS, '/api/days/2026-07-12': () => never() });
    const { unmount } = renderWith(page, { route: '/daily/2026-07-12', path: '/daily/:day?' });
    expect(await screen.findByText('Loading the day…')).toBeInTheDocument();
    unmount();
    mockFetch({ '/api/days?limit=60': DAYS,
      '/api/days/2026-07-12': new Response('{"detail":"day must be a YYYY-MM-DD date"}', { status: 422 }) });
    renderWith(page, { route: '/daily/2026-07-12', path: '/daily/:day?' });
    expect(await screen.findByRole('alert')).toHaveTextContent('day must be a YYYY-MM-DD date');
  });

  it('pages older days with the before cursor', async () => {
    const full = Array.from({ length: 60 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 6, 14 - i)).toISOString().slice(0, 10);
      return { day: d, label: d, counts: { top: 0, relevant: 0, side: 0 }, run_count: 0, headline: null };
    });
    const fetch = mockFetch({
      '/api/days?limit=60&before=2026-05-16': [{ ...DAYS[1]!, day: '2026-05-15', label: 'Friday - 15.05.2026' }],
      '/api/days?limit=60': full,
      '/api/days/2026-07-14': detail('2026-07-14', 'x', 'y'),
    });
    renderWith(page, { route: '/daily/2026-07-14', path: '/daily/:day?' });
    await userEvent.click((await screen.findAllByRole('button', { name: 'Load older days' }))[0]!);
    expect(await screen.findByRole('link', { name: /Friday - 15\.05\.2026/ })).toBeInTheDocument();
    expect(fetch.mock.calls.map((c) => c[0])).toContain('/api/days?limit=60&before=2026-05-16');
  });
});
