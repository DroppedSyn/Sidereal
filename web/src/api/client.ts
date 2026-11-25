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

// One FastAPI validation error (`{loc, msg}`) as "field: message" (the body/query prefix dropped).
function validationText(item: unknown): string {
  if (item === null || typeof item !== 'object') return '';
  const { loc, msg } = item as { loc?: unknown; msg?: unknown };
  if (typeof msg !== 'string') return '';
  const where = Array.isArray(loc) ? loc.slice(1).map(String).join('.') : '';
  return where ? `${where}: ${msg}` : msg;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body !== null && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        const text = detail.map(validationText).filter((t) => t !== '').join('; ');
        if (text) return text;
      }
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

function send<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Sidereal': '1' };
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  return request<T>(path, init);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return send<T>('POST', path, body);
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return send<T>('PUT', path, body);
}

export function apiDelete<T>(path: string): Promise<T> {
  return send<T>('DELETE', path);
}
