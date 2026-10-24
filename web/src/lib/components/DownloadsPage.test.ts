import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DownloadsPage from './DownloadsPage.svelte';
import { session } from '$lib/session.svelte';

describe('DownloadsPage profile filter', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
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

  it('blocks artifacts until the saved Profile scan marks their download lane ready', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
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
      if (url.includes('/jobs')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    await session.restore();
    render(DownloadsPage);

    expect(await screen.findByText('Download belum siap · Scan Profil')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Mulai' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true);
  });
});
