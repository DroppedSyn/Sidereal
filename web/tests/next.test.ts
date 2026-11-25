import { describe, expect, it } from 'vitest';
import { loginPath, safeNext } from '../src/lib/next';

describe('safeNext', () => {
  it('keeps same-site paths', () => {
    expect(safeNext('/daily/2026-07-14')).toBe('/daily/2026-07-14');
    expect(safeNext('/runs?x=1')).toBe('/runs?x=1');
  });

  it('refuses anything that could leave the site or loop', () => {
    for (const bad of [null, undefined, '', 'https://evil.example', '//evil.example', '/\\evil.example',
      'javascript:alert(1)', '/a\\b', '/a\nb', '/login', '/login?next=/x']) {
      expect(safeNext(bad)).toBe('/');
    }
  });

  it('builds the login path with an encoded next', () => {
    expect(loginPath('/daily/2026-07-14')).toBe('/login?next=%2Fdaily%2F2026-07-14');
    expect(loginPath('/')).toBe('/login');
    expect(loginPath('//evil')).toBe('/login');
  });
});
