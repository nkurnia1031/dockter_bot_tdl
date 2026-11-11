import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import TargetPicker from './TargetPicker.svelte';
import { session } from '$lib/session.svelte';

describe('TargetPicker profile targets', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows authorized profiles without using catalog worker ownership as a gate', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default', 'archive', 'remote-only']
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

    const profilePicker = await screen.findByLabelText('Profile target') as HTMLSelectElement;
    expect([...profilePicker.options].map((option) => option.value)).toContain('remote-only');
    await fireEvent.change(profilePicker, { target: { value: 'remote-only' } });
    const workerPicker = screen.getByLabelText('Worker target') as HTMLSelectElement;
    expect([...workerPicker.options].map((option) => option.value)).toEqual(['', 'local', 'remote-1']);
    await fireEvent.change(workerPicker, { target: { value: 'remote-1' } });

    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    expect(await screen.findByText(/remote-only · remote-1/)).toBeTruthy();
  });

  it('can select a disabled worker for management while showing it as unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local', enabled: true },
        { name: 'remote-1', url: 'https://worker.example', enabled: false }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [] }), { status: 200 });
      return new Response('{}', { status: 404 });
    }));

    await session.restore();
    render(TargetPicker, { props: {
      purpose: 'storage',
      requireProfile: false,
      requiresVerification: false,
      allowDisabledWorkerSelection: true
    } });

    const workerPicker = await screen.findByLabelText('Worker target') as HTMLSelectElement;
    const disabledWorker = [...workerPicker.options].find((option) => option.value === 'remote-1');
    expect(disabledWorker?.disabled).toBe(false);
    await fireEvent.change(workerPicker, { target: { value: 'remote-1' } });
    expect(workerPicker.value).toBe('remote-1');
    expect(await screen.findByText(/Worker nonaktif untuk job baru/)).toBeTruthy();
  });
});
