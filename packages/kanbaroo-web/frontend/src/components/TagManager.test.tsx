import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TagManager from './TagManager';
import { useAuthStore } from '../state/auth';
import { renderWithProviders } from '../test/render';
import type { Tag } from '../types/api';

type ResponseFactory = (input: RequestInfo | URL, init?: RequestInit) => Response;

function fetchRouter(routes: Record<string, ResponseFactory>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const keys = Object.keys(routes).sort((a, b) => b.length - a.length);
    for (const prefix of keys) {
      if (url.startsWith(prefix)) {
        const factory = routes[prefix];
        if (!factory) {
          throw new Error(`No factory for ${prefix}`);
        }
        return factory(input, init);
      }
    }
    throw new Error(`Unexpected fetch ${url}`);
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const TAG_RED: Tag = {
  id: 'tag-red',
  workspace_id: 'ws-1',
  name: 'red',
  color: '#ff0000',
  created_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
};

const TAG_BLUE: Tag = {
  id: 'tag-blue',
  workspace_id: 'ws-1',
  name: 'blue',
  color: null,
  created_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
};

const TAG_GREEN: Tag = {
  id: 'tag-green',
  workspace_id: 'ws-1',
  name: 'green',
  color: null,
  created_at: '2026-04-22T00:00:00Z',
  deleted_at: null,
};

describe('TagManager', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().setToken('kbr_test_token');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    useAuthStore.getState().clearToken();
    vi.restoreAllMocks();
  });

  it('renders attached tags as chips', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [TAG_RED, TAG_BLUE] }),
      '/api/v1/workspaces/ws-1/tags': () =>
        jsonResponse({ items: [TAG_RED, TAG_BLUE, TAG_GREEN] }),
    }) as unknown as typeof fetch;

    renderWithProviders(<TagManager storyId="st-1" workspaceId="ws-1" />);

    const chips = await screen.findAllByText(/red|blue/);
    expect(chips.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByLabelText('Remove tag red')).toBeInTheDocument();
    expect(screen.getByLabelText('Remove tag blue')).toBeInTheDocument();
  });

  it('add-tag popover lists workspace tags minus currently attached', async () => {
    globalThis.fetch = fetchRouter({
      '/api/v1/stories/st-1/tags': () => jsonResponse({ items: [TAG_RED] }),
      '/api/v1/workspaces/ws-1/tags': () =>
        jsonResponse({ items: [TAG_RED, TAG_BLUE, TAG_GREEN] }),
    }) as unknown as typeof fetch;

    renderWithProviders(<TagManager storyId="st-1" workspaceId="ws-1" />);

    const user = userEvent.setup();
    const addButton = await screen.findByRole('button', { name: 'Add tag' });
    await user.click(addButton);

    const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
    const names = within(dialog).getAllByRole('button', { name: /blue|green|red/ });
    const labels = names.map((el) => el.textContent?.trim());
    expect(labels).toContain('blue');
    expect(labels).toContain('green');
    expect(labels).not.toContain('red');
  });

  it('creating a new tag POSTs the workspace tags endpoint then POSTs the story tags endpoint', async () => {
    const calls: { url: string; method: string; body: string | null }[] = [];
    const createdTag: Tag = {
      id: 'tag-new',
      workspace_id: 'ws-1',
      name: 'fresh',
      color: null,
      created_at: '2026-04-22T00:00:00Z',
      deleted_at: null,
    };
    globalThis.fetch = fetchRouter({
      '/api/v1/stories/st-1/tags': (_input, init) => {
        const method = (init?.method ?? 'GET').toUpperCase();
        if (method === 'POST') {
          calls.push({
            url: '/api/v1/stories/st-1/tags',
            method,
            body: typeof init?.body === 'string' ? init.body : null,
          });
          return jsonResponse({});
        }
        return jsonResponse({ items: [] });
      },
      '/api/v1/workspaces/ws-1/tags': (_input, init) => {
        const method = (init?.method ?? 'GET').toUpperCase();
        if (method === 'POST') {
          calls.push({
            url: '/api/v1/workspaces/ws-1/tags',
            method,
            body: typeof init?.body === 'string' ? init.body : null,
          });
          return jsonResponse(createdTag, 201);
        }
        return jsonResponse({ items: [] });
      },
    }) as unknown as typeof fetch;

    renderWithProviders(<TagManager storyId="st-1" workspaceId="ws-1" />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add tag' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add tag' });
    await user.click(within(dialog).getByRole('button', { name: 'Create new tag' }));
    await user.type(within(dialog).getByLabelText(/name/i), 'fresh');
    await user.click(within(dialog).getByRole('button', { name: 'Create and add' }));

    await waitFor(() => {
      const urls = calls.map((c) => c.url);
      expect(urls).toContain('/api/v1/workspaces/ws-1/tags');
      expect(urls).toContain('/api/v1/stories/st-1/tags');
    });
    const storyAdd = calls.find((c) => c.url === '/api/v1/stories/st-1/tags');
    expect(storyAdd?.body).toContain('tag-new');
  });
});
