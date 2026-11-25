import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import RunTimeline from '../src/components/RunTimeline';

describe('RunTimeline', () => {
  it('shows one entry per run with the time and the status as text', () => {
    render(
      <RunTimeline
        runs={[
          { id: 1, started_at: '2026-07-12T00:00:00Z', finished_at: '2026-07-12T00:05:00Z', trigger: 'timer', status: 'ok' },
          { id: 2, started_at: '2026-07-12T04:00:00Z', finished_at: null, trigger: 'manual', status: 'failed' },
        ]}
      />,
    );
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('01:00ok');
    expect(items[1]).toHaveTextContent('05:00failed');
    expect(items[1]).toHaveClass('run-failed');
    expect(items[1]).toHaveAttribute('title', '12.07.2026 05:00 · manual · failed');
  });

  it('says when there were no scans', () => {
    render(<RunTimeline runs={[]} />);
    expect(screen.getByText('No scans this day.')).toBeInTheDocument();
  });
});
