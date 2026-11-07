import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DownloadsPage from './DownloadsPage.svelte';
import { session } from '$lib/session.svelte';

describe('DownloadsPage profile filter', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function flushPromises() {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  }

  it('keeps artifact and profile catalogs manual while idle', async () => {
    vi.useFakeTimers();
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles: [{ name: 'default', workers: ['local'], exclusive_worker: 'local' }]
      }), { status: 200 });
      if (url.includes('/downloads/artifacts?')) return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);
    await flushPromises();
    const profileInitial = requests.filter((url) => url.endsWith('/profiles/local')).length;
    const artifactsInitial = requests.filter((url) => url.includes('/downloads/artifacts?')).length;

    await vi.advanceTimersByTimeAsync(30_000);
    expect(requests.filter((url) => url.endsWith('/profiles/local'))).toHaveLength(profileInitial);
    expect(requests.filter((url) => url.includes('/downloads/artifacts?'))).toHaveLength(artifactsInitial);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh katalog unduhan' }));
    await flushPromises();
    expect(requests.filter((url) => url.endsWith('/profiles/local'))).toHaveLength(profileInitial + 1);
    expect(requests.filter((url) => url.includes('/downloads/artifacts?'))).toHaveLength(artifactsInitial + 2);
  });

  it('sends global reconcile scope and filters as query parameters', async () => {
    const requests: Array<{ url: string; method: string; body?: BodyInit | null }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: init?.body });
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', enabled: true }, { name: 'remote-1', enabled: true }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [
        { name: 'archive', workers: ['remote-1'], exclusive_worker: 'remote-1' }
      ] }), { status: 200 });
      if (url.includes('/downloads/artifacts?')) return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      if (url.includes('/downloads/artifacts/reconcile')) return new Response(JSON.stringify({ jobs: [] }), { status: 200 });
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);
    const profilePicker = await screen.findByLabelText('Profile') as HTMLSelectElement;
    await fireEvent.change(profilePicker, { target: { value: 'archive' } });
    const workerPicker = screen.getByLabelText('Worker / VPS') as HTMLSelectElement;
    await fireEvent.change(workerPicker, { target: { value: 'remote-1' } });
    await fireEvent.click(await screen.findByRole('button', { name: /Reconcile global/ }));

    await waitFor(() => expect(requests.some(({ url, method }) =>
      method === 'POST' && url.includes('/downloads/artifacts/reconcile')
    )).toBe(true));
    const request = requests.find(({ url, method }) =>
      method === 'POST' && url.includes('/downloads/artifacts/reconcile')
    );
    if (!request) throw new Error('Global reconcile request was not sent.');
    const params = new URL(request.url, 'http://localhost').searchParams;
    expect(params.get('scope')).toBe('global');
    expect(params.get('profile')).toBe('archive');
    expect(params.get('worker')).toBe('remote-1');
    expect(request?.body).toBeUndefined();
  });

  it('applies the pending status before the global 200-item limit', async () => {
    const target = {
      id: 'remote2-pending',
      filename: 'restore-me.json',
      profile: 'irang',
      worker: 'remote-2',
      status: 'pending',
      available: true,
      created_at: '2026-11-06T17:49:31Z'
    };
    const recentDownloaded = Array.from({ length: 200 }, (_, index) => ({
      id: `downloaded-${index}`,
      filename: `recent-${index}.json`,
      profile: 'default',
      worker: 'local',
      status: 'downloaded',
      available: true,
      created_at: `2026-11-07T${String(23 - Math.floor(index / 60)).padStart(2, '0')}:${String(59 - index % 60).padStart(2, '0')}:00Z`
    }));
    const catalog = [...recentDownloaded, target];
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default', 'irang']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', enabled: true }, { name: 'remote-2', enabled: true }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [] }), { status: 200 });
      if (url.includes('/downloads/artifacts?')) {
        const params = new URL(url, 'http://localhost').searchParams;
        const archived = params.get('archived') === 'true';
        const status = params.get('status');
        const matching = archived ? [] : catalog.filter(item => !status || item.status === status);
        const offset = Number(params.get('offset') || 0);
        const limit = Number(params.get('limit') || 50);
        return new Response(JSON.stringify({ items: matching.slice(offset, offset + limit), total: matching.length }), { status: 200 });
      }
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);

    expect(await screen.findByText('restore-me.json')).toBeTruthy();
    expect(requests.some(url => new URL(url, 'http://localhost').searchParams.get('status') === 'pending')).toBe(true);
  });

  it('offers only verified catalog profiles and reloads with the selected catalog value', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push(`${init?.method || 'GET'} ${url}`);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'identity-profile', worker_route: 'local' },
        profiles: ['identity-profile', 'stale-identity-profile']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local' },
        { name: 'remote-1', url: 'https://worker.example' }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [
        { name: 'remote-only', workers: ['remote-1'], exclusive_worker: 'remote-1' }
      ] }), { status: 200 });
      if (url.includes('/downloads/artifacts?')) return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);

    const profilePicker = await screen.findByLabelText('Profile') as HTMLSelectElement;
    expect([...profilePicker.options].map((option) => option.value)).toEqual(['', 'remote-only']);
    expect(profilePicker.innerHTML).toContain('remote-only (remote-1)');
    await fireEvent.change(profilePicker, { target: { value: 'remote-only' } });

    await waitFor(() => expect(requests.some((request) => request.includes('profile=remote-only'))).toBe(true));
  });

  it('keeps artifact actions available when the saved Profile scan is not ready', async () => {
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
        { name: 'local', enabled: true }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles: [{ name: 'default', workers: ['local'], exclusive_worker: 'local' }],
        runtime_readiness: {
          checked_at: '2026-10-24T10:00:00Z',
          workers: [{ name: 'local', status: 'success' }],
          cells: [{ worker: 'local', profile: 'default', runtime: 'download', status: 'not_ready', checked_at: '2026-10-24T10:00:00Z', reason_code: 'PROFILE_CANARY_DOWNLOAD_FAILED' }]
        }
      }), { status: 200 });
      if (url.includes('/downloads/artifacts?') && url.includes('archived=false')) return new Response(JSON.stringify({ items: [
        { id: 'artifact-1', filename: 'backup.json', profile: 'default', worker: 'local', status: 'pending', available: true }
      ], total: 1 }), { status: 200 });
      if (url.includes('/downloads/artifacts?')) return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      if (url.endsWith('/downloads/batch') && method === 'POST') return new Response(JSON.stringify({ groups: [] }), { status: 200 });
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);

    expect(await screen.findByText('Scan terakhir: belum siap')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Mulai' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(false);
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai' }));
    await waitFor(() => expect(requests.some(({ url, method }) => url.endsWith('/downloads/batch') && method === 'POST')).toBe(true));
  });
});
