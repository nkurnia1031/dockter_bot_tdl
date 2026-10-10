import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ProfilesPage from './ProfilesPage.svelte';

describe('ProfilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('uploads a TDL session ZIP to the selected secure worker', async () => {
    const interval = vi.spyOn(window, 'setInterval');
    const requests: { url: string; method: string; body?: BodyInit | null }[] = [];
    let managementCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: init?.body });
      if (url.endsWith('/profiles/management')) {
        managementCalls += 1;
        return new Response(JSON.stringify({
          items: managementCalls > 1 ? [{
            name: 'novel', active: false, status: 'distributing', vault: true,
            operation_id: 'operation-1', workers: [{ worker: 'local', status: 'waiting' }]
          }] : [],
          workers: [{ name: 'local', enabled: true, online: true, secure: true }]
        }), { status: 200 });
      }
      if (url.includes('/profiles/provisionings/upload?')) {
        return new Response(JSON.stringify({ id: 'operation-1', status: 'distributing' }), { status: 200 });
      }
      if (url.endsWith('/profiles/provisionings/operation-1')) {
        return new Response(JSON.stringify({
          id: 'operation-1', profile: 'novel', status: 'distributing', source: 'upload',
          workers: [{ worker: 'local', status: 'waiting' }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByLabelText('Nama profil');
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.input(screen.getByLabelText('Nama profil'), { target: { value: 'novel' } });
    await fireEvent.change(screen.getByLabelText('Worker untuk menyiapkan sesi'), { target: { value: 'local' } });
    const file = new File(['session'], 'session.zip', { type: 'application/zip' });
    await fireEvent.change(screen.getByLabelText(/ZIP berisi folder/), { target: { files: [file] } });
    const submit = screen.getByRole('button', { name: 'Validasi dan sebarkan' });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(submit);

    expect(await screen.findByText('Sinkronisasi')).toBeTruthy();
    expect(interval.mock.calls.some(([, delay]) => delay === 4000)).toBe(false);
    const upload = requests.find((item) => item.url.includes('/profiles/provisionings/upload'));
    expect(upload?.method).toBe('POST');
    expect(upload?.url).toContain('name=novel');
    expect(upload?.url).toContain('worker=local');
    expect(upload?.body).toBe(file);
  });

  it('shows why profile sync is waiting, lets the user request sync, and cancel it', async () => {
    const requests: { url: string; method: string; headers?: HeadersInit; body?: BodyInit | null }[] = [];
    let syncOperations: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, headers: init?.headers, body: init?.body });
      if (url.endsWith('/profiles/management')) {
        return new Response(JSON.stringify({
          items: [{
            name: 'irang', active: true, status: 'active', vault: true,
            workers: [{ worker: 'local', status: 'waiting' }]
          }],
          workers: [{ name: 'local', enabled: true, online: true, secure: true }]
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') {
        return new Response(JSON.stringify({ items: syncOperations }), { status: 200 });
      }
      if (url.endsWith('/workers/local/profile-sync')) {
        return new Response(JSON.stringify({
          worker: 'local', status: 'waiting_worker', backend_available: false,
          profiles: { irang: { status: 'waiting_worker', error_code: 'BACKEND_UNAVAILABLE', desired_revision: 2, installed_revision: 1 } }
        }), { status: 200 });
      }
      if (url === '/api/v1/operations' && method === 'POST') {
        const operation = {
          operation_id: 'sync-op-1', kind: 'profile.sync', profile: 'irang', status: 'waiting_worker', phase: 'waiting_worker',
          target: { profile: 'irang', worker: 'local', desired_revision: 2 }
        };
        syncOperations = [operation];
        return new Response(JSON.stringify(operation), { status: 202 });
      }
      if (url.endsWith('/operations/sync-op-1/cancel') && method === 'POST') {
        syncOperations = [{
          ...syncOperations[0], status: 'cancelled',
          progress: { worker_sync_cancel: 'worker_unavailable' }
        }];
        return new Response(JSON.stringify(syncOperations[0]), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    expect(await screen.findByText(/Worker belum dapat menjangkau backend \(BACKEND_UNAVAILABLE\)/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Periksa / sinkronkan' }));
    expect(await screen.findByRole('button', { name: 'Batalkan sync' })).toBeTruthy();
    expect(screen.getByText(/Worker local melaporkan BACKEND_UNAVAILABLE/)).toBeTruthy();

    const submit = requests.find((item) => item.url === '/api/v1/operations' && item.method === 'POST');
    expect(new Headers(submit?.headers).get('Idempotency-Key')).toMatch(/^profile-sync-/);
    expect(JSON.parse(String(submit?.body))).toEqual({
      kind: 'profile.sync', target: { profile: 'irang', worker: 'local' }, input: {}
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Batalkan sync' }));
    expect(await screen.findByText(/Permintaan pembatalan sinkronisasi irang pada local dikirim/)).toBeTruthy();
    expect(await screen.findByText(/worker offline atau tidak dapat dijangkau; pembatalan proses worker belum terkonfirmasi/)).toBeTruthy();
    const cancel = requests.find((item) => item.url.endsWith('/operations/sync-op-1/cancel'));
    expect(cancel?.method).toBe('POST');
    expect(new Headers(cancel?.headers).get('Idempotency-Key')).toMatch(/^profile-sync-/);
  });
});
