import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiGet } from '../src/api/client';
import { toOverrides } from '../src/components/settings/TuningForm';
import SettingsPage from '../src/pages/SettingsPage';
import { mockFetch, renderWith } from './helpers';
import { AREA, SOURCE, VIEW, json, writes } from './settingsHelpers';

afterEach(() => vi.unstubAllGlobals());

function routes(extra: Record<string, unknown> = {}) {
  return { '/api/settings/focus': [AREA], '/api/settings/sources': [SOURCE], '/api/settings': VIEW,
    ...extra };
}

describe('SettingsPage', () => {
  it('renders every section and the effective config as text', async () => {
    mockFetch(routes());
    renderWith(<SettingsPage />, { route: '/settings' });
    for (const name of ['Focus areas', 'Sources', 'Scoring and budget', 'Notifications',
      'Effective config (read-only)']) {
      expect(await screen.findByRole('heading', { name })).toBeInTheDocument();
    }
    expect(document.querySelector('.config-dump')?.textContent).toContain('"top_cap": 8');
  });

  it('saves overrides as numbers, only filled-in fields', async () => {
    const fetch = mockFetch(routes({
      '/api/settings/overrides': json({ ...VIEW, overrides: { scoring: { top_cap: 5 }, budget: {}, triage: {} } }),
    }));
    renderWith(<SettingsPage />);
    const cap = await screen.findByLabelText('scoring.top_cap');
    expect(cap).toHaveAttribute('placeholder', '8');
    await userEvent.type(cap, '5');
    await userEvent.click(screen.getByRole('button', { name: 'Save overrides' }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();
    expect(writes(fetch)).toEqual([{ url: '/api/settings/overrides', method: 'PUT', sidereal: '1',
      body: { scoring: { top_cap: 5 }, budget: {}, triage: {} } }]);
    expect(screen.getByLabelText('scoring.top_cap')).toHaveValue('5');
  });

  it('shows a refused override', async () => {
    mockFetch(routes({
      '/api/settings/overrides': json({ detail: 'scoring thresholds must satisfy top > relevant > side' }, 422),
    }));
    renderWith(<SettingsPage />);
    await userEvent.type(await screen.findByLabelText('scoring.top_threshold'), '10');
    await userEvent.click(screen.getByRole('button', { name: 'Save overrides' }));
    expect(await screen.findByText('Not saved: scoring thresholds must satisfy top > relevant > side'))
      .toBeInTheDocument();
  });

  it('resets every override', async () => {
    const fetch = mockFetch(routes({ '/api/settings/overrides': json(VIEW) }));
    renderWith(<SettingsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Reset all to the file' }));
    expect(writes(fetch)[0]?.body).toEqual({ scoring: {}, budget: {}, triage: {} });
  });

  it('shows channel state and sends a test message', async () => {
    const fetch = mockFetch(routes({
      '/api/settings/notify/test': json({ channel: 'discord', ok: true, error: null }),
    }));
    renderWith(<SettingsPage />);
    const section = (await screen.findByRole('heading', { name: 'Notifications' })).closest('section')!;
    expect(within(section).getByText('not configured')).toBeInTheDocument();
    expect(within(section).getByText('configured')).toBeInTheDocument();
    expect(within(section).getByText(/set notify.smtp_host/)).toBeInTheDocument();
    await userEvent.click(within(section).getByRole('button', { name: 'Send test Discord' }));
    expect(await within(section).findByText('Test message sent.')).toBeInTheDocument();
    expect(writes(fetch)).toEqual([{ url: '/api/settings/notify/test', method: 'POST', sidereal: '1',
      body: { channel: 'discord' } }]);
  });

  it('shows a failed test send', async () => {
    mockFetch(routes({
      '/api/settings/notify/test': json({ channel: 'email', ok: false, error: 'email: SIDEREAL_SMTP_PASSWORD is not set' }),
    }));
    renderWith(<SettingsPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send test Email' }));
    expect(await screen.findByText('Test failed: email: SIDEREAL_SMTP_PASSWORD is not set')).toBeInTheDocument();
  });
});

describe('toOverrides', () => {
  it('drops empty fields and keeps unparsable text for the server to refuse', () => {
    expect(toOverrides({ scoring: { top_cap: ' 5 ', kev_bonus: '', w_novelty: 'abc' }, triage: {} }))
      .toEqual({ scoring: { top_cap: 5, w_novelty: 'abc' }, triage: {} });
  });
});

describe('client validation errors', () => {
  it('turns a FastAPI 422 list into field messages', async () => {
    mockFetch({ '/api/x': json({ detail: [
      { loc: ['body', 'scoring', 'top_cap'], msg: 'Input should be greater than or equal to 1' },
      { loc: ['body', 'url'], msg: 'Value error, URL refused' }] }, 422) });
    await expect(apiGet('/api/x')).rejects.toThrow(
      'scoring.top_cap: Input should be greater than or equal to 1; url: Value error, URL refused');
  });
});
