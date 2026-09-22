import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import JobTable from './JobTable.svelte';

describe('JobTable', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('shows an accessible empty state and global terminate action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    render(JobTable, { title: 'Daftar aktivitas' });
    expect(await screen.findByText('Belum ada job.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Terminate semua aktif' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh daftar job' })).toBeTruthy();
  });

  it('filters Quick Mode globally and retries a failed attempt', async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [{ id: 'failed-1', kind: 'export', status: 'failed', profile: 'archive', worker: 'remote-1', updated_at: '2026-09-17T00:00:00Z', error: { message: 'gagal upload' } }] }), { status: 200 });
      if (url.endsWith('/retry')) return new Response(JSON.stringify({ id: 'retry-1', status: 'queued' }), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, retryable: true });
    const retryButton = await screen.findByRole('button', { name: 'Retry' });
    await fireEvent.click(retryButton);

    expect(calls.some((call) => call.url.includes('scope=global') && call.url.includes('kind=export') && call.url.includes('quick_mode=true'))).toBe(true);
    expect(calls.some((call) => call.url.endsWith('/retry') && call.method === 'POST')).toBe(true);
  });

  it('uses a live active monitor query separate from terminal history', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running', profile: 'default', worker: 'local', payload: { quick_mode: true }, progress: { phase: 'downloading' } }] }), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, view: 'active', title: 'Monitor aktif' });

    expect(await screen.findByText('Sedang berjalan')).toBeTruthy();
    expect(urls.some((url) => decodeURIComponent(url).includes('status=queued,dispatched,running'))).toBe(true);
    expect(screen.queryByText('History terbaru')).toBeNull();
  });

  it('auto polls monitor views that also contain history', async () => {
    const interval = vi.spyOn(globalThis, 'setInterval');
    vi.stubGlobal('fetch', vi.fn(async () => {
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'utility', status: 'running', progress: { phase: 'compressing' } }] }), { status: 200 });
    }));

    render(JobTable, { kind: 'utility', title: 'Utility monitor' });
    expect(await screen.findByText('Sedang berjalan')).toBeTruthy();

    expect(interval).toHaveBeenCalledWith(expect.any(Function), 2500);
    expect(screen.getByText('Live · 2,5 detik')).toBeTruthy();
  });
});
