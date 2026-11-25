import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseOptions } from '../src/components/settings/SourceForm';
import SourceSettings from '../src/components/settings/SourceSettings';
import { mockFetch, renderWith } from './helpers';
import { SOURCE, byMethod, json, writes } from './settingsHelpers';

afterEach(() => vi.unstubAllGlobals());

const FIELDS = { name: SOURCE.name, url: SOURCE.url, weight: SOURCE.weight,
  max_items: SOURCE.max_items, options: SOURCE.options };

describe('SourceSettings', () => {
  it('disables a source with one click (PUT without key or kind)', async () => {
    const fetch = mockFetch({
      '/api/settings/sources/3': json({ ...SOURCE, enabled: false }),
      '/api/settings/sources': [SOURCE],
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Krebs on Security enabled' }));
    expect(writes(fetch)).toEqual([{ url: '/api/settings/sources/3', method: 'PUT', sidereal: '1',
      body: { ...FIELDS, enabled: false } }]);
  });

  it('edits weight and options', async () => {
    const fetch = mockFetch({
      '/api/settings/sources/3': json(SOURCE),
      '/api/settings/sources': [SOURCE],
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Krebs on Security' }));
    const form = screen.getByRole('form', { name: 'Edit Krebs on Security' });
    const weight = within(form).getByLabelText('Weight (0.5 to 1.5)');
    await userEvent.clear(weight);
    await userEvent.type(weight, '1.3');
    const options = within(form).getByLabelText('Options (JSON)');
    await userEvent.clear(options);
    await userEvent.type(options, '{{"include_regex": "(?i)azure"}');
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }));
    expect(writes(fetch)).toEqual([{ url: '/api/settings/sources/3', method: 'PUT', sidereal: '1',
      body: { ...FIELDS, weight: 1.3, enabled: true, options: { include_regex: '(?i)azure' } } }]);
  });

  it('refuses options that are not a JSON object without sending', async () => {
    const fetch = mockFetch({ '/api/settings/sources': [SOURCE] });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    const form = screen.getByRole('form', { name: 'New source' });
    await userEvent.type(within(form).getByLabelText('Key (a-z, 0-9, -)'), 'new');
    await userEvent.type(within(form).getByLabelText('Name'), 'New');
    await userEvent.type(within(form).getByLabelText('Feed URL (http or https)'), 'https://e.example/rss');
    const options = within(form).getByLabelText('Options (JSON)');
    await userEvent.clear(options);
    await userEvent.type(options, '[[1, 2]');
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }));
    expect(screen.getByText(/Options must be a JSON object/)).toBeInTheDocument();
    expect(writes(fetch)).toEqual([]);
  });

  it('adds a source and shows the server refusal of a private URL', async () => {
    const fetch = mockFetch({
      '/api/settings/sources': byMethod([SOURCE], () => json({ detail: [{ loc: ['body', 'url'],
        msg: 'Value error, URL refused: address 10.0.0.5 is private' }] }, 422)),
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add source' }));
    const form = screen.getByRole('form', { name: 'New source' });
    await userEvent.type(within(form).getByLabelText('Key (a-z, 0-9, -)'), 'lan');
    await userEvent.selectOptions(within(form).getByLabelText('Kind'), 'msrc');
    await userEvent.type(within(form).getByLabelText('Name'), 'LAN');
    await userEvent.type(within(form).getByLabelText('Feed URL (http or https)'), 'http://10.0.0.5/rss');
    await userEvent.click(within(form).getByRole('button', { name: 'Save' }));
    expect(await screen.findByText(/Not saved: url: Value error, URL refused: address 10.0.0.5 is private/))
      .toBeInTheDocument();
    expect(writes(fetch)).toEqual([{ url: '/api/settings/sources', method: 'POST', sidereal: '1',
      body: { key: 'lan', kind: 'msrc', name: 'LAN', url: 'http://10.0.0.5/rss', enabled: true,
        weight: 1, max_items: 50, options: {} } }]);
  });

  it('tests a feed and shows the parsed count and titles as text', async () => {
    const fetch = mockFetch({
      '/api/settings/sources/test': json({ ok: true, entries: 12, items: 2, error: null,
        titles: ['<b>One</b>', 'Two'] }),
      '/api/settings/sources': [SOURCE],
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Krebs on Security' }));
    await userEvent.click(screen.getByRole('button', { name: 'Test feed' }));
    expect(await screen.findByText('Feed OK: 12 entries, 2 kept after filters.')).toBeInTheDocument();
    expect(screen.getByText('<b>One</b>')).toBeInTheDocument();
    expect(writes(fetch)).toEqual([{ url: '/api/settings/sources/test', method: 'POST', sidereal: '1',
      body: { kind: 'rss', url: SOURCE.url, max_items: 50, options: SOURCE.options } }]);
  });

  it('shows a failed feed test', async () => {
    mockFetch({
      '/api/settings/sources/test': json({ ok: false, entries: 0, items: 0, titles: [],
        error: 'URL refused: address 10.0.0.7 is private' }),
      '/api/settings/sources': [SOURCE],
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Krebs on Security' }));
    await userEvent.click(screen.getByRole('button', { name: 'Test feed' }));
    expect(await screen.findByText('Feed not usable: URL refused: address 10.0.0.7 is private'))
      .toBeInTheDocument();
  });

  it('shows a 409 when a source with items is deleted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockFetch({
      '/api/settings/sources/3': json({ detail: 'this source has items: disable it instead' }, 409),
      '/api/settings/sources': [SOURCE],
    });
    renderWith(<SourceSettings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Krebs on Security' }));
    expect(await screen.findByText('Could not delete: this source has items: disable it instead'))
      .toBeInTheDocument();
  });
});

describe('parseOptions', () => {
  it('accepts objects and empty text only', () => {
    expect(parseOptions('')).toEqual({});
    expect(parseOptions('{"a": 1}')).toEqual({ a: 1 });
    expect(typeof parseOptions('null')).toBe('string');
    expect(typeof parseOptions('[]')).toBe('string');
    expect(typeof parseOptions('{oops')).toBe('string');
  });
});
