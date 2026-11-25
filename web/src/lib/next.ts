// Where to go after login: only a same-site path, never another origin (open-redirect guard).
export function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/';
  if ([...raw].some((ch) => ch.charCodeAt(0) < 0x20 || ch === '\\')) return '/';
  if (raw === '/login' || raw.startsWith('/login?') || raw.startsWith('/login/')) return '/';
  return raw;
}

export function loginPath(current: string): string {
  const next = safeNext(current);
  return next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`;
}
