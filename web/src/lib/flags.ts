// Story flags (stories.flags_json, e.g. {"kev": true, "exploited": true, "cvss": 9.8}) as badges.

export interface FlagBadge {
  key: string;
  label: string;
  severe: boolean;
}

export function flagBadges(flags: Record<string, unknown>): FlagBadge[] {
  const out: FlagBadge[] = [];
  if (flags.kev === true) out.push({ key: 'kev', label: 'KEV', severe: true });
  if (flags.exploited === true) out.push({ key: 'exploited', label: 'Exploited', severe: true });
  const cvss = flags.cvss;
  if (typeof cvss === 'number' && Number.isFinite(cvss)) {
    out.push({ key: 'cvss', label: `CVSS ${cvss.toFixed(1)}`, severe: cvss >= 9 });
  }
  return out;
}
