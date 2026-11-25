import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { makeGazette, makeSections, mockFetch, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

describe('App shell', () => {
  it('renders the masthead, the four tabs and the gazette at /', async () => {
    mockFetch({ '/api/gazette': makeGazette(makeSections()), '/api/runs': [], '/api/sources': [] });
    renderWith(<App />);
    expect(screen.getByRole('heading', { level: 1, name: 'Sidereal' })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)).toEqual([
      'Gazette', 'Daily', 'Runs', 'Sources',
    ]);
    expect(screen.getByRole('link', { name: 'Gazette' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('heading', { name: 'The Gazette' })).toBeInTheDocument();
  });

  it('switches tabs through the router', async () => {
    mockFetch({ '/api/gazette': makeGazette(makeSections()), '/api/runs': [], '/api/sources': [] });
    renderWith(<App />);
    await userEvent.click(screen.getByRole('link', { name: 'Sources' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/sources');
    expect(await screen.findByText('No sources configured.')).toBeInTheDocument();
  });

  it('shows a not-found page for unknown paths', () => {
    mockFetch({ '/api/runs': [] });
    renderWith(<App />, { route: '/nope' });
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});
