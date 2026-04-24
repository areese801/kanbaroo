import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAuthStore } from '../state/auth';
import {
  useAddStoryTags,
  useCreateStory,
  useRemoveStoryTag,
  useStory,
  useTransitionStory,
  useUpdateStory,
  type TransitionStoryError,
} from './stories';
import type { ApiError } from './http';
import type { Story } from '../types/api';

function makeStory(overrides: Partial<Story> = {}): Story {
  return {
    id: overrides.id ?? 'st-1',
    workspace_id: overrides.workspace_id ?? 'ws-1',
    epic_id: null,
    human_id: overrides.human_id ?? 'KAN-1',
    title: overrides.title ?? 'Test story',
    description: null,
    priority: overrides.priority ?? 'none',
    state: overrides.state ?? 'todo',
    state_actor_type: null,
    state_actor_id: null,
    branch_name: null,
    commit_sha: null,
    pr_url: null,
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    deleted_at: null,
    version: overrides.version ?? 3,
  };
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 5 * 60 * 1000, staleTime: 60 * 1000 },
      mutations: { retry: false },
    },
  });
}

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useTransitionStory', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('optimistically updates the cache, then replaces with the server response on success', async () => {
    const initial = makeStory({ id: 'st-1', state: 'todo', version: 3 });
    const serverUpdated = makeStory({ id: 'st-1', state: 'in_progress', version: 4 });

    const client = makeClient();
    client.setQueryData<Story[]>(['stories', 'ws-1'], [initial]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-1/transition');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('POST');
      const headers = new Headers(init?.headers);
      expect(headers.get('If-Match')).toBe('3');
      expect(headers.get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(JSON.stringify({ to_state: 'in_progress' }));
      return new Response(JSON.stringify(serverUpdated), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '4' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useTransitionStory('ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ storyId: 'st-1', expectedVersion: 3, toState: 'in_progress' });

    await waitFor(() => {
      const cached = client.getQueryData<Story[]>(['stories', 'ws-1']);
      expect(cached?.[0]?.state).toBe('in_progress');
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const final = client.getQueryData<Story[]>(['stories', 'ws-1']);
    expect(final?.[0]?.version).toBe(4);
    expect(final?.[0]?.state).toBe('in_progress');
  });

  it('rolls back to the snapshot when the server returns 412', async () => {
    const initial = makeStory({ id: 'st-2', state: 'in_progress', version: 7 });
    const client = makeClient();
    client.setQueryData<Story[]>(['stories', 'ws-1'], [initial]);

    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { code: 'version_conflict', message: 'If-Match mismatch' } }),
        { status: 412, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useTransitionStory('ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ storyId: 'st-2', expectedVersion: 7, toState: 'in_review' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const rolledBack = client.getQueryData<Story[]>(['stories', 'ws-1']);
    expect(rolledBack?.[0]?.state).toBe('in_progress');
    expect(rolledBack?.[0]?.version).toBe(7);
    const err = result.current.error as TransitionStoryError | null;
    expect(err?.status).toBe(412);
  });

  it('rolls back to the snapshot when the server rejects an illegal transition with 422', async () => {
    const initial = makeStory({ id: 'st-3', state: 'backlog', version: 1 });
    const client = makeClient();
    client.setQueryData<Story[]>(['stories', 'ws-1'], [initial]);

    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { code: 'validation_error', message: 'illegal transition' } }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useTransitionStory('ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ storyId: 'st-3', expectedVersion: 1, toState: 'done' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const rolledBack = client.getQueryData<Story[]>(['stories', 'ws-1']);
    expect(rolledBack?.[0]?.state).toBe('backlog');
    const err = result.current.error as TransitionStoryError | null;
    expect(err?.status).toBe(422);
  });
});

describe('useStory', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('fetches a single story by id', async () => {
    const story = makeStory({ id: 'st-one' });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-one');
      return new Response(JSON.stringify(story), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const client = makeClient();
    const { result } = renderHook(() => useStory('st-one'), {
      wrapper: makeWrapper(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe('st-one');
  });
});

describe('useUpdateStory', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('patches the story with If-Match and replaces the cached story on success', async () => {
    const initial = makeStory({ id: 'st-5', title: 'Old', version: 2 });
    const updated = makeStory({ id: 'st-5', title: 'New', version: 3 });
    const client = makeClient();
    client.setQueryData<Story>(['story', 'st-5'], initial);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-5');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('PATCH');
      const headers = new Headers(init?.headers);
      expect(headers.get('If-Match')).toBe('2');
      return new Response(JSON.stringify(updated), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '3' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useUpdateStory('st-5', 'ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ expectedVersion: 2, payload: { title: 'New' } });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const cached = client.getQueryData<Story>(['story', 'st-5']);
    expect(cached?.title).toBe('New');
    expect(cached?.version).toBe(3);
  });

  it('rolls back the cache and exposes .status=412 on conflict', async () => {
    const initial = makeStory({ id: 'st-6', title: 'Stable', version: 7 });
    const client = makeClient();
    client.setQueryData<Story>(['story', 'st-6'], initial);

    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { code: 'version_conflict', message: 'mismatch' } }),
        { status: 412, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useUpdateStory('st-6', 'ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ expectedVersion: 7, payload: { title: 'Stomp' } });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const rolledBack = client.getQueryData<Story>(['story', 'st-6']);
    expect(rolledBack?.title).toBe('Stable');
    expect((result.current.error as ApiError | null)?.status).toBe(412);
  });
});

describe('useCreateStory', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('POSTs the payload and invalidates the workspace stories cache on success', async () => {
    const created = makeStory({ id: 'st-new', human_id: 'KAN-99', title: 'Added' });
    const client = makeClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/workspaces/ws-1/stories');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('POST');
      const headers = new Headers(init?.headers);
      expect(headers.get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(
        JSON.stringify({ title: 'Added', priority: 'high' }),
      );
      return new Response(JSON.stringify(created), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useCreateStory('ws-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ title: 'Added', priority: 'high' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.id).toBe('st-new');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['stories', 'ws-1'] });
  });
});

describe('useAddStoryTags / useRemoveStoryTag', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('POSTs the tag ids and invalidates story-tags + story + audit', async () => {
    const story = makeStory({ id: 'st-tag', version: 1 });
    const client = makeClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-tag/tags');
      expect(init?.body).toBe(JSON.stringify({ tag_ids: ['tag-a'] }));
      return new Response(JSON.stringify(story), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useAddStoryTags('st-tag', 'ws-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ tag_ids: ['tag-a'] });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['story-tags', 'st-tag'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['story', 'st-tag'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-tag'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['stories', 'ws-1'] });
  });

  it('DELETEs the association and invalidates the same keys', async () => {
    const client = makeClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-tag/tags/tag-a');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('DELETE');
      return new Response(null, { status: 204 });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useRemoveStoryTag('st-tag', 'ws-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ tagId: 'tag-a' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['story-tags', 'st-tag'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['story', 'st-tag'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-tag'] });
  });
});
