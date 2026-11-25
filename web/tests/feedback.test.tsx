import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyChange, editView } from '../src/api/feedback';
import GazettePage from '../src/pages/GazettePage';
import { NOW, makeGazette, makeSections, makeStory, mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

function writes(fetch: ReturnType<typeof mockFetch>) {
  return fetch.mock.calls
    .filter(([, init]) => init?.method && init.method !== 'GET')
    .map(([url, init]) => ({
      url: String(url),
      method: init?.method,
      headers: init?.headers as Record<string, string>,
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)) as unknown,
    }));
}

function gazette() {
  return makeGazette(makeSections({
    top: [makeStory({ id: 1, title: 'Entra flaw', bucket: 'top' })],
    relevant: [makeStory({ id: 2, title: 'vWAN routing' })],
  }));
}

function card(title: string) {
  return screen.getByRole('link', { name: title }).closest('article') as HTMLElement;
}

describe('editView / applyChange', () => {
  it('patches matching stories and removes hidden ones with their count', () => {
    const g = gazette();
    const voted = editView(g, (s) => s.id === 2, (s) => applyChange(s, { vote: 'up' }));
    expect(voted.sections.relevant[0]?.vote).toBe('up');
    expect(voted.sections.top[0]?.vote).toBeNull();
    expect(g.sections.relevant[0]?.vote).toBeNull(); // input untouched
    const hidden = editView(g, (s) => s.id === 1, (s) => applyChange(s, { hidden: true }));
    expect(hidden.sections.top).toEqual([]);
    expect(hidden.counts.top).toBe(0);
    expect(hidden.counts.relevant).toBe(1);
  });
});

describe('story feedback controls', () => {
  it('votes optimistically and sends X-Sidereal: 1 with the vote body', async () => {
    const fetch = mockFetch({ '/api/gazette': gazette(), '/api/stories/2/vote': () => never() });
    renderWith(<GazettePage now={NOW} />);
    await screen.findByRole('link', { name: 'vWAN routing' });
    const up = within(card('vWAN routing')).getByRole('button', { name: 'More like this' });
    expect(up).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(up);
    expect(up).toHaveAttribute('aria-pressed', 'true'); // before the server answered
    expect(writes(fetch)).toEqual([{
      url: '/api/stories/2/vote', method: 'PUT',
      headers: expect.objectContaining({ 'X-Sidereal': '1', 'Content-Type': 'application/json' }) as unknown,
      body: { vote: 'up' },
    }]);
  });

  it.each([['up', 'More like this'], ['down', 'Less like this']] as const)(
    'clears a %s vote when the pressed button is clicked again', async (vote, name) => {
      const g = makeGazette(makeSections({ top: [makeStory({ id: 1, title: 'Voted', bucket: 'top', vote })] }));
      const fetch = mockFetch({ '/api/gazette': g, '/api/stories/1/vote': () => never() });
      renderWith(<GazettePage now={NOW} />);
      await screen.findByRole('link', { name: 'Voted' });
      const button = screen.getByRole('button', { name });
      expect(button).toHaveAttribute('aria-pressed', 'true');
      await userEvent.click(button);
      expect(writes(fetch)[0]?.body).toEqual({ vote: null });
      expect(button).toHaveAttribute('aria-pressed', 'false');
    });

  it('hides a story at once and lowers the section count', async () => {
    const fetch = mockFetch({ '/api/gazette': gazette(), '/api/stories/1/hidden': () => never() });
    renderWith(<GazettePage now={NOW} />);
    await screen.findByRole('link', { name: 'Entra flaw' });
    await userEvent.click(within(card('Entra flaw')).getByRole('button', { name: 'Hide' }));
    expect(screen.queryByRole('link', { name: 'Entra flaw' })).toBeNull();
    expect(screen.getByRole('region', { name: 'TOP 0' })).toBeInTheDocument();
    expect(writes(fetch)[0]).toMatchObject({ url: '/api/stories/1/hidden', method: 'PUT', body: { hidden: true } });
  });

  it('rolls back and shows an error when the write fails', async () => {
    let calls = 0;
    mockFetch({
      // the refetch after the failure never answers: only the rollback can bring the story back
      '/api/gazette': () => (calls++ === 0 ? gazette() : never()),
      '/api/stories/1/hidden': new Response('{"detail":"story not found"}', { status: 404 }),
    });
    renderWith(<GazettePage now={NOW} />);
    await screen.findByRole('link', { name: 'Entra flaw' });
    await userEvent.click(within(card('Entra flaw')).getByRole('button', { name: 'Hide' }));
    expect(await screen.findByRole('link', { name: 'Entra flaw' })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save: story not found');
  });

  it('marks read and unread; unread titles are bold (story-unread)', async () => {
    const fetch = mockFetch({ '/api/gazette': gazette(), '/api/stories/2/read': () => never() });
    renderWith(<GazettePage now={NOW} />);
    await screen.findByRole('link', { name: 'vWAN routing' });
    expect(card('vWAN routing')).toHaveClass('story-unread');
    await userEvent.click(within(card('vWAN routing')).getByRole('button', { name: 'Mark read' }));
    expect(card('vWAN routing')).toHaveClass('story-read');
    expect(within(card('vWAN routing')).getByRole('button', { name: 'Mark unread' })).toBeInTheDocument();
    expect(writes(fetch)[0]).toMatchObject({ url: '/api/stories/2/read', body: { read: true } });
  });

  it('opening the article marks the story read', async () => {
    const fetch = mockFetch({ '/api/gazette': gazette(), '/api/stories/1/read': () => never() });
    renderWith(<GazettePage now={NOW} />);
    const link = await screen.findByRole('link', { name: 'Entra flaw' });
    link.addEventListener('click', (e) => e.preventDefault());
    await userEvent.click(link);
    await waitFor(() => expect(writes(fetch)[0]).toMatchObject({ url: '/api/stories/1/read', body: { read: true } }));
  });
});
