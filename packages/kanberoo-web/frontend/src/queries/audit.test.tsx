import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAuthStore } from '../state/auth';
import { useStoryAudit } from './audit';

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

describe('useStoryAudit', () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('fetches the audit envelope for the story', async () => {
    const event = {
      id: 'a-1',
      occurred_at: '2026-04-22T00:00:00Z',
      actor_type: 'human',
      actor_id: 'tok-1',
      entity_type: 'story',
      entity_id: 'st-1',
      action: 'updated',
      diff: { before: { title: 'Old' }, after: { title: 'New' } },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      expect(url).toBe('/api/v1/audit/entity/story/st-1?limit=200');
      return new Response(JSON.stringify({ items: [event], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const client = makeClient();
    const { result } = renderHook(() => useStoryAudit('st-1'), {
      wrapper: makeWrapper(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.length).toBe(1);
    expect(result.current.data?.[0]?.action).toBe('updated');
  });

  it('returns an empty array when the API reports no events', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const client = makeClient();
    const { result } = renderHook(() => useStoryAudit('st-empty'), {
      wrapper: makeWrapper(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
