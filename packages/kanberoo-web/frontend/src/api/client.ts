import { useAuthStore } from '../state/auth';

export type UnauthorizedHandler = () => void;

let onUnauthorized: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

export type ApiFetchInit = RequestInit & {
  token?: string | null;
};

export async function apiFetch(path: string, init: ApiFetchInit = {}): Promise<Response> {
  const { token: overrideToken, headers: initHeaders, ...rest } = init;
  const token = overrideToken !== undefined ? overrideToken : useAuthStore.getState().token;
  const headers = new Headers(initHeaders);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(path, { ...rest, headers });
  if (response.status === 401) {
    useAuthStore.getState().clearToken();
    if (onUnauthorized) {
      onUnauthorized();
    }
  }
  return response;
}
