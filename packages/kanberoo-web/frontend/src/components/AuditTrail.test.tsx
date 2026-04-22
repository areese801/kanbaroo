import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import AuditTrail from './AuditTrail';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { AuditEvent } from '../types/api';

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

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AuditTrail', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders a state_changed event with before and after states', async () => {
    const event: AuditEvent = {
      id: 'a-1',
      occurred_at: '2026-04-22T00:00:00Z',
      actor_type: 'claude',
      actor_id: 'tok-c',
      entity_type: 'story',
      entity_id: 'st-1',
      action: 'state_changed',
      diff: {
        before: { state: 'todo' },
        after: { state: 'in_progress' },
      },
    };
    globalThis.fetch = fetchRouter({
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [event], next_cursor: null }),
    }) as unknown as typeof fetch;

    renderWithProviders(<AuditTrail storyId="st-1" />);

    await waitFor(() => expect(screen.getByText('todo')).toBeInTheDocument());
    expect(screen.getByText('in_progress')).toBeInTheDocument();
    expect(screen.getByText(/Claude moved this from/)).toBeInTheDocument();
  });

  it('renders an updated event by listing the changed field names', async () => {
    const event: AuditEvent = {
      id: 'a-2',
      occurred_at: '2026-04-22T00:00:00Z',
      actor_type: 'human',
      actor_id: 'tok-h',
      entity_type: 'story',
      entity_id: 'st-1',
      action: 'updated',
      diff: {
        before: { title: 'Old', priority: 'none' },
        after: { title: 'New', priority: 'high' },
      },
    };
    globalThis.fetch = fetchRouter({
      '/api/v1/audit/entity/story/st-1': () =>
        jsonResponse({ items: [event], next_cursor: null }),
    }) as unknown as typeof fetch;

    renderWithProviders(<AuditTrail storyId="st-1" />);

    await waitFor(() =>
      expect(screen.getByText(/Human edited/)).toBeInTheDocument(),
    );
    expect(screen.getByText('title')).toBeInTheDocument();
    expect(screen.getByText('priority')).toBeInTheDocument();
  });

  it('renders an empty state when the API returns no events', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/audit/entity/story/st-empty': () =>
        jsonResponse({ items: [], next_cursor: null }),
    }) as unknown as typeof fetch;

    renderWithProviders(<AuditTrail storyId="st-empty" />);

    await waitFor(() =>
      expect(screen.getByText(/no audit events yet/i)).toBeInTheDocument(),
    );
  });
});
