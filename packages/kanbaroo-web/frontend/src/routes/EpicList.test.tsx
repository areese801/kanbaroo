import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import EpicList, { countStoriesByEpic } from './EpicList';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Epic, Story, Workspace } from '../types/api';

const WORKSPACE: Workspace = {
  id: 'ws-1',
  key: 'KAN',
  name: 'Kanbaroo',
  description: null,
  next_issue_num: 1,
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 1,
};

function makeEpic(overrides: Partial<Epic>): Epic {
  return {
    id: overrides.id ?? 'ep-0',
    workspace_id: 'ws-1',
    human_id: overrides.human_id ?? 'KAN-0',
    title: overrides.title ?? 'Epic title',
    description: null,
    state: overrides.state ?? 'open',
    created_at: '2026-04-22T00:00:00Z',
    updated_at: overrides.updated_at ?? '2026-04-23T00:00:00Z',
    deleted_at: null,
    version: 1,
  };
}

function makeStory(overrides: Partial<Story>): Story {
  return {
    id: overrides.id ?? 'st-0',
    workspace_id: 'ws-1',
    epic_id: overrides.epic_id ?? null,
    human_id: overrides.human_id ?? 'KAN-0',
    title: 'Story title',
    description: null,
    priority: 'none',
    state: overrides.state ?? 'backlog',
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
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

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

function renderEpics() {
  return renderWithProviders(
    <Routes>
      <Route path="/workspaces/:workspaceId/epics" element={<EpicList />} />
      <Route path="/workspaces/:workspaceId/board" element={<div>board route</div>} />
    </Routes>,
    { initialEntries: ['/workspaces/ws-1/epics'] },
  );
}

function rowFor(humanId: string): HTMLElement {
  const cell = screen.getByText(humanId);
  const row = cell.closest('tr');
  if (!row) {
    throw new Error(`No row for ${humanId}`);
  }
  return row;
}

function cellsOf(row: HTMLElement): string[] {
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent ?? '');
}

describe('countStoriesByEpic', () => {
  it('counts totals and open stories per epic, treating only done as closed', () => {
    const counts = countStoriesByEpic([
      makeStory({ id: 'a', epic_id: 'ep-1', state: 'backlog' }),
      makeStory({ id: 'b', epic_id: 'ep-1', state: 'todo' }),
      makeStory({ id: 'c', epic_id: 'ep-1', state: 'in_progress' }),
      makeStory({ id: 'd', epic_id: 'ep-1', state: 'in_review' }),
      makeStory({ id: 'e', epic_id: 'ep-1', state: 'done' }),
      makeStory({ id: 'f', epic_id: 'ep-2', state: 'done' }),
      makeStory({ id: 'g', epic_id: null, state: 'todo' }),
    ]);
    expect(counts.get('ep-1')).toEqual({ total: 5, open: 4 });
    expect(counts.get('ep-2')).toEqual({ total: 1, open: 0 });
    expect(counts.size).toBe(2);
  });
});

describe('EpicList', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders the pinned column headers in order', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ items: [makeEpic({ id: 'ep-1', human_id: 'KAN-1' })], next_cursor: null }),
      '/api/v1/workspaces/ws-1/stories': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    }) as unknown as typeof fetch;

    renderEpics();

    expect(await screen.findByText('KAN-1')).toBeInTheDocument();
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(['Key', 'Title', 'State', 'Stories', 'Open', 'Last updated']);
  });

  it('shows total and open counts per epic from one workspace-wide story fetch', async () => {
    const epics = [
      makeEpic({ id: 'ep-1', human_id: 'KAN-1', title: 'Mixed', updated_at: '2026-04-23T01:02:03Z' }),
      makeEpic({ id: 'ep-2', human_id: 'KAN-2', title: 'Finished', state: 'closed' }),
      makeEpic({ id: 'ep-3', human_id: 'KAN-3', title: 'Empty' }),
    ];
    const stories = [
      makeStory({ id: 'a', epic_id: 'ep-1', state: 'backlog' }),
      makeStory({ id: 'b', epic_id: 'ep-1', state: 'in_progress' }),
      makeStory({ id: 'c', epic_id: 'ep-1', state: 'done' }),
      makeStory({ id: 'd', epic_id: 'ep-2', state: 'done' }),
      makeStory({ id: 'e', epic_id: 'ep-2', state: 'done' }),
      makeStory({ id: 'f', epic_id: null, state: 'todo' }),
    ];
    const fetchMock = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () => jsonResponse({ items: epics, next_cursor: null }),
      '/api/v1/workspaces/ws-1/stories': () =>
        jsonResponse({ items: stories, next_cursor: null }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderEpics();

    expect(await screen.findByText('Mixed')).toBeInTheDocument();
    await waitFor(() => {
      expect(cellsOf(rowFor('KAN-1'))).toEqual([
        'KAN-1',
        'Mixed',
        'open',
        '3',
        '2',
        '2026-04-23T01:02:03Z',
      ]);
    });
    expect(cellsOf(rowFor('KAN-2')).slice(0, 5)).toEqual(['KAN-2', 'Finished', 'closed', '2', '0']);
    expect(cellsOf(rowFor('KAN-3')).slice(3, 5)).toEqual(['0', '0']);

    const storyRequests = fetchMock.mock.calls.filter(([input]) => {
      const url = typeof input === 'string' ? input : input.toString();
      return url.startsWith('/api/v1/workspaces/ws-1/stories');
    });
    expect(storyRequests).toHaveLength(1);
    expect(await screen.findByText('(KAN)', { exact: false })).toBeInTheDocument();
  });

  it('counts stories across every page of a paginated story list', async () => {
    const epics = [makeEpic({ id: 'ep-1', human_id: 'KAN-1', title: 'Big' })];
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () => jsonResponse({ items: epics, next_cursor: null }),
      '/api/v1/workspaces/ws-1/stories': (input) => {
        const url = typeof input === 'string' ? input : input.toString();
        const cursor = new URL(url, 'http://localhost').searchParams.get('cursor');
        if (cursor === null) {
          return jsonResponse({
            items: [
              makeStory({ id: 'a', epic_id: 'ep-1', state: 'todo' }),
              makeStory({ id: 'b', epic_id: 'ep-1', state: 'done' }),
            ],
            next_cursor: 'next',
          });
        }
        return jsonResponse({
          items: [makeStory({ id: 'c', epic_id: 'ep-1', state: 'in_review' })],
          next_cursor: null,
        });
      },
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    }) as unknown as typeof fetch;

    renderEpics();

    expect(await screen.findByText('Big')).toBeInTheDocument();
    await waitFor(() => {
      expect(cellsOf(rowFor('KAN-1')).slice(3, 5)).toEqual(['3', '2']);
    });
  });

  it('renders an empty-state hint when the workspace has no epics', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/stories': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    }) as unknown as typeof fetch;

    renderEpics();

    expect(await screen.findByText(/no epics yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows an error panel with retry when the epics request fails', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ error: { code: 'internal', message: 'boom' } }, 500),
      '/api/v1/workspaces/ws-1/stories': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    }) as unknown as typeof fetch;

    renderEpics();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not load epics/i);
    expect(within(alert).getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('links back to the board', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/stories': () => jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
    }) as unknown as typeof fetch;

    renderEpics();
    await screen.findByText(/no epics yet/i);

    const user = userEvent.setup();
    await user.click(screen.getByRole('link', { name: 'Board' }));
    expect(await screen.findByText('board route')).toBeInTheDocument();
  });
});
