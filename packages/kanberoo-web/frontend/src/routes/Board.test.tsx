import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Story, Workspace } from '../types/api';

type DragStartEvent = { active: { id: string; data: { current: unknown } } };
type DragEndEvent = { active: { id: string; data: { current: unknown } }; over: { id: string } | null };
type DragCancelEvent = Record<string, never>;

type DragHandlers = {
  onDragStart?: (e: DragStartEvent) => void;
  onDragEnd?: (e: DragEndEvent) => void;
  onDragCancel?: (e: DragCancelEvent) => void;
};

// Hoist the shared state so the vi.mock factory (which is itself hoisted)
// can reach it.
const { dndTestHooks } = vi.hoisted(() => {
  return { dndTestHooks: { current: {} as DragHandlers } };
});

// Mock dnd-kit so the test can synthesize drag events without a real pointer
// sensor. Tests capture the DndContext handlers via `dndTestHooks.current`
// and call them directly. useDraggable / useDroppable / DragOverlay still
// return realistic shapes so the Board renders its draggable markup and
// drop-target styles without real DOM interaction.
vi.mock('@dnd-kit/core', () => {
  return {
    DndContext: ({
      children,
      onDragStart,
      onDragEnd,
      onDragCancel,
    }: {
      children: ReactNode;
      onDragStart?: (e: DragStartEvent) => void;
      onDragEnd?: (e: DragEndEvent) => void;
      onDragCancel?: (e: DragCancelEvent) => void;
    }) => {
      dndTestHooks.current = { onDragStart, onDragEnd, onDragCancel };
      return children;
    },
    DragOverlay: () => null,
    PointerSensor: class {},
    useDraggable: ({ id, data }: { id: string; data: Record<string, unknown> }) => ({
      attributes: { role: 'button', tabIndex: 0, 'aria-roledescription': 'draggable' },
      listeners: {},
      setNodeRef: () => {},
      transform: null,
      isDragging: false,
      node: { current: null },
      active: null,
      over: null,
      rect: { current: null },
      _data: { id, data },
    }),
    useDroppable: ({ id }: { id: string }) => ({
      isOver: false,
      active: null,
      node: { current: null },
      over: null,
      rect: { current: null },
      setNodeRef: () => {},
      _id: id,
    }),
    useSensor: () => ({}),
    useSensors: () => [],
  };
});

import Board from './Board';

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
    version: overrides.version ?? 1,
  };
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

function renderBoard() {
  return renderWithProviders(
    <Routes>
      <Route path="/workspaces/:workspaceId/board" element={<Board />} />
    </Routes>,
    { initialEntries: ['/workspaces/ws-1/board'] },
  );
}

function simulateDropOn(
  storyId: string,
  fromState: Story['state'],
  version: number,
  targetState: Story['state'],
): void {
  // Re-read the handlers between calls: each render of Board captures a new
  // closure over `activeCard`, so we must pick up the latest after onDragStart
  // has queued the state update.
  act(() => {
    dndTestHooks.current.onDragStart?.({
      active: {
        id: `story-${storyId}`,
        data: { current: { storyId, fromState, version } },
      },
    });
  });
  act(() => {
    dndTestHooks.current.onDragEnd?.({
      active: {
        id: `story-${storyId}`,
        data: { current: { storyId, fromState, version } },
      },
      over: { id: `column-${targetState}` },
    });
  });
}

