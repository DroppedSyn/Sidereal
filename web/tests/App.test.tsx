import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from '../src/App';

describe('App', () => {
  it('renders the Sidereal heading and a placeholder', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Sidereal' })).toBeInTheDocument();
    expect(screen.getByText(/being built/)).toBeInTheDocument();
  });
});
