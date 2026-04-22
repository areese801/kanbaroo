import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import Board from './Board';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Story, Workspace } from '../types/api';

const WORKSPACE: Workspace = {
  id: 'ws-1',
  key: 'KAN',
  name: 'Kanberoo',
  description: null,
  next_issue_num: 1,
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 1,
};

function makeStory(overrides: Partial<Story>): Story {
  return {
    id: overrides.id ?? 'st-0',
    workspace_id: 'ws-1',
    epic_id: null,
    human_id: overrides.human_id ?? 'KAN-0',
    title: overrides.title ?? 'Story title',
    description: null,
    priority: overrides.priority ?? 'none',
    state: overrides.state ?? 'backlog',
    state_actor_type: overrides.state_actor_type ?? null,
    state_actor_id: overrides.state_actor_id ?? null,
    branch_name: null,
    commit_sha: null,
    pr_url: null,
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    deleted_at: null,
    version: 1,
  };
}

type ResponseFactory = () => Response;

function fetchRouter(routes: Record<string, ResponseFactory>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    for (const prefix of Object.keys(routes)) {
      if (url.startsWith(prefix)) {
        const factory = routes[prefix];
        if (!factory) {
          throw new Error(`No factory for ${prefix}`);
        }
        return factory();
      }
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function renderBoard() {
  return renderWithProviders(
    <Routes>
      <Route path="/workspaces/:workspaceId/board" element={<Board />} />
    </Routes>,
    { initialEntries: ['/workspaces/ws-1/board'] },
  );
}

describe('Board', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders five columns in the pinned order with counts', async () => {
    const stories: Story[] = [
      makeStory({ id: 'a', human_id: 'KAN-1', state: 'backlog' }),
      makeStory({ id: 'b', human_id: 'KAN-2', state: 'backlog' }),
      makeStory({ id: 'c', human_id: 'KAN-3', state: 'todo' }),
      makeStory({ id: 'd', human_id: 'KAN-4', state: 'in_progress' }),
      makeStory({ id: 'e', human_id: 'KAN-5', state: 'done' }),
    ];

    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify({ items: stories, next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/tags': () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1': () =>
        new Response(JSON.stringify(WORKSPACE), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    renderBoard();

    expect(await screen.findByText('KAN-1')).toBeInTheDocument();

    const backlog = screen.getByRole('region', { name: 'Backlog' });
    const todo = screen.getByRole('region', { name: 'To do' });
    const inProgress = screen.getByRole('region', { name: 'In progress' });
    const inReview = screen.getByRole('region', { name: 'In review' });
    const done = screen.getByRole('region', { name: 'Done' });

    const columns = screen.getAllByRole('region');
    expect(columns.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Backlog',
      'To do',
      'In progress',
      'In review',
      'Done',
    ]);

    expect(within(backlog).getByText('(2)')).toBeInTheDocument();
    expect(within(todo).getByText('(1)')).toBeInTheDocument();
    expect(within(inProgress).getByText('(1)')).toBeInTheDocument();
    expect(within(inReview).getByText('(0)')).toBeInTheDocument();
    expect(within(done).getByText('(1)')).toBeInTheDocument();
  });

  it('renders a story in the In progress column with its human_id, title, priority chip, and actor badge', async () => {
    const story = makeStory({
      id: 'story-42',
      human_id: 'KAN-42',
      title: 'Ship the thing',
      state: 'in_progress',
      priority: 'high',
      state_actor_type: 'claude',
      state_actor_id: 'actor-1',
    });

    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify({ items: [story], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/tags': () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1': () =>
        new Response(JSON.stringify(WORKSPACE), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    renderBoard();

    expect(await screen.findByText('KAN-42')).toBeInTheDocument();
    const inProgress = screen.getByRole('region', { name: 'In progress' });
    expect(within(inProgress).getByText('KAN-42')).toBeInTheDocument();
    expect(within(inProgress).getByText('Ship the thing')).toBeInTheDocument();
    expect(within(inProgress).getByText('High')).toBeInTheDocument();
    expect(within(inProgress).getByText('Claude')).toBeInTheDocument();
  });

  it('omits the priority chip for stories with priority "none"', async () => {
    const story = makeStory({
      id: 'story-plain',
      human_id: 'KAN-7',
      title: 'Quiet story',
      state: 'todo',
      priority: 'none',
    });

    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify({ items: [story], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/tags': () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1': () =>
        new Response(JSON.stringify(WORKSPACE), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    renderBoard();

    expect(await screen.findByText('Quiet story')).toBeInTheDocument();
    const todo = screen.getByRole('region', { name: 'To do' });
    expect(within(todo).getByText('Quiet story')).toBeInTheDocument();
    expect(within(todo).queryByText('Low')).not.toBeInTheDocument();
    expect(within(todo).queryByText('Medium')).not.toBeInTheDocument();
    expect(within(todo).queryByText('High')).not.toBeInTheDocument();
    expect(within(todo).queryByText('None')).not.toBeInTheDocument();
  });

  it('renders an error banner with a retry button when stories fail to load', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify({ error: { code: 'boom', message: 'nope' } }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1/tags': () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      '/api/v1/workspaces/ws-1': () =>
        new Response(JSON.stringify(WORKSPACE), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    }) as unknown as typeof fetch;

    renderBoard();

    await waitFor(() => {
      expect(screen.getByText(/could not load stories/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