describe('Board', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
    dndTestHooks.current = {};
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

    const backlog = screen.getByRole('region', { name: /^Backlog,/ });
    const todo = screen.getByRole('region', { name: /^To do,/ });
    const inProgress = screen.getByRole('region', { name: /^In progress,/ });
    const inReview = screen.getByRole('region', { name: /^In review,/ });
    const done = screen.getByRole('region', { name: /^Done,/ });

    const columns = screen.getAllByRole('region');
    expect(columns.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Backlog, 2 stories',
      'To do, 1 story',
      'In progress, 1 story',
      'In review, 0 stories',
      'Done, 1 story',
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
    const inProgress = screen.getByRole('region', { name: /^In progress,/ });
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
    const todo = screen.getByRole('region', { name: /^To do,/ });
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

  it('dragging a todo story into the In progress column fires the transition mutation with If-Match', async () => {
    const story = makeStory({
      id: 'st-42',
      human_id: 'KAN-42',
      title: 'Shippable',
      state: 'todo',
      version: 3,
    });
    const updated = { ...story, state: 'in_progress' as const, version: 4 };

    const postCalls: { url: string; headers: Headers; body: string | null }[] = [];
    let storiesResponse: Story[] = [story];

    globalThis.fetch = fetchRouter({
      '/api/v1/stories/st-42/transition': (_input, init) => {
        const headers = new Headers(init?.headers);
        const body = typeof init?.body === 'string' ? init.body : null;
        postCalls.push({
          url: '/api/v1/stories/st-42/transition',
          headers,
          body,
        });
        storiesResponse = [updated];
        return new Response(JSON.stringify(updated), {
          status: 200,
          headers: { 'Content-Type': 'application/json', ETag: '4' },
        });
      },
      '/api/v1/workspaces/ws-1/stories': () =>
        new Response(JSON.stringify({ items: storiesResponse, next_cursor: null }), {
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

    simulateDropOn('st-42', 'todo', 3, 'in_progress');

    await waitFor(() => {
      expect(postCalls.length).toBeGreaterThan(0);
    });
    const call = postCalls[0]!;
    expect(call.headers.get('If-Match')).toBe('3');
    expect(call.headers.get('Content-Type')).toBe('application/json');
    expect(call.body).toBe(JSON.stringify({ to_state: 'in_progress' }));
  });

  it('pressing "n" opens the story-create modal', async () => {
    const story = makeStory({ id: 'st-1', human_id: 'KAN-1', state: 'backlog' });
    globalThis.fetch = fetchRouter({
      '/api/v1/workspaces/ws-1/epics': () =>
        new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
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
    await screen.findByText('KAN-1');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'n' }));
    });
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: /new story/i })).toBeInTheDocument();
  });

  it('pressing "/" focuses the search input; typing filters visible cards', async () => {
    const stories: Story[] = [
      makeStory({ id: 'a', human_id: 'KAN-1', title: 'Shippable', state: 'backlog' }),
      makeStory({ id: 'b', human_id: 'KAN-2', title: 'Research', state: 'backlog' }),
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
    await screen.findByText('KAN-1');
    await screen.findByText('Shippable');
    expect(screen.getByText('Research')).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    });

    const input = await screen.findByRole('searchbox', { name: /search stories/i });
    await waitFor(() => {
      expect(document.activeElement).toBe(input);
    });

    await userEvent.type(input, 'ship');
    await waitFor(() => {
      expect(screen.queryByText('Research')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Shippable')).toBeInTheDocument();
  });

  it('Escape clears and hides the board search', async () => {
    const stories: Story[] = [
      makeStory({ id: 'a', human_id: 'KAN-1', title: 'Shippable', state: 'backlog' }),
      makeStory({ id: 'b', human_id: 'KAN-2', title: 'Research', state: 'backlog' }),
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
    await screen.findByText('KAN-1');

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    });
    const input = await screen.findByRole('searchbox', { name: /search stories/i });
    await userEvent.type(input, 'ship');

    act(() => {
      fireEvent.keyDown(input, { key: 'Escape' });
    });
    await waitFor(() => {
      expect(screen.queryByRole('searchbox', { name: /search stories/i })).not.toBeInTheDocument();
    });
    expect(screen.getByText('Research')).toBeInTheDocument();
  });

  it('story cards carry aria-label and aria-roledescription so screen readers announce drag', async () => {
    const story = makeStory({
      id: 'st-a11y',
      human_id: 'KAN-50',
      title: 'Accessible',
      state: 'todo',
      priority: 'high',
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
    await screen.findByText('KAN-50');

    const card = screen.getByText('Accessible').closest('article');
    expect(card).not.toBeNull();
    expect(card).toHaveAttribute('aria-roledescription', 'draggable story');
    expect(card).toHaveAttribute(
      'aria-label',
      expect.stringContaining('KAN-50'),
    );
  });

  it('dragging a backlog story onto Done shows the cannot-move banner and does not POST', async () => {
    const story = makeStory({
      id: 'st-backlog',
      human_id: 'KAN-9',
      title: 'Stay backlog',
      state: 'backlog',
      version: 2,
    });
    const postCalls: string[] = [];

    globalThis.fetch = fetchRouter({
      '/api/v1/stories/': (input) => {
        postCalls.push(typeof input === 'string' ? input : input.toString());
        return new Response('{}', { status: 200 });
      },
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
    expect(await screen.findByText('KAN-9')).toBeInTheDocument();

    simulateDropOn('st-backlog', 'backlog', 2, 'done');

    await waitFor(() => {
      expect(
        screen.getByText(/cannot move a backlog story to done\./i),
      ).toBeInTheDocument();
    });
    expect(postCalls).toHaveLength(0);
  });
});
