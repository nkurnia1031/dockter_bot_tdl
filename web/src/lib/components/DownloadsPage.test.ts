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
});
