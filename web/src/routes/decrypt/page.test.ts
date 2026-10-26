import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DecryptPage from './+page.svelte';

describe('DecryptPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows five history entries per page and replaces entries when navigating', async () => {
    const requests: { url: string; method: string }[] = [];
    const history = Array.from({ length: 60 }, (_, index) => ({
      id: `history-${index + 1}`,
      result: `history-result-${index + 1}`,
      created_at: `2026-10-26T10:${String(index).padStart(2, '0')}:00Z`,
    }));
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url.startsWith('/api/v1/decrypt/history?')) {
        const parsed = new URL(url, 'http://local.test');
        const limit = Number(parsed.searchParams.get('limit'));
        const offset = Number(parsed.searchParams.get('offset'));
        const items = history.slice(offset, offset + limit);
        return new Response(JSON.stringify({
          items,
          total: history.length,
          next_offset: offset + items.length < history.length ? offset + items.length : null,
        }), { status: 200 });
      }
      if (url.startsWith('/api/v1/jobs?kind=safelink_resolve')) {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(DecryptPage);

    expect(await screen.findByText('history-result-1')).toBeTruthy();
    expect(screen.getByText('history-result-5')).toBeTruthy();
    expect(screen.queryByText('history-result-6')).toBeNull();
    expect(screen.getByText('5 dari 60 hasil tersimpan')).toBeTruthy();
    const pagination = screen.getByRole('navigation', { name: 'Navigasi halaman riwayat dekripsi' });
    expect(pagination.textContent).toContain('…');
    expect(screen.getByRole('button', { name: 'Halaman 12' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Halaman 6' })).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));

    expect(await screen.findByText('history-result-6')).toBeTruthy();
    expect(screen.getByText('history-result-10')).toBeTruthy();
    expect(screen.queryByText('history-result-1')).toBeNull();
    expect(requests).toContainEqual({
      url: '/api/v1/decrypt/history?limit=5&offset=5',
      method: 'GET',
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang' }));
    await waitFor(() => expect(requests.filter((request) =>
      request.url === '/api/v1/decrypt/history?limit=5&offset=5' && request.method === 'GET'
    )).toHaveLength(2));
    expect(screen.getByRole('button', { name: 'Halaman 2' }).getAttribute('aria-current')).toBe('page');
  });

  it('returns to the first page after saving a newly decrypted result', async () => {
    const requests: { url: string; method: string }[] = [];
    const history = Array.from({ length: 12 }, (_, index) => ({
      id: `history-${index + 1}`,
      result: `history-result-${index + 1}`,
      created_at: `2026-10-26T10:${String(index).padStart(2, '0')}:00Z`,
    }));
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/decrypt/history' && method === 'POST') {
        const body = JSON.parse(String(init?.body || '{}')) as { result: string };
        const item = {
          id: 'history-new', result: body.result, created_at: '2026-10-26T11:00:00Z',
        };
        history.unshift(item);
        return new Response(JSON.stringify({ item }), { status: 201 });
      }
      if (url.startsWith('/api/v1/decrypt/history?')) {
        const parsed = new URL(url, 'http://local.test');
        const limit = Number(parsed.searchParams.get('limit'));
        const offset = Number(parsed.searchParams.get('offset'));
        const items = history.slice(offset, offset + limit);
        return new Response(JSON.stringify({
          items,
          total: history.length,
          next_offset: offset + items.length < history.length ? offset + items.length : null,
        }), { status: 200 });
      }
      if (url.startsWith('/api/v1/jobs?kind=safelink_resolve')) {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(DecryptPage);

    await screen.findByText('history-result-1');
    await fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));
    await screen.findByText('history-result-6');
    await fireEvent.click(screen.getByRole('button', { name: 'Isi contoh' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Dekripsi' }));

    await waitFor(() => expect(requests.filter((request) =>
      request.url === '/api/v1/decrypt/history?limit=5&offset=0' && request.method === 'GET'
    )).toHaveLength(2));
    await waitFor(() => expect(
      screen.getByRole('button', { name: 'Halaman 1' }).getAttribute('aria-current')
    ).toBe('page'));
  });

  it('defaults to Auto, shows saved worker readiness, and submits a manual worker', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({
        url,
        method,
        body: typeof init?.body === 'string' ? init.body : undefined,
      });
      if (url === '/api/v1/safelink/workers') {
        return new Response(JSON.stringify({ items: [
          { name: 'local', enabled: true, status: 'ready', reason_code: '', queued_jobs: 1 },
          { name: 'remote', enabled: true, status: 'not_ready', reason_code: 'RESOLVER_RUNTIME_UNAVAILABLE', queued_jobs: 0 },
        ] }), { status: 200 });
      }
      if (url.startsWith('/api/v1/jobs?kind=safelink_resolve')) {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      if (url === '/api/v1/safelink/jobs' && method === 'POST') {
        return new Response(JSON.stringify({ id: 'job-1', status: 'queued' }), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(DecryptPage);

    const worker = await screen.findByRole('combobox', { name: 'Worker' });
    await waitFor(() => expect(worker.querySelector('option[value="remote"]')?.textContent).toContain('tidak siap'));
    expect((worker as HTMLSelectElement).value).toBe('');
    await fireEvent.change(worker, { target: { value: 'remote' } });
    await fireEvent.input(screen.getByRole('textbox', { name: 'URL shortlink' }), {
      target: { value: 'https://pndk.to/example' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    await waitFor(() => expect(requests).toContainEqual({
      url: '/api/v1/safelink/jobs',
      method: 'POST',
      body: JSON.stringify({ url: 'https://pndk.to/example', worker: 'remote' }),
    }));
  });
});
