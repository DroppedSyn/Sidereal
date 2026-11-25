import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiGet, apiPost, withQuery } from '../src/api/client';
import { mockFetch } from './helpers';

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('builds query strings and skips undefined values', () => {
    expect(withQuery('/api/days', { limit: 60, before: undefined })).toBe('/api/days?limit=60');
    expect(withQuery('/api/gazette')).toBe('/api/gazette');
  });

  it('GETs JSON without the write header', async () => {
    const fetch = mockFetch({ '/api/runs': [{ id: 1 }] });
    await expect(apiGet('/api/runs', { limit: 1 })).resolves.toEqual([{ id: 1 }]);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe('/api/runs?limit=1');
    expect((init?.headers as Record<string, string>)['X-Sidereal']).toBeUndefined();
  });

  it('POSTs with X-Sidereal: 1', async () => {
    const fetch = mockFetch({ '/api/runs': { status: 'started', unit: 'u' } });
    await apiPost('/api/runs');
    const init = fetch.mock.calls[0]![1]!;
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-Sidereal']).toBe('1');
  });

  it('turns an error response into ApiError with the detail text', async () => {
    mockFetch({ '/api/runs': new Response('{"detail":"a run is already in progress"}', { status: 409 }) });
    const err = await apiPost('/api/runs').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe('a run is already in progress');
  });

  it('falls back to the status for non-JSON errors and network failures', async () => {
    mockFetch({ '/api/x': new Response('oops', { status: 502 }) });
    await expect(apiGet('/api/x')).rejects.toThrow('HTTP 502');
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('net'))));
    await expect(apiGet('/api/x')).rejects.toMatchObject({ status: 0 });
  });
});
