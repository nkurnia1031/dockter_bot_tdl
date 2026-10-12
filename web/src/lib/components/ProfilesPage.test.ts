import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ProfilesPage from './ProfilesPage.svelte';

describe('ProfilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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
              { name: 'user1_session', ready: true, code: 'OK' }
            ]
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
    expect(screen.getByText(/root.*Siap/)).toBeTruthy();
    expect(screen.getByText(/user1.*Siap/)).toBeTruthy();
    expect(screen.getByText(/Hasil scan.*remote-2/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Adopsi/ })).toBeNull();
    expect(requests).toContainEqual({ url: '/api/v1/workers/remote-2/profiles/scan', method: 'POST' });

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang worker' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/hasil scan sebelumnya dihapus/i);
    expect(screen.queryByText('irang')).toBeNull();
    expect(requests.filter((item) => item.url.includes('/profiles/scan'))).toHaveLength(1);
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
});
