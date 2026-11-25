import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import StorySections, { CALM_MESSAGE } from '../src/components/StorySections';
import { countsOf, makeSections, makeStory } from './helpers';

describe('StorySections', () => {
  it('renders TOP, Relevant and On the side with their stories', () => {
    const s = makeSections({
      top: [makeStory({ title: 'Top one', bucket: 'top' })],
      relevant: [makeStory({ title: 'Rel one' })],
      side: [makeStory({ title: 'Side one', bucket: 'side' })],
    });
    render(<StorySections sections={s} counts={countsOf(s)} includeDrop={false} onToggleDrop={() => {}} />);
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(['TOP 1', 'Relevant 1', 'On the side 1']);
    expect(screen.getByRole('region', { name: 'TOP 1' })).toHaveTextContent('Top one');
    expect(screen.getByRole('region', { name: 'Relevant 1' })).toHaveTextContent('Rel one');
    expect(screen.getByRole('region', { name: 'On the side 1' })).toHaveTextContent('Side one');
    expect(screen.queryByRole('button', { name: /dropped/ })).toBeNull();
  });

  it('shows the calm message when TOP is empty', () => {
    const s = makeSections();
    render(<StorySections sections={s} counts={countsOf(s)} includeDrop={false} onToggleDrop={() => {}} />);
    expect(screen.getByText(CALM_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText('Nothing relevant here.')).toBeInTheDocument();
    expect(screen.getByText('Nothing on the side.')).toBeInTheDocument();
  });

  it('offers "Show N dropped" from the counts and shows the dropped list when included', async () => {
    const onToggle = vi.fn();
    const s = makeSections();
    const { rerender } = render(
      <StorySections sections={s} counts={countsOf(s, 4)} includeDrop={false} onToggleDrop={onToggle} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Show 4 dropped' }));
    expect(onToggle).toHaveBeenCalledOnce();
    const withDrop = makeSections({ drop: [makeStory({ title: 'Dropped one', bucket: 'drop' })] });
    rerender(<StorySections sections={withDrop} counts={countsOf(withDrop, 4)} includeDrop onToggleDrop={onToggle} />);
    expect(screen.getByRole('button', { name: 'Hide 4 dropped' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('region', { name: 'Dropped 1' })).toHaveTextContent('Dropped one');
  });
});
