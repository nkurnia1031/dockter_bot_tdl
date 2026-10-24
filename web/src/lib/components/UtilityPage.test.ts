import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import UtilityPage from './UtilityPage.svelte';
import { session } from '$lib/session.svelte';

function readinessResponse(status: 'ready' | 'not_ready' = 'ready') {
  return new Response(JSON.stringify({
    profiles: [],
    runtime_readiness: {
      checked_at: '2026-10-23T10:00:00Z',
      workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T10:00:00Z', reason_code: '' }],
      cells: [{ worker: 'local', profile: null, runtime: 'utility', status, checked_at: '2026-10-23T10:00:00Z', reason_code: status === 'ready' ? '' : 'UTILITY_SCRIPT_MISSING' }]
    }
  }), { status: 200 });
}

describe('UtilityPage access controls', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it('uses the selected worker and submits without manual target verification', async () => {
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local', enabled: true }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return readinessResponse();
      if (url.endsWith('/utility/folders')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.includes('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [] }), { status: 200 });
      if (url.endsWith('/utility/jobs') && method === 'POST') return new Response(JSON.stringify({ id: 'utility-1', kind: 'utility', status: 'queued' }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    await session.restore();
    render(UtilityPage);
    expect(await screen.findByRole('combobox', { name: 'Worker target' })).toBeTruthy();
    expect(screen.queryByRole('status', { name: 'Kesiapan Utility' })).toBeNull();
    await fireEvent.click(await screen.findByRole('button', { name: 'Pilih' }));
    const submit = screen.getByRole('button', { name: 'Jalankan utility' }) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    await fireEvent.click(submit);

    expect(requests.some((item) => item.url.includes('/context/verify'))).toBe(false);
    expect(requests.some((item) => item.url.endsWith('/utility/jobs') && item.method === 'POST')).toBe(true);
  });

  it('does not gate Utility on a Profile scan runtime snapshot', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local', enabled: true }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return readinessResponse('not_ready');
      if (url.endsWith('/utility/folders')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.includes('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    await session.restore();
    render(UtilityPage);
    expect(screen.queryByRole('status', { name: 'Kesiapan Utility' })).toBeNull();
    await fireEvent.click(await screen.findByRole('button', { name: 'Pilih' }));
    const submit = screen.getByRole('button', { name: 'Jalankan utility' }) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    await fireEvent.click(submit);
    expect(requests.some((url) => url.endsWith('/utility/jobs'))).toBe(true);
  });
});
