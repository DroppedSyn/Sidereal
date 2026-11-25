// Dates and times for display: DD.MM.YYYY, 24 h clock, always Europe/London (the server's
// schedule.tz default; the API sends UTC ISO strings ending in Z).

export const TIME_ZONE = 'Europe/London';
// deploy/sidereal-run.timer: OnCalendar=*-*-* 00,04,08,12,16,20:00:00 Europe/London
export const RUN_HOURS = [0, 4, 8, 12, 16, 20];

const partsFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

interface LocalParts {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
}

function localParts(date: Date): LocalParts {
  const out: Record<string, string> = {};
  for (const p of partsFormat.formatToParts(date)) out[p.type] = p.value;
  return {
    year: out.year ?? '',
    month: out.month ?? '',
    day: out.day ?? '',
    hour: out.hour ?? '',
    minute: out.minute ?? '',
  };
}

function toDate(value: string | Date): Date | null {
  const d = typeof value === 'string' ? new Date(value) : value;
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDate(value: string | Date): string {
  const d = toDate(value);
  if (d === null) return '';
  const p = localParts(d);
  return `${p.day}.${p.month}.${p.year}`;
}

export function formatTime(value: string | Date): string {
  const d = toDate(value);
  if (d === null) return '';
  const p = localParts(d);
  return `${p.hour}:${p.minute}`;
}

export function formatDateTime(value: string | Date): string {
  const d = toDate(value);
  return d === null ? '' : `${formatDate(d)} ${formatTime(d)}`;
}

/** "just now", "12 min ago", "5 h ago", "3 days ago"; older than a week → DD.MM.YYYY. */
export function relativeTime(value: string, now: Date = new Date()): string {
  const d = toDate(value);
  if (d === null) return '';
  const minutes = Math.floor((now.getTime() - d.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return days === 1 ? '1 day ago' : `${days} days ago`;
  return formatDate(d);
}

/** The next timer run strictly after `now` (London wall-clock hours in RUN_HOURS). */
export function nextScheduledRun(now: Date): Date {
  const hour = 3_600_000;
  // London's offset is a whole number of hours, so UTC hour boundaries are local ones too.
  let t = Math.floor(now.getTime() / hour) * hour + hour;
  for (let i = 0; i < 48; i += 1, t += hour) {
    const h = Number(localParts(new Date(t)).hour);
    if (RUN_HOURS.includes(h)) return new Date(t);
  }
  return new Date(t);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '…';
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60} s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}
