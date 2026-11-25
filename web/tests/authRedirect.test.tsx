import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { ApiError, apiPost, setUnauthorizedHandler } from '../src/api/client';
import { mockFetch, renderWith } from './helpers';

afterEach(() => {
  vi.unstubAllGlobals();
  setUnauthorizedHandler(null);
});

const unauthorized = () => new Response('{"detail":"authentication required"}', { status: 401 });

describe('401 handling', () => {
  it('sends the app to /login with next when a query answers 401', async () => {
    mockFetch({ '/api/runs': unauthorized, '/api/auth/me': unauthorized, '/api/sources': unauthorized });
    renderWith(<App />, { route: '/sources' });
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'));
    expect(screen.getByTestId('search')).toHaveTextContent('?next=%2Fsources');
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
  });

  it('a failed login does not count as a lost session', async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch({ '/api/auth/login': unauthorized });
    await expect(apiPost('/api/auth/login', {})).rejects.toBeInstanceOf(ApiError);
    expect(handler).not.toHaveBeenCalled();
    mockFetch({ '/api/runs': unauthorized });
    await expect(apiPost('/api/runs')).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe('UserMenu', () => {
  it('shows the user and logs out to /login', async () => {
    const fetch = mockFetch({
      '/api/auth/me': { auth: 'on', username: 'owner' },
      '/api/auth/logout': new Response(null, { status: 204 }),
      '/api/runs': [],
      '/api/sources': [],
    });
    renderWith(<App />, { route: '/sources' });
    expect(await screen.findByText('owner')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Log out' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'));
    const call = fetch.mock.calls.find(([u]) => String(u) === '/api/auth/logout')!;
    expect(call[1]?.method).toBe('POST');
    expect((call[1]?.headers as Record<string, string>)['X-Sidereal']).toBe('1');
  });

  it('shows no logout control when auth is off', async () => {
    mockFetch({ '/api/auth/me': { auth: 'off', username: null }, '/api/runs': [], '/api/sources': [] });
    renderWith(<App />, { route: '/sources' });
    expect(await screen.findByText('No sources configured.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument();
  });
});
