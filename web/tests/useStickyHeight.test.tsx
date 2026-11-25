import { render } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useStickyHeight } from '../src/lib/useStickyHeight';

function Probe({ height }: { height: number }) {
  const ref = useRef<HTMLElement>(null);
  useStickyHeight(ref);
  return (
    <header
      ref={(el) => {
        if (el) Object.defineProperty(el, 'offsetHeight', { configurable: true, value: height });
        (ref as { current: HTMLElement | null }).current = el;
      }}
    />
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.style.removeProperty('--topbar-h');
});

describe('useStickyHeight', () => {
  it('publishes the header height as --topbar-h', () => {
    render(<Probe height={84} />);
    expect(document.documentElement.style.getPropertyValue('--topbar-h')).toBe('84px');
  });

  it('updates on resize and cleans up on unmount', () => {
    let cb: (() => void) | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(fn: () => void) { cb = fn; }
        observe() {}
        disconnect() { disconnect(); }
      },
    );
    const { container, unmount } = render(<Probe height={84} />);
    const header = container.querySelector('header')!;
    Object.defineProperty(header, 'offsetHeight', { configurable: true, value: 150 });
    cb!();
    expect(document.documentElement.style.getPropertyValue('--topbar-h')).toBe('150px');
    unmount();
    expect(disconnect).toHaveBeenCalled();
    expect(document.documentElement.style.getPropertyValue('--topbar-h')).toBe('');
  });
});
