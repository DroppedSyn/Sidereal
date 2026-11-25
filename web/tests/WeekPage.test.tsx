import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { WeekDetail, WeekSummary } from '../src/api/types';
import WeekPage from '../src/pages/WeekPage';
import { makeSections, makeStory, mockFetch, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const NOW = new Date('2026-12-02T12:00:00Z'); // Wednesday of 2026-W49

const WEEKS: WeekSummary[] = [
  { week: '2026-W48', label: 'Week 48 · 23.11.2026 – 29.11.2026', start_day: '2026-11-23',
    end_day: '2026-11-29', headline: 'Entra week', story_count: 2, updated_at: '2026-11-29T20:00:00Z' },
  { week: '2026-W47', label: 'Week 47 · 16.11.2026 – 22.11.2026', start_day: '2026-11-16',
    end_day: '2026-11-22', headline: 'Quiet week', story_count: 1, updated_at: '2026-11-22T20:00:00Z' },
];

function detail(week: string, over: Partial<WeekDetail> = {}): WeekDetail {
  const sections = makeSections({
    top: [makeStory({ title: `Top of ${week}`, bucket: 'top', day: '2026-11-24' })],
    relevant: [makeStory({ title: `Relevant of ${week}`, day: '2026-11-25' })],
  });
  return { week, label: `Label ${week}`, start_day: '2026-11-23', end_day: '2026-11-29',
    overview: 'Azure paragraph.\n\nIdentity <b>paragraph</b>.', headline: `Headline ${week}`,
    updated_at: '2026-11-29T20:00:00Z', sections,
    counts: { top: 1, relevant: 1, side: 0, drop: 0 }, ...over };
}

const page = <WeekPage now={NOW} />;

describe('WeekPage', () => {
  it('opens the newest week with a digest, its overview as paragraphs and both sections', async () => {
    mockFetch({ '/api/weeks?limit=52': WEEKS, '/api/weeks/2026-W48': detail('2026-W48') });
    const { container } = renderWith(page, { route: '/week', path: '/week/:week?' });
    expect(await screen.findByRole('heading', { level: 2, name: 'Label 2026-W48' })).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/week/2026-W48');
    expect(screen.getByText('Headline 2026-W48')).toBeInTheDocument();
    expect(screen.getByText('Azure paragraph.')).toBeInTheDocument();
    // Overview text is rendered as text, never as HTML.
    expect(screen.getByText('Identity <b>paragraph</b>.')).toBeInTheDocument();
    expect(container.querySelector('.week-overview b')).toBeNull();
    expect(screen.getByRole('region', { name: 'TOP 1' })).toHaveTextContent('Top of 2026-W48');
    expect(screen.getByRole('region', { name: 'Relevant 1' })).toHaveTextContent('Relevant of 2026-W48');
    expect(screen.getByRole('link', { name: 'Export Markdown' })).toHaveAttribute(
      'href', '/api/weeks/2026-W48/export.md');
  });

  it('lists this week so far first and switches weeks', async () => {
    const fetch = mockFetch({
      '/api/weeks?limit=52': WEEKS,
      '/api/weeks/2026-W47': detail('2026-W47'),
      '/api/weeks/2026-W49': detail('2026-W49', { overview: null, headline: null, updated_at: null }),
    });
    renderWith(page, { route: '/week/2026-W47', path: '/week/:week?' });
    expect(await screen.findByText('Top of 2026-W47')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Weeks' });
    const links = Array.from(nav.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/week/2026-W49', '/week/2026-W48', '/week/2026-W47']);
    await userEvent.click(screen.getByRole('link', { name: /This week so far/ }));
    expect(await screen.findByText('Top of 2026-W49')).toBeInTheDocument();
    expect(screen.getByText(/No weekly overview yet/)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/week/2026-W49');
    expect(fetch.mock.calls.map((c) => c[0])).toContain('/api/weeks/2026-W47');
  });

  it('goes to this week when no digest exists yet', async () => {
    mockFetch({ '/api/weeks?limit=52': [], '/api/weeks/2026-W49': detail('2026-W49') });
    renderWith(page, { route: '/week', path: '/week/:week?' });
    expect(await screen.findByText('Top of 2026-W49')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/week/2026-W49');
  });

  it('refuses a malformed week without calling the API', async () => {
    const fetch = mockFetch({ '/api/weeks?limit=52': WEEKS });
    renderWith(page, { route: '/week/2026-48', path: '/week/:week?' });
    expect(await screen.findByRole('alert')).toHaveTextContent('Not a week');
    expect(fetch.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith('/api/weeks/'))).toEqual([]);
  });

  it('shows the API error for a week the server rejects', async () => {
    mockFetch({
      '/api/weeks?limit=52': WEEKS,
      '/api/weeks/2025-W53': new Response('{"detail":"week must be an ISO week like 2026-W48"}',
        { status: 422, headers: { 'Content-Type': 'application/json' } }),
    });
    renderWith(page, { route: '/week/2025-W53', path: '/week/:week?' });
    expect(await screen.findByRole('alert')).toHaveTextContent('week must be an ISO week');
  });

  it('prints through the browser', async () => {
    mockFetch({ '/api/weeks?limit=52': WEEKS, '/api/weeks/2026-W48': detail('2026-W48') });
    const print = vi.fn();
    vi.stubGlobal('print', print);
    renderWith(page, { route: '/week/2026-W48', path: '/week/:week?' });
    await userEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }));
    expect(print).toHaveBeenCalledOnce();
  });

  it('hides a story from the week at once', async () => {
    const week = detail('2026-W48');
    let hidden = false;
    const fetch = mockFetch({
      '/api/weeks?limit=52': WEEKS,
      '/api/weeks/2026-W48': () => (hidden ? detail('2026-W48', {
        sections: { ...week.sections, top: [] }, counts: { ...week.counts, top: 0 } }) : week),
      '/api/stories/': (url: URL) => {
        hidden = true;
        return { story_id: Number(url.pathname.split('/')[3]), vote: null, read: false, hidden: true };
      },
    });
    renderWith(page, { route: '/week/2026-W48', path: '/week/:week?' });
    const top = await screen.findByRole('region', { name: 'TOP 1' });
    await userEvent.click(within(top).getByRole('button', { name: 'Hide' }));
    expect(await screen.findByRole('region', { name: 'TOP 0' })).toBeInTheDocument();
    expect(fetch.mock.calls.map((c) => String(c[0]))).toContain(
      `/api/stories/${week.sections.top[0]?.id}/hidden`);
  });
});
