// The only place that talks to the API. Every write carries `X-Sidereal: 1` (plan §11 write guard);
// the browser adds Origin itself.

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string') return detail;
    }
  } catch {
    // not JSON: fall through to the status text
  }
  return `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ''}`;
}

// Called on any 401 except from the login call itself (a failed login is not a lost session).
// The app shell registers a handler that sends the browser to /login?next=… (plan §11.2).
let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export const LOGIN_PATH = '/api/auth/login';

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: 'same-origin', ...init });
  } catch {
    throw new ApiError(0, 'The server cannot be reached.');
  }
  if (!res.ok) {
    if (res.status === 401 && path !== LOGIN_PATH) unauthorizedHandler?.();
    throw new ApiError(res.status, await errorMessage(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type Query = Record<string, string | number | boolean | undefined>;

export function withQuery(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export function apiGet<T>(path: string, query?: Query): Promise<T> {
  return request<T>(withQuery(path, query), { method: 'GET', headers: { Accept: 'application/json' } });
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Sidereal': '1' };
  const init: RequestInit = { method: 'POST', headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  return request<T>(path, init);
}
