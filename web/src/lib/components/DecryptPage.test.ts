import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DecryptPage from '../../routes/decrypt/+page.svelte';

describe('Decrypt page shortlink resolver', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('submits a shortlink job, restores its result from job history, and does not open it', async () => {
    const shortlink = 'https://pndk.to/opaque-code';
    const destination = 'https://files.example.test/book.zip';
    const requests: { path: string; method: string; body?: Record<string, unknown> }[] = [];
    let historyLoads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ path, method, body });
      if (path.includes('/jobs?kind=safelink_resolve')) {
        historyLoads += 1;
        return new Response(JSON.stringify({ items: historyLoads === 1 ? [] : [{
          id: 'resolver-job-1',
          status: 'succeeded',
          worker: 'resolver-1',
          result: { destination_url: destination }
        }] }), { status: 200 });
      }
      if (path.endsWith('/safelink/jobs') && method === 'POST') {
        return new Response(JSON.stringify({ id: 'resolver-job-1', status: 'queued' }), { status: 202 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);

    render(DecryptPage);
    await fireEvent.input(await screen.findByLabelText('URL shortlink'), { target: { value: shortlink } });
    await fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    expect(await screen.findByDisplayValue(destination)).toBeTruthy();
    expect(requests.find((request) => request.path.endsWith('/safelink/jobs') && request.method === 'POST')?.body)
      .toEqual({ url: shortlink });
    expect(await screen.findByText('Job resolver masuk antrean. Kamu dapat menutup halaman; hasilnya tersimpan di riwayat.')).toBeTruthy();
    await waitFor(() => expect(historyLoads).toBe(2));
    expect(open).not.toHaveBeenCalled();
  });
});
