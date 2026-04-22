import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '../state/auth';

export type EventStreamStatus = 'idle' | 'connecting' | 'open' | 'disconnected';

export type EventStreamState = {
  status: EventStreamStatus;
  reconnectAttempts: number;
};

type ServerEvent = {
  event_id: string;
  event_type: string;
  occurred_at: string;
  actor_type: string;
  actor_id: string;
  entity_type: string;
  entity_id: string;
  entity_version: number | null;
  payload: Record<string, unknown>;
};

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;
const POLICY_VIOLATION_CLOSE = 1008;
const NORMAL_CLOSE = 1000;

function wsUrlFor(token: string): string {
  const base =
    typeof window !== 'undefined' && window.location
      ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
      : 'ws://localhost';
  return `${base}/api/v1/events?token=${encodeURIComponent(token)}`;
}

function computeBackoff(attempt: number): number {
  const raw = Math.min(MAX_BACKOFF_MS, INITIAL_BACKOFF_MS * 2 ** attempt);
  const jitter = Math.random() * Math.min(500, raw * 0.2);
  return Math.round(raw + jitter);
}

export function useEventStream(workspaceId: string | null | undefined): EventStreamState {
  const queryClient = useQueryClient();
  const token = useAuthStore((s) => s.token);
  const clearToken = useAuthStore((s) => s.clearToken);
  const [state, setState] = useState<EventStreamState>({
    status: 'idle',
    reconnectAttempts: 0,
  });

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;
    if (!workspaceId || !token) {
      setState({ status: 'idle', reconnectAttempts: 0 });
      return () => {
        unmountedRef.current = true;
      };
    }

    let attempts = 0;

    const connect = (): void => {
      if (unmountedRef.current) {
        return;
      }
      setState({ status: 'connecting', reconnectAttempts: attempts });
      const url = wsUrlFor(token);
      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => {
        if (unmountedRef.current) {
          return;
        }
        setState({ status: 'open', reconnectAttempts: 0 });
      };

      socket.onmessage = (message) => {
        if (unmountedRef.current) {
          return;
        }
        attempts = 0;
        const raw = typeof message.data === 'string' ? message.data : '';
        if (!raw) {
          return;
        }
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch (error) {
          console.warn('useEventStream: dropping unparseable frame', error);
          return;
        }
        if (!parsed || typeof parsed !== 'object') {
          return;
        }
        const frame = parsed as Record<string, unknown>;
        if (frame.type === 'ping') {
          return;
        }
        const event = frame as unknown as ServerEvent;
        if (event.entity_type === 'story') {
          const payloadWorkspaceId = (event.payload as { workspace_id?: unknown }).workspace_id;
          if (typeof payloadWorkspaceId === 'string' && payloadWorkspaceId === workspaceId) {
            queryClient.invalidateQueries({ queryKey: ['stories', workspaceId] });
          }
          return;
        }
        if (event.entity_type === 'workspace' && event.entity_id === workspaceId) {
          queryClient.invalidateQueries({ queryKey: ['workspaces'] });
          queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] });
        }
      };

      socket.onclose = (closeEvent) => {
        socketRef.current = null;
        if (unmountedRef.current) {
          return;
        }
        if (closeEvent.code === NORMAL_CLOSE) {
          setState({ status: 'idle', reconnectAttempts: 0 });
          return;
        }
        if (closeEvent.code === POLICY_VIOLATION_CLOSE) {
          setState({ status: 'disconnected', reconnectAttempts: attempts });
          clearToken();
          return;
        }
        attempts += 1;
        setState({ status: 'connecting', reconnectAttempts: attempts });
        const delay = computeBackoff(attempts - 1);
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        // Errors are followed by a close event; let onclose drive the reconnect.
      };
    };

    connect();

    return () => {
      unmountedRef.current = true;
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        try {
          socket.close(NORMAL_CLOSE, 'unmounting');
        } catch {
          // ignore close errors during cleanup
        }
      }
    };
  }, [workspaceId, token, queryClient, clearToken]);

  return state;
}
