import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import GazettePage from '../src/pages/GazettePage';
import { NOW, makeGazette, makeSections, makeStory, mockFetch, never, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

describe('GazettePage', () => {
  it('shows a loading state', () => {
    mockFetch({ '/api/gazette': () => never() });
    renderWith(<GazettePage now={NOW} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the gazette');
  });

  it('shows an error with a retry', async () => {
    const fetch = mockFetch({ '/api/gazette': new Response('{"detail":"database not initialised"}', { status: 503 }) });
    renderWith(<GazettePage now={NOW} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('database not initialised');
    fetch.mockClear();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(fetch).toHaveBeenCalled();
  });

  it('renders the three sections from /api/gazette', async () => {
    const fetch = mockFetch({
      '/api/gazette': makeGazette(
        makeSections({
          top: [makeStory({ title: 'Exploited Entra flaw', bucket: 'top' })],
          relevant: [makeStory({ title: 'vWAN routing intent' })],
          side: [makeStory({ title: 'Egress pricing', bucket: 'side' })],
        }),
      ),
    });
    renderWith(<GazettePage now={NOW} />);
    expect(await screen.findByRole('link', { name: 'Exploited Entra flaw' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'TOP 1' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Relevant 1' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'On the side 1' })).toBeInTheDocument();
    expect(screen.getByText(/Last 24 hours · 14\.07\.2026 · updated 15:30/)).toBeInTheDocument();
    expect(fetch.mock.calls[0]![0]).toBe('/api/gazette');
  });

  it('shows the calm message for an empty window', async () => {
    mockFetch({ '/api/gazette': makeGazette(makeSections()) });
    renderWith(<GazettePage now={NOW} />);
    expect(await screen.findByText('Nothing needs your attention right now.')).toBeInTheDocument();
  });

  it('"Show N dropped" refetches with include_drop=true', async () => {
    const fetch = mockFetch({
      '/api/gazette?include_drop=true': makeGazette(
        makeSections({ drop: [makeStory({ title: 'Show HN thing', bucket: 'drop' })] }),
      ),
      '/api/gazette': makeGazette(makeSections(), 1),
    });
    renderWith(<GazettePage now={NOW} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Show 1 dropped' }));
    expect(await screen.findByText('Show HN thing')).toBeInTheDocument();
    expect(fetch.mock.calls.map((c) => c[0])).toEqual(['/api/gazette', '/api/gazette?include_drop=true']);
  });
});
