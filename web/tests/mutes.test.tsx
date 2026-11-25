import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DayDetail, Mute } from '../src/api/types';
import MutesList from '../src/components/MutesList';
import StoryCard from '../src/components/StoryCard';
import DailyPage from '../src/pages/DailyPage';
import { countsOf, makeSections, makeStory, mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

function posted(fetch: ReturnType<typeof mockFetch>) {
  return fetch.mock.calls
    .filter(([, init]) => init?.method === 'POST' || init?.method === 'DELETE')
    .map(([url, init]) => ({
      url: String(url), method: init?.method,
      sidereal: (init?.headers as Record<string, string>)['X-Sidereal'],
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)) as unknown,
    }));
}

const MUTE: Mute = { id: 7, kind: 'source', value: 'hackernews', created_at: '2026-07-14T08:00:00Z' };

describe('MuteMenu on a story card', () => {
  it('mutes one of the story sources', async () => {
    const fetch = mockFetch({ '/api/mutes': MUTE });
    renderWith(<StoryCard story={makeStory({
      sources: [{ key: 'hackernews', name: 'Hacker News', url: null }] })} />);
    await userEvent.click(screen.getByRole('button', { name: 'Mute…' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mute source Hacker News' }));
    expect(await screen.findByText(/Muted source “hackernews” from the next scan/)).toBeInTheDocument();
    expect(posted(fetch)).toEqual([{ url: '/api/mutes', method: 'POST', sidereal: '1',
      body: { kind: 'source', value: 'hackernews' } }]);
  });

  it('mutes a typed keyword (trimmed) and clears the field', async () => {
    const fetch = mockFetch({ '/api/mutes': { ...MUTE, kind: 'keyword', value: 'bitcoin' } });
    renderWith(<StoryCard story={makeStory()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Mute…' }));
    const submit = screen.getByRole('button', { name: 'Mute keyword' });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Keyword'), '  Bitcoin ');
    await userEvent.click(submit);
    expect(await screen.findByText(/Muted keyword “bitcoin”/)).toBeInTheDocument();
    expect(posted(fetch)[0]?.body).toEqual({ kind: 'keyword', value: 'Bitcoin' });
    expect(screen.getByLabelText('Keyword')).toHaveValue('');
  });

  it('shows the API error', async () => {
    mockFetch({ '/api/mutes': new Response('{"detail":"unknown source"}', { status: 422 }) });
    renderWith(<StoryCard story={makeStory()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Mute…' }));
    await userEvent.click(screen.getByRole('button', { name: 'Mute source BleepingComputer' }));
    expect(await screen.findByText('Could not mute: unknown source')).toBeInTheDocument();
  });
});

describe('MutesList', () => {
  it('lists mutes and unmutes optimistically with X-Sidereal', async () => {
    const fetch = mockFetch({
      '/api/mutes/7': () => never(),
      '/api/mutes': [MUTE, { id: 8, kind: 'keyword', value: 'crypto', created_at: MUTE.created_at }],
    });
    renderWith(<MutesList />);
    expect(await screen.findByText('hackernews')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unmute source hackernews' }));
    expect(screen.queryByText('hackernews')).toBeNull();
    expect(screen.getByText('crypto')).toBeInTheDocument();
    expect(posted(fetch)).toEqual([{ url: '/api/mutes/7', method: 'DELETE', sidereal: '1', body: undefined }]);
  });

  it('says when nothing is muted', async () => {
    mockFetch({ '/api/mutes': [] });
    renderWith(<MutesList />);
    expect(await screen.findByText('Nothing muted.')).toBeInTheDocument();
  });
});

describe('Mark day read', () => {
  it('marks the day read optimistically and posts to the day', async () => {
    const sections = makeSections({ relevant: [makeStory({ title: 'Unread one', day: '2026-07-14' })] });
    const detail: DayDetail = { day: '2026-07-14', label: 'Tuesday - 14.07.2026', overview: null,
      headline: null, sections, counts: countsOf(sections), runs: [] };
    const fetch = mockFetch({
      '/api/days?limit=60': [],
      '/api/days/2026-07-14/read': () => never(),
      '/api/days/2026-07-14': detail,
    });
    renderWith(<DailyPage />, { route: '/daily/2026-07-14', path: '/daily/:day' });
    const link = await screen.findByRole('link', { name: 'Unread one' });
    const article = link.closest('article') as HTMLElement;
    expect(article).toHaveClass('story-unread');
    await userEvent.click(screen.getByRole('button', { name: 'Mark day read' }));
    expect(article).toHaveClass('story-read');
    expect(within(article).getByRole('button', { name: 'Mark unread' })).toBeInTheDocument();
    expect(posted(fetch)).toEqual([{ url: '/api/days/2026-07-14/read', method: 'POST', sidereal: '1', body: undefined }]);
  });
});
