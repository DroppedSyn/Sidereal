import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SourceBadges from '../src/components/SourceBadges';

describe('SourceBadges', () => {
  it('links http(s) sources and renders others as text', () => {
    render(
      <SourceBadges
        sources={[
          { key: 'msrc', name: 'MSRC', url: 'https://msrc.example/1' },
          { key: 'bad', name: 'Bad', url: 'javascript:alert(1)' },
          { key: 'none', name: 'No URL', url: null },
        ]}
      />,
    );
    const link = screen.getByRole('link', { name: 'MSRC' });
    expect(link).toHaveAttribute('href', 'https://msrc.example/1');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText('Bad').closest('a')).toBeNull();
    expect(screen.getByText('No URL').closest('a')).toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('renders nothing without sources', () => {
    const { container } = render(<SourceBadges sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
