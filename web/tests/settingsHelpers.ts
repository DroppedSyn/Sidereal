// Fixtures for the settings tests (M27).
import type { mockFetch } from './helpers';
import type { FocusArea, SettingsView, SourceConfig } from '../src/api/types';

export const AREA: FocusArea = {
  key: 'azure-networking', name: 'Azure networking', tier: 'primary',
  description: 'New Azure network resources and features, GA, preview and retirements.',
  keywords: ['vnet', 'private link'], enabled: true,
};

export const SOURCE: SourceConfig = {
  id: 3, key: 'krebs', name: 'Krebs on Security', kind: 'rss',
  url: 'https://krebsonsecurity.com/feed/', enabled: true, weight: 1.1, max_items: 50,
  options: { article_hosts: ['krebsonsecurity.com'] },
};

export const VIEW: SettingsView = {
  config: { scoring: { top_cap: 8, top_threshold: 72 }, budget: { max_assess_per_run: 40 },
    triage: { keep_min: 2 }, web: { port: 8470 } },
  overrides: { scoring: {}, budget: {}, triage: {} },
  editable: { scoring: ['top_threshold', 'top_cap'], budget: ['max_assess_per_run'],
    triage: ['keep_min'] },
  notify: [
    { name: 'email', enabled: false, configured: false,
      problem: 'email: set notify.smtp_host, smtp_from and smtp_to' },
    { name: 'discord', enabled: true, configured: true, problem: null },
  ],
};

export interface Sent {
  url: string;
  method: string | undefined;
  sidereal: string | undefined;
  body: unknown;
}

/** Every write the mocked fetch saw (POST/PUT/DELETE), in order. */
export function writes(fetch: ReturnType<typeof mockFetch>): Sent[] {
  return fetch.mock.calls
    .filter(([, init]) => init?.method !== undefined && init.method !== 'GET')
    .map(([url, init]) => ({
      url: String(url), method: init?.method,
      sidereal: (init?.headers as Record<string, string>)['X-Sidereal'],
      body: init?.body === undefined ? undefined : JSON.parse(String(init.body)) as unknown,
    }));
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** A route answering GETs with `get` and writes with `write(init)`. */
export function byMethod(get: unknown, write: (init?: RequestInit) => unknown) {
  return (_url: URL, init?: RequestInit) => (init?.method && init.method !== 'GET' ? write(init) : get);
}
