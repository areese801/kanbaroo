import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import WorkspaceList from './WorkspaceList';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Workspace } from '../types/api';

const WS_ALPHA: Workspace = {
  id: 'ws-1',
  key: 'KAN',
  name: 'Kanberoo',
  description: 'Primary workspace',
  next_issue_num: 1,
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 1,
};

const WS_BETA: Workspace = {
  ...WS_ALPHA,
  id: 'ws-2',
  key: 'BETA',
  name: 'Beta',
  description: null,
};

function renderList() {
  return renderWithProviders(
    <Routes>
      <Route path="/workspaces" element={<WorkspaceList />} />
      <Route path="/workspaces/:workspaceId/board" element={<div>board route</div>} />
    </Routes>,
    { initialEntries: ['/workspaces'] },
  );
}

describe('WorkspaceList', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders each workspace as a row', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ items: [WS_ALPHA, WS_BETA], next_cursor: null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ) as unknown as typeof fetch;

    renderList();

    expect(await screen.findByText('Kanberoo')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('KAN')).toBeInTheDocument();
    expect(screen.getByText('BETA')).toBeInTheDocument();
    expect(screen.getByText('Primary workspace')).toBeInTheDocument();
  });

  it('renders an empty-state hint when no workspaces exist', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ) as unknown as typeof fetch;

    renderList();

    expect(await screen.findByText(/no workspaces yet/i)).toBeInTheDocument();
  });

  it('submits the create form with the trimmed payload and resets inputs', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url === '/api/v1/workspaces' && method === 'POST') {
        return new Response(JSON.stringify(WS_BETA), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const user = userEvent.setup();
    renderList();
    await screen.findByText(/no workspaces yet/i);

    await user.type(screen.getByLabelText(/key/i), '  BETA  ');
    await user.type(screen.getByLabelText(/name/i), '  Beta  ');
    await user.type(screen.getByLabelText(/description/i), '  the beta  ');
    await user.click(screen.getByRole('button', { name: /create workspace/i }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((call) => {
        const init = call[1] as RequestInit | undefined;
        return (init?.method ?? 'GET').toUpperCase() === 'POST';
      });
      expect(postCall).toBeDefined();
    });

    const postCall = fetchMock.mock.calls.find((call) => {
      const init = call[1] as RequestInit | undefined;
      return (init?.method ?? 'GET').toUpperCase() === 'POST';
    });
    const [, postInit] = postCall as [string, RequestInit];
    expect(postInit.body).toBe(
      JSON.stringify({ key: 'BETA', name: 'Beta', description: 'the beta' }),
    );

    await waitFor(() =>
      expect((screen.getByLabelText(/key/i) as HTMLInputElement).value).toBe(''),
    );
    expect((screen.getByLabelText(/name/i) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/description/i) as HTMLInputElement).value).toBe('');
  });

  it('renders the error state when the query errors', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: 'server_error', message: 'boom' } }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    ) as unknown as typeof fetch;

    renderList();

    expect(await screen.findByText(/could not load workspaces/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
