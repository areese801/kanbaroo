import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import AppHeader from './AppHeader';

function renderHeader() {
  return renderWithProviders(
    <Routes>
      <Route element={<AppHeader />}>
        <Route path="/workspaces" element={<p>workspaces body</p>} />
      </Route>
    </Routes>,
    { initialEntries: ['/workspaces'] },
  );
}

describe('AppHeader keyboard help modal', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ) as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('opens the keyboard-help modal when "?" is pressed', async () => {
    renderHeader();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }));
    });
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText(/keyboard shortcuts/i)).toBeInTheDocument();
  });

  it('closes the keyboard-help modal when Escape is pressed', async () => {
    renderHeader();
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }));
    });
    await screen.findByRole('dialog');
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
