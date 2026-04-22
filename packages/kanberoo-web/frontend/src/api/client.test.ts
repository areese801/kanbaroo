import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, setUnauthorizedHandler } from './client';
import { useAuthStore } from '../state/auth';

function mockFetchResponse(status: number, body: unknown = {}): Response {
  const payload = JSON.stringify(body);
  return new Response(payload, {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('apiFetch', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().clearToken();
    localStorage.clear();
    setUnauthorizedHandler(null);
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('attaches Authorization header when a token is set', async () => {
    useAuthStore.getState().setToken('kbr_unit_test_token');
    const fetchMock = vi.fn().mockResolvedValue(mockFetchResponse(200, { items: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const response = await apiFetch('/api/v1/workspaces');

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [url, init] = call as [string, RequestInit];
    expect(url).toBe('/api/v1/workspaces');
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer kbr_unit_test_token');
  });

  it('omits Authorization when the token is null', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockFetchResponse(200));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await apiFetch('/api/v1/workspaces');

    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const [, init] = call as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.has('Authorization')).toBe(false);
  });

  it('clears the store and calls the unauthorized handler on a 401', async () => {
    useAuthStore.getState().setToken('kbr_stale_token');
    const fetchMock = vi
      .fn()
      .mockResolvedValue(mockFetchResponse(401, { error: { code: 'unauthorized', message: 'bad token' } }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const handler = vi.fn();
    setUnauthorizedHandler(handler);

    const response = await apiFetch('/api/v1/workspaces');

    expect(response.status).toBe(401);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().token).toBeNull();
  });
});
