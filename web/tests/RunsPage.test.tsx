import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Run } from '../src/api/types';
import RunsPage from '../src/pages/RunsPage';
import { mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const RUNS: Run[] = [
  { id: 2, started_at: '2026-07-14T11:00:00Z', finished_at: '2026-07-14T11:05:00Z', trigger: 'timer',
    status: 'ok', duration_s: 305, error: null,
    stats: { items: { new: 12 }, stories: { new: 5 }, assess: { ok: 4, failed: 0 }, sources: { failed: 0 } } },
  { id: 1, started_at: '2026-07-14T07:00:00Z', finished_at: '2026-07-14T07:01:00Z', trigger: 'manual',
    status: 'failed', duration_s: 60, error: 'ollama down', stats: { gate: 'idle' } },
];

describe('RunsPage', () => {
  it('lists runs with status, duration and a summary', async () => {
    const fetch = mockFetch({ '/api/runs?limit=50': RUNS });
    renderWith(<RunsPage />);
    expect(await screen.findByText('14.07.2026 12:00')).toBeInTheDocument();
    expect(screen.getByText('5 min 5 s')).toBeInTheDocument();
    expect(screen.getByText('12 new items · 5 new stories · 4 assessed')).toBeInTheDocument();
    expect(screen.getByText('failed')).toHaveClass('status-failed');
    expect(screen.getByText('ollama down')).toBeInTheDocument();
    expect(fetch.mock.calls[0]![0]).toBe('/api/runs?limit=50');
  });

  it('expands a row to the full stats as text', async () => {
    mockFetch({ '/api/runs?limit=50': RUNS });
    renderWith(<RunsPage />);
    const toggle = await screen.findByRole('button', { name: '14.07.2026 08:00' });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/"gate": "idle"/)).toBeInTheDocument();
    expect(screen.getByText('Error: ollama down')).toBeInTheDocument();
  });

  it('starts a run with POST and X-Sidereal: 1', async () => {
    const fetch = mockFetch({
      '/api/runs?limit=50': RUNS,
      '/api/runs': (_u: URL, init?: RequestInit) =>
        init?.method === 'POST' ? { status: 'started', unit: 'sidereal-run-manual.service' } : RUNS,
    });
    renderWith(<RunsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run now' }));
    expect(await screen.findByText('Scan started.')).toBeInTheDocument();
    const post = fetch.mock.calls.find((c) => c[1]?.method === 'POST')!;
    expect(post[0]).toBe('/api/runs');
    expect((post[1]!.headers as Record<string, string>)['X-Sidereal']).toBe('1');
  });

  it('explains a 409 while a run is in progress', async () => {
    mockFetch({
      '/api/runs?limit=50': RUNS,
      '/api/runs': (_u: URL, init?: RequestInit) =>
        init?.method === 'POST' ? new Response('{"detail":"a run is already in progress"}', { status: 409 }) : RUNS,
    });
    renderWith(<RunsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run now' }));
    expect(await screen.findByText('A scan is already running.')).toBeInTheDocument();
  });

  it('shows loading, empty and error states', async () => {
    mockFetch({ '/api/runs?limit=50': () => never() });
    const first = renderWith(<RunsPage />);
    expect(screen.getByText('Loading runs…')).toBeInTheDocument();
    first.unmount();
    mockFetch({ '/api/runs?limit=50': [] });
    const second = renderWith(<RunsPage />);
    expect(await screen.findByText('No scans yet.')).toBeInTheDocument();
    second.unmount();
    mockFetch({ '/api/runs?limit=50': new Response('x', { status: 500 }) });
    renderWith(<RunsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 500');
  });
});
