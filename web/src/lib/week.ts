// ISO weeks for the Week tab (M29): keys like 2026-W48, Monday..Sunday of London days, the same
// rule as the server's `weeks.py`.
import { TIME_ZONE } from './format';

const dayFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** The London date of `date` as YYYY-MM-DD. */
export function localDay(date: Date): string {
  const out: Record<string, string> = {};
  for (const p of dayFormat.formatToParts(date)) out[p.type] = p.value;
  return `${out.year}-${out.month}-${out.day}`;
}

/** ISO week key of a YYYY-MM-DD date: the week belongs to the year of its Thursday. */
export function isoWeek(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  const date = new Date(Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1));
  const weekday = date.getUTCDay() || 7; // Monday 1 .. Sunday 7
  date.setUTCDate(date.getUTCDate() + 4 - weekday); // that week's Thursday
  const year = date.getUTCFullYear();
  const week = Math.floor((date.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 / 7) + 1;
  return `${year}-W${String(week).padStart(2, '0')}`;
}

export function currentWeek(now: Date = new Date()): string {
  return isoWeek(localDay(now));
}

/** Overview paragraphs (the server joins them with one blank line). */
export function paragraphs(text: string): string[] {
  return text.split(/\n\s*\n/).map((p) => p.trim()).filter((p) => p !== '');
}
