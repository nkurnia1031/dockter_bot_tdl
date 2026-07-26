export type ApiError = Error & { code?: string; status?: number };

const csrf = () => document.cookie.split('; ').find((part) => part.startsWith('tme3_csrf='))?.split('=').slice(1).join('') || '';

export async function api<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('x-csrf-token', csrf());
  let response = await fetch(`/api/v1${path}`, { ...init, method, headers, credentials: 'same-origin', cache: 'no-store' });
  if (response.status === 401 && !retried && !path.startsWith('/auth/browser/')) {
    const refresh = await fetch('/api/v1/auth/browser/refresh', { method: 'POST', credentials: 'same-origin', headers: { 'x-csrf-token': csrf() } });
    if (refresh.ok) return api<T>(path, init, true);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body?.error?.message || `HTTP ${response.status}`) as ApiError;
    error.code = body?.error?.code; error.status = response.status; throw error;
  }
  return response.json() as Promise<T>;
}

export async function post<T>(path: string, value?: unknown): Promise<T> {
  const result = await api<T>(path, { method: 'POST', body: value === undefined ? undefined : JSON.stringify(value) });
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('tme3:data-mutated', { detail: { path } }));
  return result;
}
export const put = <T>(path: string, value: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(value) });
export const patch = <T>(path: string, value: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(value) });
export const remove = <T>(path: string) => api<T>(path, { method: 'DELETE' });
