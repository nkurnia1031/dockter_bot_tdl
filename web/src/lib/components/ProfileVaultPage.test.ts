import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
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
    expect(requests).toEqual(['/api/v1/profiles/management']);

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang status Vault' }));
    expect(requests).toEqual(['/api/v1/profiles/management', '/api/v1/profiles/management']);
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
});
