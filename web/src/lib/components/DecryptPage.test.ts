import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DecryptPage from '../../routes/decrypt/+page.svelte';

describe('Decrypt page shortlink resolver', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders decrypted HTTP URLs as clickable links', async () => {
    const requests: { path: string; method: string; body?: Record<string, unknown> }[] = [];
    let savedHistoryItem: { id: string; result: string; created_at: string } | null = null;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ path, method, body });
      if (path.includes('/decrypt/history') && method === 'POST') {
        savedHistoryItem = {
          id: 'decrypt-result-1',
          result: 'https://qiwi.gg/file/aHda4057-HDHTIND884',
          created_at: '2026-10-20T00:00:00Z'
        };
        return new Response(JSON.stringify({ item: savedHistoryItem }), { status: 201 });
      }
      if (path.includes('/decrypt/history')) return new Response(JSON.stringify({
        items: savedHistoryItem ? [savedHistoryItem] : [],
        total: savedHistoryItem ? 1 : 0,
        next_offset: null
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    render(DecryptPage);

    await fireEvent.input(screen.getByRole('textbox', { name: 'Teks terenkripsi' }), {
      target: { value: 'a77894319ebfd94509a5db3c280d9aee30d8f20e48773993e3a07eda5632fcf4050a8da670fb4831a28b1f68f6cef20af063b32024485302' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Dekripsi' }));

    const link = await screen.findByRole('link', { name: 'https://qiwi.gg/file/aHda4057-HDHTIND884' });
    expect(link.getAttribute('href')).toBe('https://qiwi.gg/file/aHda4057-HDHTIND884');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(screen.queryByRole('textbox', { name: 'Hasil dekripsi' })).toBeNull();
    expect(await screen.findByText('Dekripsi selesai dan hasilnya disimpan di riwayat.')).toBeTruthy();
    expect(requests.find((request) => request.path.includes('/decrypt/history') && request.method === 'POST')?.body)
      .toEqual({ result: 'https://qiwi.gg/file/aHda4057-HDHTIND884' });
    expect(await screen.findByRole('button', { name: /Tampilkan hasil dekripsi/ })).toBeTruthy();
  });

  it('loads a previously saved decrypted result from history', async () => {
    const previousResult = 'https://files.example.test/previous.zip';
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const path = String(input);
      if (path.includes('/decrypt/history')) {
        return new Response(JSON.stringify({ items: [{
          id: 'decrypt-result-old',
          result: previousResult,
          created_at: '2026-10-19T12:00:00Z'
        }], total: 1, next_offset: null }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    render(DecryptPage);

    await fireEvent.click(await screen.findByRole('button', { name: /Tampilkan hasil dekripsi/ }));

    expect(await screen.findByRole('link', { name: previousResult })).toBeTruthy();
    expect(screen.getByText('Hasil dekripsi dimuat dari riwayat.')).toBeTruthy();
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

    const outputLink = await screen.findByRole('link', { name: destination });
    expect(outputLink.getAttribute('href')).toBe(destination);
    expect(outputLink.getAttribute('target')).toBe('_blank');
    expect(screen.queryByRole('textbox', { name: 'URL tujuan' })).toBeNull();
    expect(requests.find((request) => request.path.endsWith('/safelink/jobs') && request.method === 'POST')?.body)
      .toEqual({ url: shortlink });
    expect(await screen.findByText('Job resolver masuk antrean. Kamu dapat menutup halaman; hasilnya tersimpan di riwayat.')).toBeTruthy();
    await waitFor(() => expect(historyLoads).toBe(2));
    expect(open).not.toHaveBeenCalled();
  });
});
