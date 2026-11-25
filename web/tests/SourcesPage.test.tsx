import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SourceStatus } from '../src/api/types';
import SourcesPage from '../src/pages/SourcesPage';
import { mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

function source(over: Partial<SourceStatus>): SourceStatus {
  return { id: 1, key: 'k', name: 'Name', kind: 'rss', url: 'https://feed.example/rss', enabled: true,
    weight: 1, health: 'ok', last_fetch_at: null, last_ok_at: '2026-07-14T11:00:00Z', last_error: null,
    consecutive_failures: 0, last_item_at: null, items_7d: 42, ...over };
}

describe('SourcesPage', () => {
  it('shows health as a text badge, last ok, items and the last error', async () => {
    mockFetch({
      '/api/sources': [
        source({ id: 1, name: 'MSRC' }),
        source({ id: 2, name: 'Broken feed', health: 'broken', last_ok_at: null, items_7d: 0,
          last_error: 'broken: HTML instead of a feed', url: 'javascript:alert(1)', enabled: false }),
      ],
    });
    renderWith(<SourcesPage />);
    expect(await screen.findByRole('link', { name: 'MSRC' })).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('ok')).toHaveClass('health-ok');
    expect(screen.getByText('broken')).toHaveClass('health-broken');
    expect(screen.getByText('14.07.2026 12:00')).toBeInTheDocument();
    expect(screen.getByText('never')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('broken: HTML instead of a feed')).toBeInTheDocument();
    expect(screen.getByText('Broken feed').closest('a')).toBeNull();
    expect(screen.getByText(/disabled/)).toBeInTheDocument();
  });

  it('shows loading and error states', async () => {
    mockFetch({ '/api/sources': () => never() });
    const first = renderWith(<SourcesPage />);
    expect(screen.getByText('Loading sources…')).toBeInTheDocument();
    first.unmount();
    mockFetch({ '/api/mutes': [], '/api/sources': new Response('{"detail":"database not initialised (run sidereal init)"}', { status: 503 }) });
    renderWith(<SourcesPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('database not initialised');
  });
});
