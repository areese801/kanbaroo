import { apiFetch, type ApiFetchInit } from '../api/client';
import type { Paginated } from '../types/api';

const MAX_ERROR_BODY_CHARS = 240;

export type ApiError = Error & { status: number };

type ApiErrorBody = {
  error?: {
    message?: string;
    code?: string;
  };
};

export function makeApiError(status: number, statusText: string, body: string): ApiError {
  let message = `API ${status}: ${statusText || 'request failed'}`;
  if (body) {
    try {
      const parsed = JSON.parse(body) as ApiErrorBody;
      if (parsed.error?.message) {
        message = `${message} ${parsed.error.message}`;
      } else if (body.length <= MAX_ERROR_BODY_CHARS) {
        message = `${message} ${body}`;
      }
    } catch {
      if (body.length <= MAX_ERROR_BODY_CHARS) {
        message = `${message} ${body}`;
      }
    }
  }
  const error = new Error(message) as ApiError;
  error.status = status;
  return error;
}

export async function apiRequest(
  path: string,
  init: ApiFetchInit = {},
): Promise<Response> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let body = '';
    try {
      body = await response.text();
    } catch {
      // ignore: body was not readable
    }
    throw makeApiError(response.status, response.statusText, body);
  }
  return response;
}

export async function requestJson<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const response = await apiRequest(path, init);
  return (await response.json()) as T;
}

export const PAGE_LIMIT = 200;

/**
 * Walk a cursor-paginated list endpoint until `next_cursor` is null and
 * return every item concatenated in server order.
 *
 * `basePath` is the endpoint path without a query string; `params` are
 * the fixed query parameters for every page. The server-issued cursor is
 * appended as `cursor=` on each subsequent request.
 */
export async function requestAllPages<T>(
  basePath: string,
  params: Record<string, string> = {},
): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (;;) {
    const search = new URLSearchParams({ limit: String(PAGE_LIMIT), ...params });
    if (cursor !== null) {
      search.set('cursor', cursor);
    }
    const envelope: Paginated<T> = await requestJson<Paginated<T>>(
      `${basePath}?${search.toString()}`,
    );
    items.push(...envelope.items);
    cursor = envelope.next_cursor ?? null;
    if (cursor === null) {
      break;
    }
  }
  return items;
}
