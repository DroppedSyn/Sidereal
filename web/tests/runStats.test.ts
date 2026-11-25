import { describe, expect, it } from 'vitest';
import { summarizeStats } from '../src/lib/runStats';

describe('summarizeStats', () => {
  it('summarises the runner stats shape', () => {
    expect(
      summarizeStats({
        items: { new: 12 },
        stories: { new: 5 },
        assess: { ok: 4, failed: 1 },
        sources: { ok: 20, failed: 0 },
      }),
    ).toBe('12 new items · 5 new stories · 4 assessed · 1 assess failed');
  });

  it('is empty for unknown shapes', () => {
    expect(summarizeStats({ demo: true, items: 'x' })).toBe('');
  });
});
