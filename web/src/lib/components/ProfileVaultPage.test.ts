import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ProfileVaultPage from './ProfileVaultPage.svelte';

describe('ProfileVaultPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('separates the Vault acknowledgement from worker runtime and shows the safe failure reason', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      requests.push(url);
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({
          workers: [{ name: 'remote-1', enabled: true, online: true, secure: true }],
          items: [{
            name: 'default', active: true, status: 'waiting_worker', vault: true,
            workers: [{
              worker: 'remote-1', status: 'waiting_worker', desired_revision: 1, installed_revision: 1,
              vault_ack_status: 'ready', vault_ack_installed_revision: 1,
              runtime_status: 'waiting_worker', runtime_error_code: 'WORKER_IDENTITY_AMBIGUOUS'
            }]
          }, {
            name: 'irang', active: true, status: 'waiting_worker', vault: true,
            workers: [{ worker: 'remote-1', status: 'waiting_worker', runtime_status: 'waiting_worker', runtime_error_code: 'WORKER_UNAUTHORIZED' }]
          }, {
            name: 'storage', active: true, status: 'waiting_worker', vault: true,
            workers: [{ worker: 'remote-1', status: 'waiting_worker', runtime_status: 'waiting_worker', runtime_error_code: 'INTERNAL_UNAUTHORIZED' }]
          }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfileVaultPage);

    expect(await screen.findByText(/Token worker dipakai bersama/)).toBeTruthy();
    expect(screen.getByText(/WORKER_API_TOKEN pada worker tidak cocok/)).toBeTruthy();
    expect(screen.getByText(/BACKEND_INTERNAL_TOKEN pada worker tidak cocok/)).toBeTruthy();
    expect(screen.getByText(/Vault ACK: Siap/)).toBeTruthy();
    expect(screen.getAllByText(/Runtime worker: Menunggu/)).toHaveLength(3);
    expect(screen.getAllByRole('link', { name: 'Buka log JSON' })[0].getAttribute('href'))
      .toBe('/api/v1/profiles/default/workers/remote-1/sync-logs?limit=500');
    expect(screen.queryByRole('button', { name: /Adopsi|Sebarkan|login TDL/i })).toBeNull();
    expect(requests.filter((url) => url === '/api/v1/profiles/management')).toHaveLength(1);
    expect(requests).toContain('/api/v1/profiles/default/workers/remote-1/sync-logs?limit=50');

    await waitFor(() => expect(
      screen.getByRole('button', { name: 'Muat ulang status Vault' }).hasAttribute('disabled')
    ).toBe(false));
    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang status Vault' }));
    expect(requests.filter((url) => url === '/api/v1/profiles/management')).toHaveLength(2);
  });

  it('shows persisted sync progress history and refreshes it without restarting the operation', async () => {
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      requests.push(url);
      if (url === '/api/v1/profiles/management') return new Response(JSON.stringify({
        workers: [{ name: 'remote-1', enabled: true, online: true, secure: true }],
        items: [{
          name: 'default', active: true, status: 'sync_pending', vault: true,
          workers: [{ worker: 'remote-1', status: 'sync_pending', desired_revision: 3, runtime_status: 'sync_pending' }]
        }]
      }), { status: 200 });
      if (url.endsWith('/sync-logs?limit=50')) return new Response(JSON.stringify({
        active: true,
        next_after_id: 3,
        items: [
          { id: 1, run_id: 'operation-123', sequence: null, revision: 3, phase: 'queued', status: 'queued', code: 'PROFILE_SYNC_QUEUED', created_at: '2026-10-01T10:00:00Z' },
          { id: 2, run_id: 'worker-run-123', sequence: 1, revision: 3, phase: 'bundle_download', status: 'running', code: '', created_at: '2026-10-01T10:00:03Z' },
          { id: 3, run_id: 'worker-run-123', sequence: 2, revision: 3, phase: 'upload_validation', status: 'succeeded', code: '', created_at: '2026-10-01T10:00:04Z' }
        ]
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfileVaultPage);

    expect(await screen.findByText('Unduh bundle')).toBeTruthy();
    expect(screen.getByText('Validasi lane Upload')).toBeTruthy();
    expect(screen.getByText('Antrean')).toBeTruthy();
    expect(screen.getAllByText('Berjalan').length).toBeGreaterThan(0);
    expect(requests).toContain('/api/v1/profiles/default/workers/remote-1/sync-logs?limit=50');
    expect(requests.some((url) => url.includes('/api/v1/operations'))).toBe(false);
    await waitFor(() => expect(
      screen.getByRole('button', { name: 'Muat ulang status Vault' }).hasAttribute('disabled')
    ).toBe(false));
    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang status Vault' }));
    await waitFor(() => expect(requests.filter((url) => url.endsWith('/sync-logs?limit=50'))).toHaveLength(2));
  });

  it('deletes only the Vault bundle after explicit confirmation', async () => {
    const requests: { url: string; method: string }[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/profiles/management') return new Response(JSON.stringify({
        workers: [], items: [{ name: 'archive', active: true, status: 'active', vault: true, workers: [] }]
      }), { status: 200 });
      if (url === '/api/v1/profiles/archive/vault' && method === 'DELETE') return new Response(JSON.stringify({
        deleted: true, profile: 'archive', local_copies_unchanged: true
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfileVaultPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Hapus bundle archive dari Vault' }));

    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('Sesi pada worker lokal tidak akan dihapus'));
    expect(requests).toContainEqual({ url: '/api/v1/profiles/archive/vault', method: 'DELETE' });
    expect(await screen.findByText('Bundle archive dihapus dari Vault. Sesi worker lokal tetap utuh.')).toBeTruthy();
    expect(screen.getByText('Belum ada profil yang tersimpan di Vault.')).toBeTruthy();
  });

  it('starts one pinned distribution and retries only the failed worker with metadata requests', async () => {
    const requests: { url: string; method: string; headers: Headers; body: string | null }[] = [];
    let started = false;
    const operation = {
      id: 'a36b11cb-2135-4fce-89c2-772b0eb25792', profile: 'archive', revision: 7,
      target_workers: ['remote-1', 'remote-2'], status: 'failed',
      created_at: '2026-10-17T10:00:00Z', updated_at: '2026-10-17T10:01:00Z',
      workers: [
        { worker: 'remote-1', status: 'failed', phase: 'failed', reason_code: 'PROFILE_INSTALL_FAILED', updated_at: '2026-10-17T10:01:00Z' },
        { worker: 'remote-2', status: 'ready', phase: 'completed', reason_code: '', updated_at: '2026-10-17T10:01:00Z' }
      ]
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const headers = new Headers(init?.headers);
      const body = typeof init?.body === 'string' ? init.body : null;
      requests.push({ url, method, headers, body });
      if (url === '/api/v1/profiles/management') return new Response(JSON.stringify({
        workers: [
          { name: 'remote-1', enabled: true, online: true, secure: true },
          { name: 'remote-2', enabled: true, online: true, secure: true }
        ],
        items: [{ name: 'archive', active: true, status: 'stored', vault: true, desired_revision: 7, workers: [] }]
      }), { status: 200 });
      if (url === '/api/v1/profiles/archive/distributions' && method === 'GET') return new Response(JSON.stringify({ items: started ? [operation] : [] }), { status: 200 });
      if (url.endsWith('/events?limit=100')) return new Response(JSON.stringify({
        active: false, next_after_id: 3, items: [
          { id: 1, worker: 'remote-1', sequence: 1, phase: 'queued', status: 'queued', code: '', created_at: '2026-10-17T10:00:00Z' },
          { id: 2, worker: 'remote-1', sequence: 2, phase: 'archive_download', status: 'running', code: '', created_at: '2026-10-17T10:00:30Z' },
          { id: 3, worker: 'remote-1', sequence: 3, phase: 'failed', status: 'failed', code: 'PROFILE_INSTALL_FAILED', created_at: '2026-10-17T10:01:00Z' }
        ]
      }), { status: 200 });
      if (url === '/api/v1/profiles/archive/distributions' && method === 'POST') {
        started = true;
        return new Response(JSON.stringify(operation), { status: 202 });
      }
      if (url.endsWith('/workers/remote-1/retry') && method === 'POST') return new Response(JSON.stringify(operation), { status: 202 });
      if (url.endsWith('/sync-logs?limit=50')) return new Response(JSON.stringify({ items: [], active: false, next_after_id: 0 }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfileVaultPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Distribusikan archive revision 7 ke semua worker' }));
    expect(await screen.findByText(/Unduh arsip dari channel/)).toBeTruthy();
    expect(screen.getByText(/snapshot: remote-1, remote-2/)).toBeTruthy();
    expect(screen.getByRole('button', { name: `Retry distribusi ${operation.id} pada remote-1` })).toBeTruthy();
    const submit = requests.find((request) => request.method === 'POST' && request.url === '/api/v1/profiles/archive/distributions');
    expect(submit?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(submit?.body).toBeNull();
    const retryButton = screen.getByRole('button', { name: `Retry distribusi ${operation.id} pada remote-1` });
    await waitFor(() => expect(retryButton.hasAttribute('disabled')).toBe(false));
    await fireEvent.click(retryButton);
    const retry = requests.find((request) => request.method === 'POST' && request.url.endsWith('/workers/remote-1/retry'));
    expect(retry?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(retry?.body).toBeNull();
    expect(requests.some((request) => request.url.includes('/workers/remote-2/retry'))).toBe(false);
  });
});
