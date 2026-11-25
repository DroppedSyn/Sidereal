// One-line summary of a run's stats JSON (pipeline/runner.py shapes); unknown shapes → ''.

function num(stats: Record<string, unknown>, group: string, key: string): number | undefined {
  const g = stats[group];
  if (g === null || typeof g !== 'object') return undefined;
  const v = (g as Record<string, unknown>)[key];
  return typeof v === 'number' ? v : undefined;
}

export function summarizeStats(stats: Record<string, unknown>): string {
  const parts: string[] = [];
  const add = (value: number | undefined, label: string, always = true) => {
    if (value !== undefined && (always || value > 0)) parts.push(`${value} ${label}`);
  };
  add(num(stats, 'items', 'new'), 'new items');
  add(num(stats, 'stories', 'new'), 'new stories');
  add(num(stats, 'assess', 'ok'), 'assessed');
  add(num(stats, 'assess', 'failed'), 'assess failed', false);
  add(num(stats, 'sources', 'failed'), 'sources failed', false);
  return parts.join(' · ');
}
