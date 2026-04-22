import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Home from './Home';
import { useAuthStore } from '../state/auth';

function renderHome() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<div>login screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Home', () => {
  beforeEach(() => {
    useAuthStore.getState().clearToken();
    localStorage.clear();
  });

  it('renders a Log out button', () => {
    renderHome();
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument();
  });

  it('clears the token and navigates to /login when Log out is clicked', async () => {
    useAuthStore.getState().setToken('kbr_home_token');
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole('button', { name: /log out/i }));

    expect(useAuthStore.getState().token).toBeNull();
    expect(await screen.findByText(/login screen/i)).toBeInTheDocument();
  });
});
