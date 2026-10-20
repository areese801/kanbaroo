import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAuthStore } from '../state/auth';
import { useEpicsByWorkspace } from './epics';
import type { Epic } from '../types/api';

function makeEpic(overrides: Partial<Epic> = {}): Epic {
  return {
    id: overrides.id ?? 'ep-1',
    workspace_id: 'ws-1',
    human_id: overrides.human_id ?? 'KAN-1',
    title: overrides.title ?? 'Epic',
    description: null,
    state: overrides.state ?? 'open',
    created_at: '2026-04-22T00:00:00Z',
    updated_at: '2026-04-22T00:00:00Z',
    deleted_at: null,
    version: 1,
  };
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe('useEpicsByWorkspace', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('walks next_cursor until exhausted and concatenates every page in order', async () => {
    const requestedUrls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      requestedUrls.push(url);
      const cursor = new URL(url, 'http://localhost').searchParams.get('cursor');
      const body =
        cursor === null
          ? { items: [makeEpic({ id: 'ep-1' }), makeEpic({ id: 'ep-2' })], next_cursor: 'page-2' }
          : { items: [makeEpic({ id: 'ep-3' })], next_cursor: null };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = makeClient();
    const { result } = renderHook(() => useEpicsByWorkspace('ws-1'), {
      wrapper: makeWrapper(client),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((epic) => epic.id)).toEqual(['ep-1', 'ep-2', 'ep-3']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestedUrls).toEqual([
      '/api/v1/workspaces/ws-1/epics?limit=200',
      '/api/v1/workspaces/ws-1/epics?limit=200&cursor=page-2',
    ]);
  });

  it('does not fetch when the workspace id is missing', () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const client = makeClient();
    const { result } = renderHook(() => useEpicsByWorkspace(undefined), {
      wrapper: makeWrapper(client),
    });
    expect(result.current.isPending).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
