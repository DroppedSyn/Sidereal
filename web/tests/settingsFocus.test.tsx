import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FocusAreas from '../src/components/settings/FocusAreas';
import { splitKeywords } from '../src/components/settings/FocusAreaForm';
import { mockFetch, renderWith } from './helpers';
import { AREA, byMethod, json, writes } from './settingsHelpers';

afterEach(() => vi.unstubAllGlobals());

describe('FocusAreas', () => {
  it('lists areas with tier and keywords', async () => {
    mockFetch({ '/api/settings/focus': [AREA, { ...AREA, key: 'x', name: 'Other', enabled: false }] });
    renderWith(<FocusAreas />);
    expect(await screen.findByText('Azure networking')).toBeInTheDocument();
    expect(screen.getAllByText('vnet, private link')).toHaveLength(2);
    expect(screen.getByText('disabled')).toBeInTheDocument();
  });

  it('edits an area with PUT, X-Sidereal and no key in the body', async () => {
    const fetch = mockFetch({
      '/api/settings/focus/azure-networking': (_u: URL, init?: RequestInit) =>
        json({ ...AREA, ...JSON.parse(String(init?.body)) }),
      '/api/settings/focus': [AREA],
    });
    renderWith(<FocusAreas />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Azure networking' }));
    const form = screen.getByRole('form', { name: 'Edit Azure networking' });
    await userEvent.selectOptions(within(form).getByLabelText('Tier'), 'side');
    const kw = within(form).getByLabelText('Keywords (comma-separated)');
    await userEvent.clear(kw);
    await userEvent.type(kw, 'vnet, , VWAN ');
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('button', { name: 'Edit Azure networking' })).toBeInTheDocument();
    expect(writes(fetch)).toEqual([{
      url: '/api/settings/focus/azure-networking', method: 'PUT', sidereal: '1',
      body: { name: AREA.name, tier: 'side', description: AREA.description,
        keywords: ['vnet', 'VWAN'], enabled: true },
    }]);
  });

  it('adds an area with POST and shows a 422 from the server', async () => {
    const fetch = mockFetch({
      '/api/settings/focus': byMethod([AREA], () =>
        json({ detail: [{ loc: ['body', 'description'], msg: 'String should have at least 40 characters' }] }, 422)),
    });
    renderWith(<FocusAreas />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add focus area' }));
    const form = screen.getByRole('form', { name: 'New focus area' });
    await userEvent.type(within(form).getByLabelText('Key (a-z, 0-9, -)'), 'finops');
    await userEvent.type(within(form).getByLabelText('Name'), 'FinOps');
    await userEvent.type(within(form).getByLabelText(/Description/), 'short');
    await userEvent.type(within(form).getByLabelText('Keywords (comma-separated)'), 'finops');
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Not saved: description: String should have at least 40 characters'))
      .toBeInTheDocument();
    expect(writes(fetch)).toEqual([{ url: '/api/settings/focus', method: 'POST', sidereal: '1',
      body: { key: 'finops', name: 'FinOps', tier: 'secondary', description: 'short',
        keywords: ['finops'], enabled: true } }]);
    expect(screen.getByRole('form', { name: 'New focus area' })).toBeInTheDocument();
  });

  it('deletes after confirming', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fetch = mockFetch({
      '/api/settings/focus/azure-networking': new Response(null, { status: 204 }),
      '/api/settings/focus': [AREA],
    });
    renderWith(<FocusAreas />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Azure networking' }));
    expect(writes(fetch)).toEqual([{ url: '/api/settings/focus/azure-networking',
      method: 'DELETE', sidereal: '1', body: undefined }]);
  });

  it('does not delete when the confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const fetch = mockFetch({ '/api/settings/focus': [AREA] });
    renderWith(<FocusAreas />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Azure networking' }));
    expect(writes(fetch)).toEqual([]);
  });
});

describe('splitKeywords', () => {
  it('trims and drops empty entries', () => {
    expect(splitKeywords(' a , ,b,, c d ')).toEqual(['a', 'b', 'c d']);
    expect(splitKeywords('')).toEqual([]);
  });
});
