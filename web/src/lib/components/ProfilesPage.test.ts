import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ProfilesPage from './ProfilesPage.svelte';

describe('ProfilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('scans local profiles only after selecting a worker and pressing Scan', async () => {
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [
          { name: 'local', enabled: true, selected: true },
          { name: 'remote-2', enabled: true, selected: false }
        ] }), { status: 200 });
      }
      if (url === '/api/v1/workers/remote-2/profiles/scan' && method === 'POST') {
        return new Response(JSON.stringify({
          worker: 'remote-2', checked_at: '2026-10-12T05:00:00+00:00', items: [{
            name: 'irang', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' },
              { name: 'future_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-12T05:00:00+00:00' }
          }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    expect(screen.getByRole('link', { name: /Kelola Vault/ }).getAttribute('href')).toBe('/profiles/vault/');
    expect(requests.some((item) => item.url.includes('/profiles/scan'))).toBe(false);

    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));

    expect(await screen.findByText('irang')).toBeTruthy();
    expect(screen.getByText(/Download.*Siap/)).toBeTruthy();
    expect(screen.getByText(/Export.*Siap/)).toBeTruthy();
    expect(screen.getByText(/future_session.*Siap/)).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Lane Upload irang' }).textContent).toMatch(/Lane Upload.*Siap/s);
    expect(screen.getByText(/Hasil scan.*remote-2/)).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Adopsi profil irang dari remote-2 ke Vault' })).toBeTruthy();
    expect(requests).toContainEqual({ url: '/api/v1/workers/remote-2/profiles/scan', method: 'POST' });

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang worker' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/hasil scan sebelumnya dihapus/i);
    expect(screen.queryByText('irang')).toBeNull();
    expect(requests.filter((item) => item.url.includes('/profiles/scan'))).toHaveLength(1);
  });

  it('adopts a verified local profile into Vault without triggering distribution', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: init?.body ? String(init.body) : undefined });
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url.endsWith('/profiles/scan')) return new Response(JSON.stringify({
        worker: 'local', checked_at: '2026-10-15T00:00:00+00:00', items: [{
          name: 'archive', ready: true, deletable: true, reason_codes: [], checks: [
            { name: 'identity', ready: true, code: 'OK' },
            { name: 'root_session', ready: true, code: 'OK' },
            { name: 'user1_session', ready: true, code: 'OK' }
          ], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' }
        }], pending_identity_cleanup: []
      }), { status: 200 });
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url === '/api/v1/profiles/management') return new Response(JSON.stringify({ items: [
        { name: 'archive', vault: false, status: 'legacy' }
      ] }), { status: 200 });
      if (url === '/api/v1/profiles/archive/adopt' && method === 'POST') return new Response(JSON.stringify({ id: 'adopt-1', status: 'validating' }), { status: 200 });
      if (url === '/api/v1/profiles/provisionings/adopt-1') return new Response(JSON.stringify({
        id: 'adopt-1', profile: 'archive', source: 'adoption', status: 'stored', error: '', workers: []
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Adopsi profil archive dari local ke Vault' }));

    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('worker lain tidak akan diubah'));
    expect(requests).toContainEqual({
      url: '/api/v1/profiles/archive/adopt', method: 'POST', body: JSON.stringify({ worker: 'local' })
    });
    expect(await screen.findByText('Bundle tersimpan di Vault; belum didistribusikan')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Adopsi profil archive dari local ke Vault' })).toBeNull();
    expect(requests.some((request) => /sync|distribut|install_profile_bundle/i.test(request.url))).toBe(false);
  });

  it('shows worker failure and retries only after the operator presses Scan again', async () => {
    const requests: string[] = [];
    let scans = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      requests.push(`${(init?.method || 'GET').toUpperCase()} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-1', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/workers/remote-1/profiles/scan') {
        scans += 1;
        if (scans === 1) {
          return new Response(JSON.stringify({
            error: { code: 'WORKER_UNAVAILABLE', message: 'Worker remote-1 tidak dapat dihubungi.' }
          }), { status: 503 });
        }
        return new Response(JSON.stringify({
          worker: 'remote-1', checked_at: '2026-10-12T05:10:00+00:00', items: []
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-1' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-1' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/Worker remote-1 sedang offline/);
    expect(scans).toBe(1);
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    expect(await screen.findByText(/Worker ini tidak memiliki profil lokal/)).toBeTruthy();
    expect(scans).toBe(2);
    expect(requests.filter((item) => item.includes('/profiles/scan'))).toHaveLength(2);
  });

  it('refreshes Upload progress only while its preparation is running', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push(`${method} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url.endsWith('/profiles/scan')) {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'running', phase: 'validating_upload', progress: 70, code: 'OK', updated_at: '2026-10-14T00:00:00+00:00' }
          }]
        }), { status: 200 });
      }
      if (url.endsWith('/profiles/local')) {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:02+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-14T00:00:02+00:00' }
          }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    const lane = await screen.findByRole('region', { name: 'Lane Upload default' });
    expect(lane.textContent).toMatch(/70%/);
    expect(lane.textContent).toMatch(/Memvalidasi sesi Upload/);

    expect(await screen.findByText('Sesi Upload terpisah sudah tervalidasi dan cocok dengan identitas profil.', {}, { timeout: 3000 })).toBeTruthy();
    expect(requests).toContain('GET /api/v1/workers/local/profiles/local');
    expect(requests.filter((request) => request.endsWith('/profiles/local'))).toHaveLength(1);
  });

  it('ignores a delayed progress response after selecting another worker', async () => {
    const requests: string[] = [];
    let resolveOldWorkerStatus: ((response: Response) => void) | undefined;
    let finishOldWorkerRequest: (() => void) | undefined;
    const oldWorkerStatus = new Promise<Response>((resolve) => {
      resolveOldWorkerStatus = resolve;
    });
    const oldWorkerRequestFinished = new Promise<void>((resolve) => {
      finishOldWorkerRequest = resolve;
    });
    let markOldWorkerRequestStarted: (() => void) | undefined;
    const oldWorkerRequestStarted = new Promise<void>((resolve) => {
      markOldWorkerRequestStarted = resolve;
    });
    let runProgressRefresh: (() => void) | undefined;
    const realSetTimeout = globalThis.setTimeout.bind(globalThis);
    const setTimeoutMock = (handler: TimerHandler, timeout?: number, ...handlerArgs: unknown[]) => {
      const timer = realSetTimeout(handler, timeout, ...handlerArgs);
      if (timeout === 1500 && typeof handler === 'function') {
        runProgressRefresh = () => handler(...handlerArgs);
      }
      return timer;
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push(`${method} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [
          { name: 'local', enabled: true },
          { name: 'remote-2', enabled: true }
        ] }), { status: 200 });
      }
      if (url.endsWith('/profiles/scan')) {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [],
            upload_lane: { status: 'running', phase: 'copying', progress: 35, code: 'OK', updated_at: '2026-10-14T00:00:00+00:00' }
          }]
        }), { status: 200 });
      }
      if (url.endsWith('/profiles/local')) {
        markOldWorkerRequestStarted?.();
        return oldWorkerStatus.then((response) => {
          finishOldWorkerRequest?.();
          return response;
        });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    vi.stubGlobal('setTimeout', setTimeoutMock);
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    expect((await screen.findByRole('region', { name: 'Lane Upload default' })).textContent).toMatch(/35%/);

    runProgressRefresh?.();
    await oldWorkerRequestStarted;
    expect(requests).toContain('GET /api/v1/workers/local/profiles/local');
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    resolveOldWorkerStatus?.(new Response(JSON.stringify({
      worker: 'local', checked_at: '2026-10-14T00:00:02+00:00', items: [{
        name: 'default', ready: true, reason_codes: [], checks: [],
        upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-14T00:00:02+00:00' }
      }]
    }), { status: 200 }));
    await oldWorkerRequestFinished;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByRole('region', { name: 'Lane Upload default' })).toBeNull();
    expect(screen.queryByText('Sesi Upload terpisah sudah tervalidasi dan cocok dengan identitas profil.')).toBeNull();
  });

  it('confirms deletion with worker and profile names, then shows the durable result', async () => {
    const requests: { url: string; method: string; headers?: Headers }[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, headers: new Headers(init?.headers) });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-2', enabled: true }] }), { status: 200 });
      }
      if (url.endsWith('/profiles/scan')) {
        return new Response(JSON.stringify({
          worker: 'remote-2', checked_at: '2026-10-14T00:00:00+00:00', items: [
            { name: 'default', deletable: false, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } },
            { name: 'archive', deletable: true, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ],
          pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          operation_id: 'delete-op-1', kind: 'profile.local_delete', profile: 'archive',
          target: { profile: 'archive', worker: 'remote-2' }, status: 'succeeded',
          phase: 'completed', revision: 3, attempt: 1,
          progress: { identity_mapping_status: 'removed' }, created_at: '2026-10-14T00:00:00+00:00'
        }), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));

    expect(await screen.findByText('archive')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Hapus profil default dari remote-2' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari remote-2' }));

    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('archive'));
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('remote-2'));
    const request = requests.find((item) => item.method === 'DELETE');
    expect(request?.url).toBe('/api/v1/workers/remote-2/profiles/local/archive');
    expect(request?.headers?.get('Idempotency-Key')).toBeTruthy();
    expect(await screen.findByRole('region', { name: 'Operasi penghapusan profil' })).toBeTruthy();
    expect(screen.getByText('Mapping identitas dihapus setelah semua worker terverifikasi.')).toBeTruthy();
  });

  it('removes a stale local row when the fresh worker inventory confirms the profile is absent', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url.endsWith('/profiles/scan')) {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-15T00:00:00+00:00', items: [
            { name: 'archive', deletable: true, ready: false, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ], pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          error: { code: 'PROFILE_NOT_IN_LOCAL_SCAN', message: 'Profil archive tidak ditemukan pada hasil scan terbaru worker local.' }
        }), { status: 404 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    expect(await screen.findByRole('heading', { name: 'archive' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari local' }));

    expect((await screen.findByRole('status')).textContent).toMatch(/tidak ditemukan.*dihapus dari daftar lokal/i);
    expect(screen.queryByRole('heading', { name: 'archive' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Operasi penghapusan profil' })).toBeNull();
  });

  it('keeps the local row when the worker inventory is unavailable during delete preflight', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url.endsWith('/profiles/scan')) {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-15T00:00:00+00:00', items: [
            { name: 'archive', deletable: true, ready: false, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ], pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          error: { code: 'WORKER_UNAVAILABLE', message: 'Inventaris profil worker local tidak dapat dipastikan; tidak ada data yang dihapus.' }
        }), { status: 503 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    expect(await screen.findByRole('heading', { name: 'archive' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari local' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/Inventaris profil worker local tidak dapat dipastikan/);
    expect(screen.getByRole('heading', { name: 'archive' })).toBeTruthy();
  });

  it('restores a pending deletion operation after a new page scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url.endsWith('/profiles/scan')) return new Response(JSON.stringify({
        worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [
          { name: 'archive', deletable: true, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
        ], pending_identity_cleanup: []
      }), { status: 200 });
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [{
        operation_id: 'delete-op-recovered', kind: 'profile.local_delete', profile: 'archive',
        target: { profile: 'archive', worker: 'local' }, status: 'waiting_worker', phase: 'waiting_worker',
        revision: 2, attempt: 1, progress: { result: 'waiting_worker' }, created_at: '2026-10-14T00:00:00+00:00'
      }] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan' }));

    expect(await screen.findByText('Menunggu worker online')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Hapus profil archive dari local' }).hasAttribute('disabled')).toBe(true);
  });
});
