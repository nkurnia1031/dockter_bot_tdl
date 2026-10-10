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

  it('shows sync logs, offers recovery only for a revision error, and supports cancellation', async () => {
    const requests: { url: string; method: string; headers?: HeadersInit; body?: BodyInit | null }[] = [];
    const timeout = vi.spyOn(window, 'setTimeout');
    let syncOperations: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, headers: init?.headers, body: init?.body });
      if (url.endsWith('/profiles/management')) {
        return new Response(JSON.stringify({
          items: [{
            name: 'irang', active: true, status: 'active', vault: true,
            desired_revision: 2,
            workers: [{ worker: 'local', status: 'failed', error: 'PROFILE_BUNDLE_HASH_MISMATCH', desired_revision: 2, installed_revision: 1 }]
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
          profiles: { irang: { status: 'failed', error_code: 'PROFILE_BUNDLE_HASH_MISMATCH', desired_revision: 2, installed_revision: 1 } }
        }), { status: 200 });
      }
      if (url.includes('/profiles/irang/workers/local/sync-logs')) {
        const afterId = Number(new URL(url, 'http://localhost').searchParams.get('after_id') || 0);
        const rows = [
          {
            id: 1, run_id: 'run-12345678', revision: 2, phase: 'bundle_validation', status: 'failed',
            code: 'PROFILE_BUNDLE_HASH_MISMATCH', details: {}, created_at: '2026-10-10T00:00:00Z'
          },
          {
            id: 2, run_id: 'run-87654321', revision: 2, phase: 'manifest_fetch', status: 'running',
            code: 'WORKER_SYNC_REQUESTED', details: {}, created_at: '2026-10-10T00:00:01Z'
          },
          {
            id: 3, run_id: 'run-87654321', revision: 2, phase: 'cancelled', status: 'cancelled',
            code: 'SYNC_CANCELLED', details: {}, created_at: '2026-10-10T00:00:02Z'
          }
        ];
        const latest = rows[Math.min(2, syncOperations[0]?.status === 'cancelled' ? 2 : syncOperations.length ? 1 : 0)];
        return new Response(JSON.stringify({
          items: rows.filter((item) => item.id > afterId && item.id <= latest.id),
          next_after_id: Math.max(afterId, rows.filter((item) => item.id > afterId && item.id <= latest.id).at(-1)?.id || 0),
          latest_run_id: latest.run_id, latest_status: latest.status,
          active: latest.status === 'queued' || latest.status === 'running'
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
    expect(await screen.findByText(/PROFILE_BUNDLE_HASH_MISMATCH/)).toBeTruthy();
    expect(await screen.findByText(/Memvalidasi bundle/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Pulihkan' }));
    expect(await screen.findByRole('button', { name: 'Batalkan sync' })).toBeTruthy();
    expect(screen.getByText(/Worker local melaporkan PROFILE_BUNDLE_HASH_MISMATCH/)).toBeTruthy();
    expect(await screen.findByText(/Log diperbarui otomatis selama proses berjalan/)).toBeTruthy();
    expect(timeout.mock.calls.some(([, delay]) => delay === 2500)).toBe(true);

    const submit = requests.find((item) => item.url === '/api/v1/operations' && item.method === 'POST');
    expect(new Headers(submit?.headers).get('Idempotency-Key')).toMatch(/^profile-sync-/);
    expect(JSON.parse(String(submit?.body))).toEqual({
      kind: 'profile.sync', target: { profile: 'irang', worker: 'local' }, input: { mode: 'repair' }
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Batalkan sync' }));
    expect(await screen.findByText(/Permintaan pembatalan sinkronisasi irang pada local dikirim/)).toBeTruthy();
    expect(await screen.findByText(/worker offline atau tidak dapat dijangkau; pembatalan proses worker belum terkonfirmasi/)).toBeTruthy();
    expect(screen.queryByText(/Log diperbarui otomatis selama proses berjalan/)).toBeNull();
    const cancel = requests.find((item) => item.url.endsWith('/operations/sync-op-1/cancel'));
    expect(cancel?.method).toBe('POST');
    expect(new Headers(cancel?.headers).get('Idempotency-Key')).toMatch(/^profile-sync-/);
  });

  it('does not show a sync or recovery action for a worker already at the vault revision', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.endsWith('/profiles/management')) {
        return new Response(JSON.stringify({
          items: [{
            name: 'irang', active: true, status: 'active', vault: true, desired_revision: 4,
            workers: [{ worker: 'local', status: 'ready', desired_revision: 4, installed_revision: 4 }]
          }],
          workers: [{ name: 'local', enabled: true, online: true, secure: true }]
        }), { status: 200 });
      }
      if (url.endsWith('/workers/local/profile-sync')) {
        return new Response(JSON.stringify({
          worker: 'local', status: 'ready', backend_available: true,
          profiles: { irang: { status: 'ready', desired_revision: 4, installed_revision: 4 } }
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    expect(await screen.findByText(/Revision vault 4 sudah terpasang dan dikonfirmasi/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pulihkan' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Periksa \/ sinkronkan/ })).toBeNull();
  });

});
