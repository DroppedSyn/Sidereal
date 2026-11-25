// Shared test helpers: providers, a routing fetch mock and story/data builders.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { vi } from 'vitest';
import { ROUTER_FUTURE } from '../src/routes';
import type { Counts, Gazette, Sections, Story } from '../src/api/types';

export const NOW = new Date('2026-07-14T14:30:00Z');

type Reply = unknown | Response | ((url: URL, init?: RequestInit) => unknown | Response);

/** Mock fetch: the first route whose key is a prefix of `pathname?search` answers. */
export function mockFetch(routes: Record<string, Reply>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const target = url.pathname + url.search;
    const keys = Object.keys(routes).sort((a, b) => b.length - a.length);
    const key = keys.find((k) => target === k || target.startsWith(k));
    if (key === undefined) return new Response('{"detail":"not mocked"}', { status: 404 });
    let reply = routes[key];
    if (typeof reply === 'function') reply = (reply as (u: URL, i?: RequestInit) => unknown)(url, init);
    if (reply instanceof Response) return reply;
    if (reply instanceof Promise) return reply as Promise<Response>;
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

export function never(): Promise<Response> {
  return new Promise<Response>(() => undefined);
}

function LocationProbe() {
  const loc = useLocation();
  return (
    <>
      <div data-testid="location">{loc.pathname}</div>
      <div data-testid="search">{loc.search}</div>
    </>
  );
}

export function renderWith(ui: ReactElement, { route = '/', path }: { route?: string; path?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]} future={ROUTER_FUTURE}>
        {path ? (
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        ) : (
          ui
        )}
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Render inside a fresh QueryClientProvider only (no router): for components that use
 * mutations (story cards) but never navigate. */
export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(ui, { wrapper });
}

let nextId = 1;

export function makeStory(over: Partial<Story> = {}): Story {
  const id = over.id ?? nextId++;
  return {
    id,
    title: `Story ${id}`,
    day: '2026-07-14',
    first_seen_at: '2026-07-14T12:30:00Z',
    published_at: '2026-07-14T11:30:00Z',
    bucket: 'relevant',
    score: 61.4,
    summary: `Summary of story ${id}.`,
    why: `Why story ${id} matters.`,
    tags: ['azure'],
    focus: 'azure-networking',
    flags: {},
    sources: [{ key: 'bleepingcomputer', name: 'BleepingComputer', url: `https://bc.example/${id}` }],
    lead_url: `https://bc.example/${id}`,
    excerpt: `Original excerpt ${id}.`,
    read: false,
    vote: null,
    hidden: false,
    ...over,
  };
}

export function makeSections(over: Partial<Sections> = {}): Sections {
  return { top: [], relevant: [], side: [], drop: [], ...over };
}

export function countsOf(s: Sections, drop?: number): Counts {
  return { top: s.top.length, relevant: s.relevant.length, side: s.side.length, drop: drop ?? s.drop.length };
}

export function makeGazette(sections: Sections, drop?: number): Gazette {
  return {
    generated_at: '2026-07-14T14:30:00Z',
    window_start: '2026-07-13T14:30:00Z',
    sections,
    counts: countsOf(sections, drop),
  };
}
