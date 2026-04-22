import { apiFetch, type ApiFetchInit } from '../api/client';

const MAX_ERROR_BODY_CHARS = 240;

export async function requestJson<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) {
    let message = `API ${response.status}: ${response.statusText || 'request failed'}`;
    try {
      const body = await response.text();
      if (body && body.length <= MAX_ERROR_BODY_CHARS) {
        message = `${message} ${body}`;
      }
    } catch {
      // ignore: error body was not readable
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}
