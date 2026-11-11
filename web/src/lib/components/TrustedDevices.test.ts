import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import TrustedDevices from './TrustedDevices.svelte';

const publicKey = btoa(String.fromCharCode(...new Uint8Array(32))).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const fingerprint = 'SHA256:Zmh6rfhivXdsj8GLjp+OIAiXFIVu4jOzkCpZHQ1fKSU';

describe('trusted device settings', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists only public metadata and supports explicit refresh', async () => {
    document.cookie = 'tme3_csrf=csrf-device; Path=/';
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{ id: 'device-1', name: 'Agent laptop', algorithm: 'Ed25519', fingerprint, origin: 'https://ui.example.test', created_at: '2026-10-04T10:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }]
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    render(TrustedDevices);
    expect(await screen.findByText('Agent laptop')).toBeTruthy();
    expect(screen.getByText(fingerprint)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  it('shows the verified fingerprint before registering an enrollment file', async () => {
    document.cookie = 'tme3_csrf=csrf-device; Path=/';
    const digest = Uint8Array.from('66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925'.match(/../g)!, (part) => parseInt(part, 16));
    vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockResolvedValue(digest.buffer) } });
    const registered = { id: 'fd9f67f1-bba8-4011-9ed3-0f819ac8df10', name: 'Agent laptop', algorithm: 'Ed25519', fingerprint, origin: window.location.origin, created_at: '2026-10-04T10:00:00Z', last_used_at: null, revoked_at: null, status: 'active' };
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/devices') && init?.method === 'POST') return new Response(JSON.stringify({ device: registered, created: true }), { status: 201 });
      return new Response(JSON.stringify({ items: init?.method === 'POST' ? [registered] : [] }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetcher);
    render(TrustedDevices);
    const enrollment = {
      version: 1,
      device_id: registered.id,
      name: registered.name,
      algorithm: 'Ed25519',
      public_key: publicKey,
      fingerprint,
      origin: window.location.origin
    };
    const file = new File([JSON.stringify(enrollment)], 'device-enrollment.json', { type: 'application/json' });
    Object.defineProperty(file, 'text', { value: async () => JSON.stringify(enrollment) });
    await fireEvent.change(screen.getByLabelText('Berkas public key enrollment'), { target: { files: [file] } });
    expect(await screen.findByText(fingerprint)).toBeTruthy();
    const approve = await screen.findByRole('button', { name: 'Setujui dan tambahkan' });
    await waitFor(() => expect((approve as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(approve);
    await screen.findByText('Perangkat berhasil ditambahkan.');
    const request = fetcher.mock.calls.find((call) => String(call[0]).endsWith('/auth/devices') && call[1]?.method === 'POST');
    expect(request).toBeTruthy();
    expect(String(request?.[1]?.body)).not.toContain('private_key');
  });
});
