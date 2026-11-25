import { describe, expect, it } from 'vitest';
import {
  formatDate,
  formatDateTime,
  formatDuration,
  formatTime,
  nextScheduledRun,
  relativeTime,
} from '../src/lib/format';

describe('format', () => {
  it('formats DD.MM.YYYY and 24 h times in Europe/London (BST in summer)', () => {
    expect(formatDate('2026-07-12T23:30:00Z')).toBe('13.07.2026');
    expect(formatTime('2026-07-12T23:30:00Z')).toBe('00:30');
    expect(formatDateTime('2026-07-14T13:02:00Z')).toBe('14.07.2026 14:02');
  });

  it('uses GMT in winter', () => {
    expect(formatDateTime('2026-01-05T09:07:00Z')).toBe('05.01.2026 09:07');
  });

  it('returns empty text for bad input', () => {
    expect(formatDate('not a date')).toBe('');
    expect(relativeTime('nope')).toBe('');
  });

  it('gives relative times', () => {
    const now = new Date('2026-07-14T14:30:00Z');
    expect(relativeTime('2026-07-14T14:29:40Z', now)).toBe('just now');
    expect(relativeTime('2026-07-14T14:31:00Z', now)).toBe('just now');
    expect(relativeTime('2026-07-14T14:18:00Z', now)).toBe('12 min ago');
    expect(relativeTime('2026-07-14T09:30:00Z', now)).toBe('5 h ago');
    expect(relativeTime('2026-07-13T14:00:00Z', now)).toBe('1 day ago');
    expect(relativeTime('2026-07-11T14:00:00Z', now)).toBe('3 days ago');
    expect(relativeTime('2026-07-01T14:00:00Z', now)).toBe('01.07.2026');
  });

  it('finds the next timer run on London hours 0, 4, ... 20', () => {
    // 15:30 BST → 16:00 BST = 15:00Z
    expect(nextScheduledRun(new Date('2026-07-14T14:30:00Z')).toISOString()).toBe('2026-07-14T15:00:00.000Z');
    // exactly on a run hour → the following one (16:00 BST → 20:00 BST)
    expect(nextScheduledRun(new Date('2026-07-14T15:00:00Z')).toISOString()).toBe('2026-07-14T19:00:00.000Z');
    // winter: 21:10 GMT → 00:00 GMT next day
    expect(nextScheduledRun(new Date('2026-01-05T21:10:00Z')).toISOString()).toBe('2026-01-06T00:00:00.000Z');
  });

  it('formats durations', () => {
    expect(formatDuration(null)).toBe('…');
    expect(formatDuration(42.4)).toBe('42 s');
    expect(formatDuration(125)).toBe('2 min 5 s');
    expect(formatDuration(3725)).toBe('1 h 2 min');
  });
});
