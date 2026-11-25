import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DaySummary } from '../src/api/types';
import DayList from '../src/components/DayList';
import { renderWith } from './helpers';

const DAYS: DaySummary[] = [
  { day: '2026-07-14', label: 'Tuesday - 14.07.2026', counts: { top: 1, relevant: 3, side: 2 }, run_count: 4, headline: null },
  { day: '2026-07-12', label: 'Sunday - 12.07.2026', counts: { top: 0, relevant: 1, side: 5 }, run_count: 6, headline: 'H' },
];

describe('DayList', () => {
  it('shows labels exactly as given, with counts, and marks the selected day', () => {
    renderWith(<DayList days={DAYS} selected="2026-07-12" hasMore={false} loadingMore={false} onLoadMore={() => {}} />,
      { route: '/daily/2026-07-12' });
    const nav = screen.getByRole('navigation', { name: 'Days' });
    expect(nav).toHaveTextContent('Sunday - 12.07.2026');
    expect(nav).toHaveTextContent('0 top · 1 relevant · 5 side');
    expect(screen.getByRole('link', { name: /Sunday - 12\.07\.2026/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /Tuesday/ })).not.toHaveAttribute('aria-current');
    expect(screen.queryByRole('button', { name: /older/ })).toBeNull();
  });

  it('navigates via the links and the mobile dropdown', async () => {
    renderWith(<DayList days={DAYS} selected="2026-07-14" hasMore={false} loadingMore={false} onLoadMore={() => {}} />,
      { route: '/daily/2026-07-14' });
    await userEvent.click(screen.getByRole('link', { name: /Sunday/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/daily/2026-07-12');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Day' }), '2026-07-14');
    expect(screen.getByTestId('location')).toHaveTextContent('/daily/2026-07-14');
  });

  it('loads older days on request', async () => {
    const onLoadMore = vi.fn();
    renderWith(<DayList days={DAYS} selected={undefined} hasMore loadingMore={false} onLoadMore={onLoadMore} />);
    await userEvent.click(screen.getAllByRole('button', { name: 'Load older days' })[0]!);
    expect(onLoadMore).toHaveBeenCalledOnce();
  });
});
