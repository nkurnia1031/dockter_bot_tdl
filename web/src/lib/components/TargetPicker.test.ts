import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import TargetPicker from './TargetPicker.svelte';
import { session } from '$lib/session.svelte';

describe('TargetPicker verified profile targets', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows catalog options and pins an exclusive profile to its owner', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default', 'archive']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local' },
        { name: 'remote-1', url: 'https://worker.example' }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [
        { name: 'shared', workers: ['local', 'remote-1'], exclusive_worker: '' },
        { name: 'remote-only', workers: ['remote-1'], exclusive_worker: 'remote-1' }
      ] }), { status: 200 });
      if (url.endsWith('/context/verify')) {
        return new Response(JSON.stringify({
          verified: true,
          purpose: 'export',
          profile: JSON.parse(String(init?.body || '{}')).profile,
          worker: JSON.parse(String(init?.body || '{}')).worker
        }), { status: 200 });
      }
      return new Response('{}', { status: 404 });
    }));

    await session.restore();
    render(TargetPicker);

    const profilePicker = await screen.findByLabelText('Profile target');
    expect(profilePicker.innerHTML).toContain('remote-only (remote-1)');
    await fireEvent.change(profilePicker, { target: { value: 'remote-only' } });
    const workerPicker = screen.getByLabelText('Worker target') as HTMLSelectElement;
    await waitFor(() => expect(workerPicker.value).toBe('remote-1'));
    expect([...workerPicker.options].map((option) => option.value)).toEqual(['', 'remote-1']);

    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    expect(await screen.findByText(/remote-only · remote-1/)).toBeTruthy();
  });
});
