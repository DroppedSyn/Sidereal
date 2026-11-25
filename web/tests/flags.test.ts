import { describe, expect, it } from 'vitest';
import { flagBadges } from '../src/lib/flags';

describe('flagBadges', () => {
  it('maps kev, exploited and cvss in that order', () => {
    expect(flagBadges({ cvss: 9.8, exploited: true, kev: true }).map((f) => f.label)).toEqual([
      'KEV',
      'Exploited',
      'CVSS 9.8',
    ]);
  });

  it('marks CVSS below 9 as not severe and ignores non-true and non-number values', () => {
    expect(flagBadges({ cvss: 7 })).toEqual([{ key: 'cvss', label: 'CVSS 7.0', severe: false }]);
    expect(flagBadges({ kev: 'yes', exploited: 1, cvss: '9.8', kev_vendor: 'Microsoft' })).toEqual([]);
  });
});
