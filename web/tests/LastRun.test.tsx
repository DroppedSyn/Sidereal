import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LastRun from '../src/components/LastRun';
import { NOW, mockFetch, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

function run(status: string) {
  return [{ id: 7, started_at: '2026-07-14T12:02:00Z', finished_at: null, trigger: 'timer', status,
    duration_s: 60, stats: {}, error: null }];
}

describe('LastRun', () => {
  it('shows the last scan time and the next timer slot', async () => {
    const fetch = mockFetch({ '/api/runs?limit=1': run('ok') });
    renderWith(<LastRun now={NOW} />);
    expect(await screen.findByText('Last scan 13:02 · next ~16:00')).not.toHaveClass('last-run-failed');
    expect(fetch.mock.calls[0]![0]).toBe('/api/runs?limit=1');
  });

  it('marks a failed last scan in colour and in text', async () => {
    mockFetch({ '/api/runs?limit=1': run('failed') });
    renderWith(<LastRun now={NOW} />);
    expect(await screen.findByText('Last scan 13:02 failed · next ~16:00')).toHaveClass('last-run-failed');
  });

  it('shows a running scan and the no-scan state', async () => {
    mockFetch({ '/api/runs?limit=1': run('running') });
    const { unmount } = renderWith(<LastRun now={NOW} />);
    expect(await screen.findByText('Scan running since 13:02')).toBeInTheDocument();
    unmount();
    mockFetch({ '/api/runs?limit=1': [] });
    renderWith(<LastRun now={NOW} />);
    expect(await screen.findByText('No scans yet · next ~16:00')).toBeInTheDocument();
  });

  it('says when the status is unavailable', async () => {
    mockFetch({ '/api/runs?limit=1': new Response('x', { status: 500 }) });
    renderWith(<LastRun now={NOW} />);
    expect(await screen.findByText('Scan status unavailable')).toBeInTheDocument();
  });
});
