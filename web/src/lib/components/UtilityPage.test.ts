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
    vi.restoreAllMocks();
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

  it('previews Flatten completely and submits a separate confirmed apply job', async () => {
    const requests: { url: string; method: string; body?: any }[] = [];
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      requests.push({ url, method, body });
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
      if (url.includes('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [
        { name: 'demo', path: '/workspace/demo', kind: 'directory', files: 0, directories: 1, has_children: true }
      ] }), { status: 200 });
      if (url.endsWith('/utility/jobs') && method === 'POST') {
        return new Response(JSON.stringify({
          id: body.flatten_action === 'preview' ? 'preview-1' : 'apply-1',
          kind: 'utility', status: 'dispatched'
        }), { status: 200 });
      }
      if (url.endsWith('/jobs/preview-1')) return new Response(JSON.stringify({
        id: 'preview-1', kind: 'utility', status: 'succeeded',
        payload: { utility: 'flatten', flatten_action: 'preview' },
        result: { value: {
          summary: { moves: 1, deleted: 0, skipped: 1, action_count: 1 },
          details: [{ folder: '/workspace/demo', flatten_preview: {
            fingerprint: 'a'.repeat(64), action_count: 1, moves: 1, deleted: 0, skipped: 1,
            passes: [{ index: 1, actions: [
              { type: 'move', folder: 'single', source: 'single/file.txt', destination: 'file.txt', collision: false },
              { type: 'skip_multiple', folder: 'many', item_count: 2 }
            ] }]
          } }]
        } }
      }), { status: 200 });
      if (url.endsWith('/jobs/apply-1')) return new Response(JSON.stringify({
        id: 'apply-1', kind: 'utility', status: 'succeeded', result: { value: {} }
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(UtilityPage);
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih demo' }));
    await fireEvent.change(screen.getByRole('combobox', { name: 'Jenis operasi' }), {
      target: { value: 'flatten' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Preview Flatten' }));

    expect(await screen.findByRole('region', { name: 'Preview Flatten' })).toBeTruthy();
    expect(screen.getByText(/single\/file\.txt/)).toBeTruthy();
    expect(screen.getByText(/many/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Terapkan Flatten' }));
    await waitFor(() => expect(requests.some((item) =>
      item.url.endsWith('/utility/jobs') && item.body?.flatten_action === 'apply'
    )).toBe(true));
    const applyRequest = requests.find((item) =>
      item.url.endsWith('/utility/jobs') && item.body?.flatten_action === 'apply'
    );
    expect(applyRequest?.body?.folders).toEqual(['/workspace/demo']);
    expect(applyRequest?.body?.flatten_fingerprints).toEqual({ '/workspace/demo': 'a'.repeat(64) });
    expect(confirm).toHaveBeenCalledOnce();
    expect(await screen.findByText('Flatten selesai.')).toBeTruthy();
  });
});
