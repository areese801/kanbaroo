import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useEventStream } from './useEventStream';
import { useAuthStore } from '../state/auth';

type Listener = ((ev: MessageEvent | Event | CloseEvent) => void) | null;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = FakeWebSocket.CONNECTING;
  onopen: Listener = null;
  onmessage: Listener = null;
  onclose: Listener = null;
  onerror: Listener = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  receive(data: string): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  triggerClose(code: number, reason = ''): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.closed = true;
    const event = { code, reason, wasClean: code === 1000 } as CloseEvent;
    this.onclose?.(event);
  }

  close(code = 1000, reason = ''): void {
    if (this.closed) {
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.closed = true;
    const event = { code, reason, wasClean: code === 1000 } as CloseEvent;
    this.onclose?.(event);
  }
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

const originalWebSocket = globalThis.WebSocket;

describe('useEventStream', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket =
      FakeWebSocket as unknown as typeof WebSocket;
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
    useAuthStore.getState().clearToken();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('invalidates the stories query on a story.transitioned event for the target workspace', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    expect(socket.url).toContain('/api/v1/events?token=kbr_test_token');

    act(() => {
      socket.open();
    });

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-1',
          event_type: 'story.transitioned',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'story',
          entity_id: 'st-1',
          entity_version: 2,
          payload: { workspace_id: 'ws-1', to_state: 'in_progress' },
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['stories', 'ws-1'] });
    });
  });

  it('ignores ping keepalive frames without invalidating any queries', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(JSON.stringify({ type: 'ping', ts: '2026-04-22T00:00:00Z' }));
    });

    // Give React Query a tick to be sure no invalidation was queued.
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it('reconnects after a non-clean close with exponential backoff', async () => {
    vi.useFakeTimers();
    const client = makeClient();

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    expect(FakeWebSocket.instances.length).toBe(1);
    const first = FakeWebSocket.instances[0]!;
    act(() => first.open());

    // Simulate a transient transport close (not 1000).
    act(() => {
      first.triggerClose(1006);
    });

    // First reconnect should fire within 2s (initial backoff 1s + <=20% jitter).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(FakeWebSocket.instances.length).toBe(2);
    const second = FakeWebSocket.instances[1]!;
    expect(second.url).toContain('/api/v1/events?token=kbr_test_token');
  });

  it('does not reconnect when closed with policy violation (1008); clears the token', async () => {
    const client = makeClient();
    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.triggerClose(1008, 'bad token');
    });

    // Wait a moment; no new socket should be created.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(FakeWebSocket.instances.length).toBe(1);
    expect(useAuthStore.getState().token).toBe(null);
  });

  it('invalidates per-story keys on story.commented', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-c1',
          event_type: 'story.commented',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'story',
          entity_id: 'st-9',
          entity_version: 3,
          payload: { workspace_id: 'ws-1', story_id: 'st-9' },
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['comments', 'st-9'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-9'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story', 'st-9'] });
  });

  it('invalidates comments and audit on comment.updated', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-c2',
          event_type: 'comment.updated',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'comment',
          entity_id: 'c-1',
          entity_version: 2,
          payload: { story_id: 'st-7' },
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['comments', 'st-7'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-7'] });
  });

  it('invalidates comments and audit on comment.deleted', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-c3',
          event_type: 'comment.deleted',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'comment',
          entity_id: 'c-2',
          entity_version: 3,
          payload: { story_id: 'st-7' },
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['comments', 'st-7'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-7'] });
  });

  it('invalidates story-tags, story, and audit on story.tag_added', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-t1',
          event_type: 'story.tag_added',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'story',
          entity_id: 'st-5',
          entity_version: 2,
          payload: { workspace_id: 'ws-1', tag_id: 'tag-a' },
        }),
      );
    });

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story-tags', 'st-5'] }),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story', 'st-5'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-5'] });
  });

  it('invalidates story-tags, story, and audit on story.tag_removed', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-t2',
          event_type: 'story.tag_removed',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'story',
          entity_id: 'st-5',
          entity_version: 3,
          payload: { workspace_id: 'ws-1', tag_id: 'tag-a' },
        }),
      );
    });

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story-tags', 'st-5'] }),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story', 'st-5'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-5'] });
  });

  it('invalidates the specific story key on story.updated', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-u',
          event_type: 'story.updated',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'story',
          entity_id: 'st-3',
          entity_version: 4,
          payload: { workspace_id: 'ws-1' },
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['story', 'st-3'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['audit', 'story', 'st-3'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['stories', 'ws-1'] });
  });

  it('invalidates workspace queries when a matching workspace event arrives', async () => {
    const client = makeClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    renderHook(() => useEventStream('ws-1'), { wrapper: makeWrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const socket = FakeWebSocket.instances[0]!;
    act(() => socket.open());

    act(() => {
      socket.receive(
        JSON.stringify({
          event_id: 'evt-2',
          event_type: 'workspace.updated',
          occurred_at: '2026-04-22T00:00:00Z',
          actor_type: 'human',
          actor_id: 'tok-1',
          entity_type: 'workspace',
          entity_id: 'ws-1',
          entity_version: 5,
          payload: {},
        }),
      );
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['workspaces'] });
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['workspace', 'ws-1'] });
  });
});
