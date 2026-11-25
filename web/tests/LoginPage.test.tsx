import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LoginPage from '../src/pages/LoginPage';
import { mockFetch, renderWith } from './helpers';

afterEach(() => vi.unstubAllGlobals());

async function fill(user = 'owner', password = 'correct horse battery', code = '') {
  await userEvent.type(screen.getByLabelText('Username'), user);
  await userEvent.type(screen.getByLabelText('Password'), password);
  if (code) await userEvent.type(screen.getByLabelText('Authentication code (if set up)'), code);
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('LoginPage', () => {
  it('posts the credentials with the write header and goes to next', async () => {
    const fetch = mockFetch({ '/api/auth/login': { auth: 'on', username: 'owner' } });
    renderWith(<LoginPage />, { route: '/login?next=%2Fdaily%2F2026-07-14', path: '*' });
    await fill('owner', 'correct horse battery', '123 456');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/daily/2026-07-14'));
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('/api/auth/login');
    expect((init?.headers as Record<string, string>)['X-Sidereal']).toBe('1');
    expect(JSON.parse(String(init?.body))).toEqual({
      username: 'owner', password: 'correct horse battery', code: '123 456',
    });
  });

  it('sends a null code when none is given and ignores an off-site next', async () => {
    const fetch = mockFetch({ '/api/auth/login': { auth: 'on', username: 'owner' } });
    renderWith(<LoginPage />, { route: '/login?next=%2F%2Fevil.example', path: '*' });
    await fill();
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(/^\/$/));
    expect(JSON.parse(String(fetch.mock.calls[0]![1]?.body)).code).toBeNull();
  });

  it('shows one generic message on 401 and clears the password', async () => {
    mockFetch({
      '/api/auth/login': new Response('{"detail":"invalid username, password or code"}', { status: 401 }),
    });
    renderWith(<LoginPage />, { route: '/login', path: '/login' });
    await fill();
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username, password or code.');
    expect(screen.getByLabelText('Password')).toHaveValue('');
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
  });

  it('explains the rate limit', async () => {
    mockFetch({ '/api/auth/login': new Response('{"detail":"x"}', { status: 429 }) });
    renderWith(<LoginPage />, { route: '/login', path: '/login' });
    await fill();
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many failed attempts');
  });
});
