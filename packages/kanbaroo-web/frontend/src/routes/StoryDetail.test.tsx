import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import AppHeader from '../components/AppHeader';
import StoryDetail from './StoryDetail';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Epic, Story, Workspace } from '../types/api';

const STORY: Story = {
  id: 'st-1',
  workspace_id: 'ws-1',
  epic_id: null,
  human_id: 'KAN-7',
  title: 'Ship the thing',
  description: '# Plan\n\nDo the work.',
  priority: 'high',
  state: 'in_progress',
  state_actor_type: 'claude',
  state_actor_id: 'tok-claude',
  branch_name: 'feat/x',
  commit_sha: '1234567890abcdef',
  pr_url: 'https://example.com/pr/1',
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 4,
};

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

const EPIC: Epic = {
  id: 'ep-1',
  workspace_id: 'ws-1',
  human_id: 'EPIC-1',
  title: 'Ship phase 2',
  description: null,
  state: 'open',
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 1,
};

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

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route element={<AppHeader />}>
        <Route path="/stories/:storyId" element={<StoryDetail />} />
      </Route>
    </Routes>,
    { initialEntries: ['/stories/st-1'] },
  );
}

describe('StoryDetail', () => {
  const originalFetch = globalThis.fetch;
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
    class NoopSocket {
      url: string;
      readyState = 0;
      onopen: unknown = null;
      onmessage: unknown = null;
      onclose: unknown = null;
      onerror: unknown = null;
      constructor(url: string) {
        this.url = url;
      }
      close(): void {
        // no-op
      }
    }
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket =
      NoopSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  const baseRouter = (overrides: Record<string, ResponseFactory> = {}) =>
    fetchRouter({
      '/api/v1/stories/st-1/comments': () => jsonResponse({ items: [] }),
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ items: [EPIC], next_cursor: null }),
      '/api/v1/workspaces/ws-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
      '/api/v1/stories/st-1': (_input, init) => {
        if ((init?.method ?? 'GET').toUpperCase() === 'PATCH') {
          return jsonResponse({ ...STORY, title: 'Renamed', version: STORY.version + 1 });
        }
        return jsonResponse(STORY);
      },
      ...overrides,
    });

  it('renders the title, markdown description, and metadata in display mode', async () => {
    globalThis.fetch = baseRouter() as unknown as typeof fetch;
    const { container } = renderDetail();

    expect(await screen.findByRole('heading', { name: 'Ship the thing' })).toBeInTheDocument();
    const chip = container.querySelector('.story-human-id');
    expect(chip?.textContent).toBe('KAN-7');
    expect(screen.getByText('High')).toBeInTheDocument();
    expect(screen.getByText('In progress')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument();
    expect(screen.getByText('1234567890ab')).toBeInTheDocument();
    const prLink = screen.getByRole('link', { name: 'https://example.com/pr/1' });
    expect(prLink).toHaveAttribute('target', '_blank');
  });

  it('renders the Edit button with the primary class so it stands out from chrome', async () => {
    globalThis.fetch = baseRouter() as unknown as typeof fetch;
    renderDetail();

    const editButton = await screen.findByRole('button', { name: 'Edit' });
    expect(editButton).toHaveClass('primary');
  });

  it('clicking Edit then Save PATCHes the story and returns to display mode', async () => {
    const patchBodies: string[] = [];
    let currentStory: Story = STORY;
    const router = fetchRouter({
      '/api/v1/stories/st-1/comments': () => jsonResponse({ items: [] }),
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ items: [EPIC], next_cursor: null }),
      '/api/v1/workspaces/ws-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
      '/api/v1/stories/st-1': (_input, init) => {
        if ((init?.method ?? 'GET').toUpperCase() === 'PATCH') {
          patchBodies.push(typeof init?.body === 'string' ? init.body : '');
          currentStory = {
            ...currentStory,
            title: 'Renamed',
            version: currentStory.version + 1,
          };
          return jsonResponse(currentStory);
        }
        return jsonResponse(currentStory);
      },
    });
    globalThis.fetch = router as unknown as typeof fetch;

    renderDetail();

    expect(await screen.findByRole('heading', { name: 'Ship the thing' })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Edit' }));

    const titleInput = screen.getByLabelText('Title') as HTMLInputElement;
    expect(titleInput.value).toBe('Ship the thing');
    await user.clear(titleInput);
    await user.type(titleInput, 'Renamed');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(patchBodies.length).toBe(1));
    expect(patchBodies[0]).toContain('"title":"Renamed"');
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Renamed' })).toBeInTheDocument(),
    );
  });

  it('freezes the base version when entering edit mode so a concurrent refetch does not unstale the If-Match', async () => {
    const patchHeaders: Headers[] = [];
    let currentStory: Story = STORY;
    const router = fetchRouter({
      '/api/v1/stories/st-1/comments': () => jsonResponse({ items: [] }),
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ items: [EPIC], next_cursor: null }),
      '/api/v1/workspaces/ws-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
      '/api/v1/stories/st-1': (_input, init) => {
        if ((init?.method ?? 'GET').toUpperCase() === 'PATCH') {
          patchHeaders.push(new Headers(init?.headers));
          currentStory = {
            ...currentStory,
            title: 'Stomp',
            version: currentStory.version + 1,
          };
          return jsonResponse(currentStory);
        }
        return jsonResponse(currentStory);
      },
    });
    globalThis.fetch = router as unknown as typeof fetch;

    const { queryClient } = renderDetail();
    expect(await screen.findByRole('heading', { name: 'Ship the thing' })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Edit' }));

    const titleInput = screen.getByLabelText('Title') as HTMLInputElement;
    await user.clear(titleInput);
    await user.type(titleInput, 'Stomp');

    // Simulate tab A's save landing on tab B mid-edit: a story.updated event
    // arrives, the cache is invalidated, and the next fetch returns version
    // N+1 before the user clicks Save. Without the freeze, the save would
    // read the fresh version and succeed (no 412).
    act(() => {
      queryClient.setQueryData<Story>(['story', 'st-1'], {
        ...STORY,
        version: STORY.version + 1,
      });
    });

    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Save changes' }));
    });

    await waitFor(() => expect(patchHeaders.length).toBe(1));
    expect(patchHeaders[0]!.get('If-Match')).toBe(String(STORY.version));
    expect(patchHeaders[0]!.get('If-Match')).not.toBe(String(STORY.version + 1));
  });

  it('surfaces the conflict modal on 412 and reverts to display mode on OK', async () => {
    let patchCalls = 0;
    const router = fetchRouter({
      '/api/v1/stories/st-1/comments': () => jsonResponse({ items: [] }),
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [], next_cursor: null }),
      '/api/v1/workspaces/ws-1/epics': () =>
        jsonResponse({ items: [EPIC], next_cursor: null }),
      '/api/v1/workspaces/ws-1/tags': () => jsonResponse({ items: [] }),
      '/api/v1/workspaces/ws-1': () => jsonResponse(WORKSPACE),
      '/api/v1/stories/st-1': (_input, init) => {
        if ((init?.method ?? 'GET').toUpperCase() === 'PATCH') {
          patchCalls += 1;
          return jsonResponse(
            { error: { code: 'version_conflict', message: 'stale version' } },
            412,
          );
        }
        return jsonResponse(STORY);
      },
    });
    globalThis.fetch = router as unknown as typeof fetch;

    renderDetail();
    expect(await screen.findByRole('heading', { name: 'Ship the thing' })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Edit' }));

    const titleInput = screen.getByLabelText('Title') as HTMLInputElement;
    await user.clear(titleInput);
    await user.type(titleInput, 'Stomp');
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Save changes' }));
    });

    await waitFor(() => expect(patchCalls).toBe(1));
    const dialog = await screen.findByRole('dialog', { name: 'Conflict' });
    expect(within(dialog).getByText(/changed on the server/i)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'OK' }));
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Conflict' })).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole('heading', { name: 'Ship the thing' }),
    ).toBeInTheDocument();
  });

  it('renders a breadcrumb with the workspace label and the story human id', async () => {
    globalThis.fetch = baseRouter() as unknown as typeof fetch;
    renderDetail();
    expect(await screen.findByRole('heading', { name: 'Ship the thing' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Kanbaroo (KAN)')).toBeInTheDocument();
    });
    const matches = screen.getAllByText('KAN-7');
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});
