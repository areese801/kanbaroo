import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAuthStore } from '../state/auth';
import { useCreateWorkspace, useWorkspaces } from './workspaces';
import type { Workspace } from '../types/api';

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

const WORKSPACE_FIXTURE: Workspace = {
  id: 'ws-1',
  key: 'KAN',
  name: 'Kanberoo',
  description: 'Primary workspace',
  next_issue_num: 7,
  created_at: '2026-04-22T00:00:00Z',
  updated_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
  version: 3,
};

describe('useWorkspaces', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('fetches the workspace list envelope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ items: [WORKSPACE_FIXTURE], next_cursor: null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = makeClient();
    const { result } = renderHook(() => useWorkspaces(), {
      wrapper: makeWrapper(client),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/workspaces?limit=200');
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0]?.id).toBe('ws-1');
  });
});

describe('useCreateWorkspace', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('posts the payload, then invalidates the workspaces query', async () => {
    const listCalls: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST') {
        return new Response(JSON.stringify(WORKSPACE_FIXTURE), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      listCalls.push({ url, method });
      return new Response(
        JSON.stringify({ items: [WORKSPACE_FIXTURE], next_cursor: null }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const client = makeClient();
    const wrapper = makeWrapper(client);
    const listHook = renderHook(() => useWorkspaces(), { wrapper });
    await waitFor(() => expect(listHook.result.current.isSuccess).toBe(true));
    const listCallsBefore = listCalls.length;

    const mutationHook = renderHook(() => useCreateWorkspace(), { wrapper });
    await mutationHook.result.current.mutateAsync({
      key: 'NEW',
      name: 'New workspace',
      description: null,
    });

    const postCall = fetchMock.mock.calls.find((call) => {
      const init = call[1] as RequestInit | undefined;
      return (init?.method ?? 'GET').toUpperCase() === 'POST';
    });
    expect(postCall).toBeDefined();
    const [postUrl, postInit] = postCall as [string, RequestInit];
    expect(postUrl).toBe('/api/v1/workspaces');
    expect(postInit.method).toBe('POST');
    const postHeaders = new Headers(postInit.headers);
    expect(postHeaders.get('Content-Type')).toBe('application/json');
    expect(postInit.body).toBe(
      JSON.stringify({ key: 'NEW', name: 'New workspace', description: null }),
    );

    await waitFor(() => expect(listCalls.length).toBeGreaterThan(listCallsBefore));
  });
});
