import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Login from './Login';
import { useAuthStore } from '../state/auth';

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>board placeholder</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Login', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().clearToken();
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('signs in, stores the token, and navigates away on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText(/api token/i), 'kbr_good_token');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [url, init] = call as [string, RequestInit];
    expect(url).toBe('/api/v1/workspaces');
    expect(init.method).toBe('GET');
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer kbr_good_token');

    expect(await screen.findByText(/board placeholder/i)).toBeInTheDocument();
    expect(useAuthStore.getState().token).toBe('kbr_good_token');
  });

  it('shows an error and does not store the token when the server returns 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'bad' } }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText(/api token/i), 'kbr_bad_token');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/rejected/i);
    expect(useAuthStore.getState().token).toBeNull();
    expect(screen.queryByText(/board placeholder/i)).not.toBeInTheDocument();
  });
});
