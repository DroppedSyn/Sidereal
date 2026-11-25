// Plan §10.4: only absolute http(s) URLs become links; anything else renders as plain text.

export function safeHref(url: string | null | undefined): string | undefined {
  if (typeof url !== 'string') return undefined;
  const trimmed = url.trim();
  if (trimmed === '' || trimmed !== url) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return undefined; // relative or malformed
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return undefined;
  if (parsed.hostname === '') return undefined;
  return parsed.href;
}
