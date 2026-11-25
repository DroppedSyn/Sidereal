import { describe, expect, it } from 'vitest';
import { safeHref } from '../src/lib/safeHref';

describe('safeHref', () => {
  it.each(['https://example.com/a?b=1', 'http://example.com/', 'HTTPS://Example.com/x'])(
    'keeps http(s) URL %s',
    (url) => {
      expect(safeHref(url)).toBe(new URL(url).href);
    },
  );

  it.each([
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'java\tscript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'file:///etc/passwd',
    'ftp://example.com/',
    '/relative/path',
    'relative/path',
    '//example.com/protocol-relative',
    '#top',
    ' https://example.com/',
    ' javascript:alert(1)',
    'https://example.com/\n',
    '',
    'https://',
  ])('rejects %j', (url) => {
    expect(safeHref(url)).toBeUndefined();
  });

  it('rejects null and undefined', () => {
    expect(safeHref(null)).toBeUndefined();
    expect(safeHref(undefined)).toBeUndefined();
  });
});
