import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import StoryCard from '../src/components/StoryCard';
import { NOW, makeStory } from './helpers';

describe('StoryCard', () => {
  it('links the title to lead_url in a new tab without opener or referrer', () => {
    render(<StoryCard story={makeStory({ title: 'Big flaw', lead_url: 'https://x.example/a' })} now={NOW} />);
    const link = screen.getByRole('link', { name: 'Big flaw' });
    expect(link).toHaveAttribute('href', 'https://x.example/a');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it.each(['javascript:alert(1)', 'data:text/html,x', '/local', null])(
    'renders the title as plain text for lead_url %j',
    (url) => {
      render(<StoryCard story={makeStory({ title: 'Unsafe', lead_url: url })} now={NOW} />);
      expect(screen.getByRole('heading', { name: 'Unsafe' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Unsafe' })).toBeNull();
    },
  );

  it('renders markup in stored text as text, never as elements', () => {
    const evil = '<img src=x onerror=alert(1)><b>bold</b>';
    const { container } = render(
      <StoryCard story={makeStory({ title: evil, summary: evil, why: evil, tags: [evil] })} now={NOW} />,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByRole('heading', { name: evil })).toBeInTheDocument();
  });

  it('shows summary, why, focus, tags, flags, time and a subtle score', () => {
    render(
      <StoryCard
        story={makeStory({
          summary: 'Patch now.',
          why: 'You run Entra.',
          focus: 'entra-identity',
          tags: ['entra', 'cve'],
          flags: { kev: true, exploited: true, cvss: 9.8 },
          first_seen_at: '2026-07-14T12:30:00Z',
          score: 84.4,
        })}
        now={NOW}
      />,
    );
    expect(screen.getByText('AI summary')).toBeInTheDocument();
    expect(screen.getByText('Patch now.')).toBeInTheDocument();
    expect(screen.getByText('Why it matters:')).toBeInTheDocument();
    expect(screen.getByText('You run Entra.')).toBeInTheDocument();
    const labels = screen.getByRole('list', { name: 'Labels' });
    for (const text of ['KEV', 'Exploited', 'CVSS 9.8', 'entra-identity', 'entra', 'cve']) {
      expect(within(labels).getByText(text)).toBeInTheDocument();
    }
    const time = screen.getByText('2 h ago');
    expect(time).toHaveAttribute('title', '14.07.2026 13:30');
    expect(time).toHaveAttribute('datetime', '2026-07-14T12:30:00Z');
    expect(screen.getByText('score 84')).toBeInTheDocument();
  });

  it('hides focus "none" and marks a failed assessment', () => {
    render(<StoryCard story={makeStory({ focus: 'none', tags: [], score: null, summary: null, why: null })} />);
    expect(screen.queryByRole('list', { name: 'Labels' })).toBeNull();
    expect(screen.getByText('not assessed')).toBeInTheDocument();
    expect(screen.queryByText('AI summary')).toBeNull();
    expect(screen.queryByText('Why it matters:')).toBeNull();
  });

  it('toggles the original excerpt', async () => {
    render(<StoryCard story={makeStory({ excerpt: 'Raw feed text.' })} />);
    expect(screen.queryByText('Raw feed text.')).toBeNull();
    const button = screen.getByRole('button', { name: 'Show original excerpt' });
    await userEvent.click(button);
    expect(screen.getByText('Raw feed text.')).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Hide original excerpt' }));
    expect(screen.queryByText('Raw feed text.')).toBeNull();
  });

  it('compact cards skip the why line and the excerpt toggle', () => {
    render(<StoryCard story={makeStory({ why: 'Because.' })} variant="compact" />);
    expect(screen.queryByText('Because.')).toBeNull();
    expect(screen.queryByRole('button', { name: /excerpt/ })).toBeNull();
  });
});
