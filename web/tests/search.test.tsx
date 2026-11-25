import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import Highlighted from '../src/components/Highlighted';
import { splitHighlights } from '../src/lib/highlight';
import SearchPage from '../src/pages/SearchPage';
import type { SearchResults } from '../src/api/types';
import { NOW, makeGazette, makeSections, makeStory, mockFetch, never, renderWith, renderWithClient } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const S = '\u0002';
const E = '\u0003';

function page(results: SearchResults['results'], next_before: number | null = null, query = 'entra'): SearchResults {
  return { query, results, next_before };
}

describe('splitHighlights', () => {
  it('splits on the markers', () => {
    expect(splitHighlights(`a ${S}Entra${E} flaw ${S}x${E}`)).toEqual([
      { text: 'a ', hit: false },
      { text: 'Entra', hit: true },
      { text: ' flaw ', hit: false },
      { text: 'x', hit: true },
    ]);
  });

  it('handles no markers, empty input and stray markers', () => {
    expect(splitHighlights('plain')).toEqual([{ text: 'plain', hit: false }]);
    expect(splitHighlights('')).toEqual([]);
    expect(splitHighlights(`${E}a${S}${S}b`)).toEqual([
      { text: 'a', hit: false },
      { text: 'b', hit: true },
    ]);
  });
});

describe('Highlighted', () => {
  it('renders markup in a snippet as text, matches in <mark>', () => {
    const { container } = renderWithClient(
      <Highlighted snippet={`<img src=x onerror=alert(1)> ${S}<b>entra</b>${E} &amp; more`} />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    const marks = container.querySelectorAll('mark');
    expect(marks).toHaveLength(1);
    expect(marks[0]!.textContent).toBe('<b>entra</b>');
    expect(container.textContent).toBe('<img src=x onerror=alert(1)> <b>entra</b> &amp; more');
  });
});

describe('SearchPage', () => {
  it('asks for a query when there is none and does not fetch', () => {
    const fetch = mockFetch({});
    renderWith(<SearchPage now={NOW} />, { route: '/search', path: '/search' });
    expect(screen.getByText(/Type a word or two/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('shows a loading state', () => {
    mockFetch({ '/api/search': () => never() });
    renderWith(<SearchPage now={NOW} />, { route: '/search?q=entra', path: '/search' });
    expect(screen.getByRole('status')).toHaveTextContent('Searching');
  });

  it('renders results with snippets and story cards', async () => {
    const fetch = mockFetch({
      '/api/search': page([
        { story: makeStory({ id: 7, title: 'Exploited Entra flaw' }), rank: -3.2, snippet: `the ${S}Entra${E} flaw` },
      ]),
    });
    renderWith(<SearchPage now={NOW} />, { route: '/search?q=entra%20flaw', path: '/search' });
    expect(await screen.findByRole('link', { name: 'Exploited Entra flaw' })).toBeInTheDocument();
    expect(screen.getByText('Entra', { selector: 'mark' })).toBeInTheDocument();
    expect(screen.getByText(/Results for “entra flaw”/)).toBeInTheDocument();
    const url = new URL(String(fetch.mock.calls[0]![0]), 'http://localhost');
    expect(url.pathname).toBe('/api/search');
    expect(url.searchParams.get('q')).toBe('entra flaw');
    expect(url.searchParams.get('limit')).toBe('20');
    expect(url.searchParams.has('before')).toBe(false);
  });

  it('says so when nothing matches', async () => {
    mockFetch({ '/api/search': page([]) });
    renderWith(<SearchPage now={NOW} />, { route: '/search?q=zzz', path: '/search' });
    expect(await screen.findByText('No stories match.')).toBeInTheDocument();
  });

  it('shows an API error', async () => {
    mockFetch({ '/api/search': new Response('{"detail":"invalid search query"}', { status: 400 }) });
    renderWith(<SearchPage now={NOW} />, { route: '/search?q=x', path: '/search' });
    expect(await screen.findByRole('alert')).toHaveTextContent('invalid search query');
  });

  it('loads more with before = next_before', async () => {
    const fetch = mockFetch({
      '/api/search': (url: URL) =>
        url.searchParams.get('before') === '5'
          ? page([{ story: makeStory({ id: 4, title: 'Older' }), rank: -1, snippet: 'older' }])
          : page([{ story: makeStory({ id: 5, title: 'Newer' }), rank: -1, snippet: 'newer' }], 5),
    });
    renderWith(<SearchPage now={NOW} />, { route: '/search?q=entra', path: '/search' });
    await userEvent.click(await screen.findByRole('button', { name: 'Load more results' }));
    expect(await screen.findByRole('link', { name: 'Older' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Newer' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more results' })).toBeNull();
    const last = new URL(String(fetch.mock.calls.at(-1)![0]), 'http://localhost');
    expect(last.searchParams.get('before')).toBe('5');
  });
});

describe('header search box', () => {
  it('submits to /search?q=… and shows the results', async () => {
    mockFetch({
      '/api/gazette': makeGazette(makeSections()),
      '/api/runs': [],
      '/api/search': page([{ story: makeStory({ title: 'Found it' }), rank: -1, snippet: 'x' }]),
    });
    renderWith(<App />);
    const box = screen.getByRole('searchbox', { name: 'Search stories' });
    await userEvent.type(box, '  entra flaw {Enter}');
    expect(screen.getByTestId('location')).toHaveTextContent('/search');
    expect(screen.getByTestId('search')).toHaveTextContent('?q=entra+flaw');
    expect(await screen.findByRole('link', { name: 'Found it' })).toBeInTheDocument();
    expect(box).toHaveValue('entra flaw');
  });

  it('ignores an empty submit', async () => {
    mockFetch({ '/api/gazette': makeGazette(makeSections()), '/api/runs': [] });
    renderWith(<App />);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search stories' }), '   {Enter}');
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/);
  });
});
