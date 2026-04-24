import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAuthStore } from '../state/auth';
import {
  useComments,
  useCreateComment,
  useDeleteComment,
  useUpdateComment,
} from './comments';
import type { ApiError } from './http';
import type { Comment } from '../types/api';

function makeComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: overrides.id ?? 'c-1',
    story_id: overrides.story_id ?? 'st-1',
    parent_id: overrides.parent_id ?? null,
    body: overrides.body ?? 'hello',
    actor_type: overrides.actor_type ?? 'human',
    actor_id: overrides.actor_id ?? 'tok-1',
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    deleted_at: null,
    version: overrides.version ?? 1,
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

describe('useComments', () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('fetches the comment list envelope for a story', async () => {
    const comment = makeComment();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-1/comments?limit=200');
      return new Response(JSON.stringify({ items: [comment] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const client = makeClient();
    const { result } = renderHook(() => useComments('st-1'), {
      wrapper: makeWrapper(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.length).toBe(1);
  });
});

describe('useCreateComment', () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('POSTs the new comment and invalidates comments + audit', async () => {
    const comment = makeComment({ id: 'c-new', body: 'hi' });
    const client = makeClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/stories/st-1/comments');
      expect(init?.body).toBe(JSON.stringify({ body: 'hi', parent_id: 'c-parent' }));
      return new Response(JSON.stringify(comment), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useCreateComment('st-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ body: 'hi', parent_id: 'c-parent' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['comments', 'st-1'] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-1'] });
  });
});

describe('useUpdateComment', () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('optimistically updates then replaces with the server response on success', async () => {
    const initial = makeComment({ id: 'c-1', body: 'old', version: 2 });
    const updated = makeComment({ id: 'c-1', body: 'new', version: 3 });
    const client = makeClient();
    client.setQueryData<Comment[]>(['comments', 'st-1'], [initial]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/comments/c-1');
      const headers = new Headers(init?.headers);
      expect(headers.get('If-Match')).toBe('2');
      return new Response(JSON.stringify(updated), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ETag: '3' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useUpdateComment('st-1'), {
      wrapper: makeWrapper(client),
    });

    result.current.mutate({ commentId: 'c-1', expectedVersion: 2, body: 'new' });

    await waitFor(() => {
      const cached = client.getQueryData<Comment[]>(['comments', 'st-1']);
      expect(cached?.[0]?.body).toBe('new');
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const final = client.getQueryData<Comment[]>(['comments', 'st-1']);
    expect(final?.[0]?.version).toBe(3);
  });

  it('rolls back on 412 and exposes .status', async () => {
    const initial = makeComment({ id: 'c-1', body: 'original', version: 9 });
    const client = makeClient();
    client.setQueryData<Comment[]>(['comments', 'st-1'], [initial]);

    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { code: 'version_conflict', message: 'bad version' } }),
        { status: 412, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useUpdateComment('st-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ commentId: 'c-1', expectedVersion: 9, body: 'stomp' });

    await waitFor(() => expect(result.current.isError).toBe(true));
    const rolledBack = client.getQueryData<Comment[]>(['comments', 'st-1']);
    expect(rolledBack?.[0]?.body).toBe('original');
    expect((result.current.error as ApiError | null)?.status).toBe(412);
  });
});

describe('useDeleteComment', () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('optimistically removes the comment and invalidates on success', async () => {
    const a = makeComment({ id: 'c-a' });
    const b = makeComment({ id: 'c-b' });
    const client = makeClient();
    client.setQueryData<Comment[]>(['comments', 'st-1'], [a, b]);

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/comments/c-a');
      const headers = new Headers(init?.headers);
      expect(headers.get('If-Match')).toBe('1');
      expect((init?.method ?? 'GET').toUpperCase()).toBe('DELETE');
      return new Response(null, { status: 204 });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useDeleteComment('st-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ commentId: 'c-a', expectedVersion: 1 });

    await waitFor(() => {
      const cached = client.getQueryData<Comment[]>(['comments', 'st-1']);
      expect(cached?.length).toBe(1);
      expect(cached?.[0]?.id).toBe('c-b');
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('rolls back on 412 and exposes .status', async () => {
    const a = makeComment({ id: 'c-a' });
    const client = makeClient();
    client.setQueryData<Comment[]>(['comments', 'st-1'], [a]);

    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ error: { code: 'version_conflict', message: 'bad version' } }),
        { status: 412, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useDeleteComment('st-1'), {
      wrapper: makeWrapper(client),
    });
    result.current.mutate({ commentId: 'c-a', expectedVersion: 1 });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const rolledBack = client.getQueryData<Comment[]>(['comments', 'st-1']);
    expect(rolledBack?.[0]?.id).toBe('c-a');
    expect((result.current.error as ApiError | null)?.status).toBe(412);
  });
});
