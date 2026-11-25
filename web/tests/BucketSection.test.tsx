import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import BucketSection from '../src/components/BucketSection';
import { makeStory } from './helpers';

describe('BucketSection', () => {
  it('has a heading with the count and one card per story', () => {
    render(<BucketSection title="Relevant" bucket="relevant" emptyMessage="none"
      stories={[makeStory({ title: 'A' }), makeStory({ title: 'B' })]} />);
    const section = screen.getByRole('region', { name: 'Relevant 2' });
    expect(section).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(2);
  });

  it('shows the empty message', () => {
    render(<BucketSection title="TOP" bucket="top" emptyMessage="Calm." stories={[]} />);
    expect(screen.getByText('Calm.')).toBeInTheDocument();
    expect(screen.queryByRole('article')).toBeNull();
  });

  it('collapses after N and expands on request', async () => {
    const stories = Array.from({ length: 13 }, (_, i) => makeStory({ title: `S${i}` }));
    render(<BucketSection title="On the side" bucket="side" emptyMessage="" stories={stories}
      collapseAfter={10} variant="compact" />);
    expect(screen.getAllByRole('article')).toHaveLength(10);
    await userEvent.click(screen.getByRole('button', { name: 'Show 3 more' }));
    expect(screen.getAllByRole('article')).toHaveLength(13);
    expect(screen.queryByRole('button', { name: /more/ })).toBeNull();
  });
});
