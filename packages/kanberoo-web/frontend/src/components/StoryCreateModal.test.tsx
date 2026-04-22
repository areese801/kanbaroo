import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import StoryCreateModal from './StoryCreateModal';

type ResponseFactory = (input: RequestInfo | URL, init?: RequestInit) => Response;

function fetchRouter(routes: Record<string, ResponseFactory>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    for (const prefix of Object.keys(routes)) {
      if (url.startsWith(prefix)) {
        const factory = routes[prefix];
        if (!factory) {
          throw new Error(`No factory for ${prefix}`);
        }
        return factory(input, init);
      }
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function renderModal(onClose: () => void) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/workspaces/:workspaceId/board"
        element={<StoryCreateModal workspaceId="ws-1" onClose={onClose} />}
      />
      <Route path="/stories/:storyId" element={<p>Navigated to detail</p>} />
    </Routes>,
    { initialEntries: ['/workspaces/ws-1/board'] },
  );
}

describe('StoryCreateModal', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders a dialog and focuses the title input on mount', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    renderModal(() => undefined);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    await waitFor(() => {
      const title = screen.getByLabelText(/^Title$/);
      expect(document.activeElement).toBe(title);
    });
  });

  it('rejects submit with an empty title and does not POST', async () => {
    const fetchMock = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/stories': () => {
        throw new Error('should not POST on empty title');
      },
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderModal(() => undefined);

    await screen.findByRole('dialog');
    const submit = screen.getByRole('button', { name: /create story/i });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/title is required/i);
    });
    const postCalls = fetchMock.mock.calls.filter(([input]) => {
      const url = typeof input === 'string' ? input : String(input);
      return url.startsWith('/api/v1/workspaces/ws-1/stories');
    });
    expect(postCalls).toHaveLength(0);
  });

  it('POSTs, closes the modal, and navigates to the new story on success', async () => {
    const created = {
      id: 'st-new',
      workspace_id: 'ws-1',
      epic_id: null,
      human_id: 'KAN-9',
      title: 'New one',
      description: null,
      priority: 'none',
      state: 'backlog',
      state_actor_type: null,
      state_actor_id: null,
      branch_name: null,
      commit_sha: null,
      pr_url: null,
      created_at: '2026-04-22T00:00:00Z',
      updated_at: '2026-04-22T00:00:00Z',
      deleted_at: null,
      version: 1,
    };
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify(created), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    const onClose = vi.fn();
    renderModal(onClose);

    await screen.findByRole('dialog');
    const title = screen.getByLabelText(/^Title$/);
    await userEvent.type(title, 'New one');
    fireEvent.click(screen.getByRole('button', { name: /create story/i }));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
    await screen.findByText('Navigated to detail');
  });

  it('closes the modal when Escape is pressed', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    const onClose = vi.fn();
    renderModal(onClose);

    await screen.findByRole('dialog');
    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('closes the modal when the backdrop is clicked', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    const onClose = vi.fn();
    renderModal(onClose);

    await screen.findByRole('dialog');
    const backdrop = screen.getByTestId('modal-backdrop');
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });
});
