import { describe, expect, it } from 'vitest';
import { currentWeek, isoWeek, localDay, paragraphs } from '../src/lib/week';

describe('isoWeek', () => {
  it.each([
    ['2026-11-23', '2026-W48'],
    ['2026-11-29', '2026-W48'],
    ['2026-11-30', '2026-W49'],
    ['2026-12-28', '2026-W53'],
    ['2027-01-03', '2026-W53'],
    ['2027-01-04', '2027-W01'],
    ['2025-12-29', '2026-W01'],
    ['2021-01-03', '2020-W53'],
  ])('%s is in %s', (day, week) => {
    expect(isoWeek(day)).toBe(week);
  });
});

describe('currentWeek', () => {
  it('uses the London date, not UTC', () => {
    // Sunday 29.03.2026 23:30 UTC is Monday 00:30 in London (BST).
    expect(localDay(new Date('2026-03-29T23:30:00Z'))).toBe('2026-03-30');
    expect(currentWeek(new Date('2026-03-29T23:30:00Z'))).toBe('2026-W14');
    // Sunday 25.10.2026 23:30 UTC is still Sunday in London (GMT).
    expect(currentWeek(new Date('2026-10-25T23:30:00Z'))).toBe('2026-W43');
  });
});

describe('paragraphs', () => {
  it('splits on blank lines and drops empty ones', () => {
    expect(paragraphs('One.\n\nTwo\nlines.\n \n\nThree.\n\n')).toEqual(['One.', 'Two\nlines.', 'Three.']);
  });
});
