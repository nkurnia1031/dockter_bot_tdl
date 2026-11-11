import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DecryptPage from './DecryptPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), requests: [] as Array<{ path: string; init?: RequestInit }> }));
vi.mock('../lib/api', () => ({ api: mocks.api }));

function setupApi() {
  let saved: { id: string; result: string; created_at: string } | null = null;
  mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
    mocks.requests.push({ path, init });
    if (path.startsWith('/decrypt/history') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      saved = { id: 'decrypt-result-1', result: body.result, created_at: '2026-10-20T00:00:00Z' };
      return { item: saved };
    }
    if (path.startsWith('/decrypt/history')) return { items: saved ? [saved] : [], total: saved ? 1 : 0, next_offset: null };
    if (path === '/safelink/status') return { enabled: false };
    if (path.startsWith('/jobs?kind=safelink_resolve')) return { items: [] };
    throw new Error(`Unexpected API request ${path}`);
  });
}

describe('DecryptPage', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.requests.length = 0; setupApi(); });
  afterEach(() => cleanup());

  it('decrypts, saves the result, and renders decrypted HTTP URLs as safe links', async () => {
    const result = 'https://qiwi.gg/file/aHda4057-HDHTIND884';
    render(DecryptPage);
    await fireEvent.input(screen.getByRole('textbox', { name: 'Teks terenkripsi' }), { target: { value: 'a77894319ebfd94509a5db3c280d9aee30d8f20e48773993e3a07eda5632fcf4050a8da670fb4831a28b1f68f6cef20af063b32024485302' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Dekripsi' }));
    const link = await screen.findByRole('link', { name: result });
    expect(link.getAttribute('href')).toBe(result);
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(mocks.requests.find(({ path, init }) => path.startsWith('/decrypt/history') && init?.method === 'POST')?.init?.body).toBe(JSON.stringify({ result }));
    expect(await screen.findByText('Dekripsi selesai dan hasilnya disimpan di riwayat.')).toBeTruthy();
    expect(await screen.findAllByRole('button', { name: /Tampilkan hasil dekripsi/ })).toHaveLength(1);
  });

  it('returns history to the first page when a new result is saved', async () => {
    let saved: { id: string; result: string; created_at: string } | null = null;
    const oldItems = Array.from({ length: 5 }, (_, index) => ({ id: `old-${index}`, result: `https://files.example/${index}.zip`, created_at: '2026-10-19T00:00:00Z' }));
    const secondPage = Array.from({ length: 5 }, (_, index) => ({ id: `old-${index + 5}`, result: `https://files.example/${index + 5}.zip`, created_at: '2026-10-18T00:00:00Z' }));
    mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
      mocks.requests.push({ path, init });
      if (path.startsWith('/decrypt/history') && init?.method === 'POST') {
        saved = { id: 'new-result', result: JSON.parse(String(init.body)).result, created_at: '2026-10-20T00:00:00Z' };
        return { item: saved };
      }
      if (path.startsWith('/decrypt/history')) {
        const offset = new URLSearchParams(path.split('?')[1]).get('offset');
        if (offset === '5') return { items: secondPage, total: 10 };
        return { items: saved ? [saved, ...oldItems.slice(0, 4)] : oldItems, total: saved ? 11 : 10 };
      }
      if (path === '/safelink/status') return { enabled: false };
      if (path.startsWith('/jobs?kind=safelink_resolve')) return { items: [] };
      throw new Error(`Unexpected API request ${path}`);
    });
    render(DecryptPage);
    await screen.findByText('https://files.example/0.zip');
    await fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));
    await screen.findByText('https://files.example/5.zip');
    await fireEvent.input(screen.getByRole('textbox', { name: 'Teks terenkripsi' }), { target: { value: 'a77894319ebfd94509a5db3c280d9aee30d8f20e48773993e3a07eda5632fcf4050a8da670fb4831a28b1f68f6cef20af063b32024485302' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Dekripsi' }));
    expect(await screen.findByText('https://files.example/0.zip')).toBeTruthy();
    expect(await screen.findByRole('link', { name: 'https://qiwi.gg/file/aHda4057-HDHTIND884' })).toBeTruthy();
    expect(mocks.requests.some(({ path }) => path.includes('offset=0'))).toBe(true);
  });

  it('loads the requested history page with limit/offset and replaces the visible list', async () => {
    const firstPage = Array.from({ length: 5 }, (_, index) => ({ id: `old-${index}`, result: `https://files.example/${index}.zip`, created_at: `2026-10-${10 + index}T00:00:00Z` }));
    mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
      mocks.requests.push({ path, init });
      if (path.startsWith('/decrypt/history') && init?.method === 'POST') return { item: { id: 'new', result: 'https://files.example/new.zip', created_at: '2026-10-20T00:00:00Z' } };
      if (path.startsWith('/decrypt/history')) {
        const offset = new URLSearchParams(path.split('?')[1]).get('offset');
        return offset === '5' ? { items: [{ id: 'page-2', result: 'https://files.example/page-2.zip', created_at: '2026-10-01T00:00:00Z' }], total: 6 } : { items: firstPage, total: 6 };
      }
      if (path === '/safelink/status') return { enabled: false };
      if (path.startsWith('/jobs?kind=safelink_resolve')) return { items: [] };
      throw new Error(`Unexpected API request ${path}`);
    });
    render(DecryptPage);
    await screen.findAllByRole('button', { name: /Tampilkan hasil dekripsi/ });
    await fireEvent.click(screen.getByRole('button', { name: 'Berikutnya' }));
    expect(await screen.findByText('https://files.example/page-2.zip')).toBeTruthy();
    expect(mocks.requests.some(({ path }) => path.includes('offset=5'))).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: 'Sebelumnya' }));
    expect(await screen.findByText('https://files.example/0.zip')).toBeTruthy();
  });

  it('keeps Resolver history available when the feature is disabled', async () => {
    const destination = 'https://files.example.test/previous-resolver-result.zip';
    mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
      mocks.requests.push({ path, init });
      if (path === '/safelink/status') return { enabled: false };
      if (path.startsWith('/jobs?kind=safelink_resolve')) return { items: [{ id: 'resolver-job-existing', status: 'succeeded', worker: 'remote-1', result: { destination_url: destination } }] };
      if (path.startsWith('/decrypt/history')) return { items: [], total: 0 };
      throw new Error(`Unexpected API request ${path}`);
    });
    render(DecryptPage);
    expect(await screen.findByText('Resolver dinonaktifkan sementara. Job dan hasil sebelumnya tetap tersedia di bawah.')).toBeTruthy();
    expect(await screen.findByText(/#resolver · succeeded · remote-1/)).toBeTruthy();
    expect(await screen.findByRole('link', { name: destination })).toBeTruthy();
    expect(screen.queryByLabelText('URL shortlink')).toBeNull();
    expect(mocks.requests.some(({ path }) => path === '/safelink/workers')).toBe(false);
  });

  it('submits a shortlink job with idempotency and renders the history result without opening it', async () => {
    const destination = 'https://files.example.test/book.zip';
    let jobLoads = 0;
    mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
      mocks.requests.push({ path, init });
      if (path === '/safelink/status') return { enabled: true };
      if (path === '/safelink/workers') return { items: [{ name: 'resolver-1', status: 'ready', queued_jobs: 0 }] };
      if (path.startsWith('/jobs?kind=safelink_resolve')) { jobLoads++; return { items: jobLoads < 2 ? [] : [{ id: 'resolver-job-1', status: 'succeeded', worker: 'resolver-1', result: { destination_url: destination } }] }; }
      if (path === '/safelink/jobs' && init?.method === 'POST') return { id: 'resolver-job-1', status: 'queued' };
      if (path.startsWith('/decrypt/history')) return { items: [], total: 0 };
      throw new Error(`Unexpected API request ${path}`);
    });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(DecryptPage);
    await fireEvent.input(await screen.findByLabelText('URL shortlink'), { target: { value: 'https://pndk.to/opaque-code' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    expect(await screen.findByRole('link', { name: destination })).toBeTruthy();
    const submit = mocks.requests.find(({ path, init }) => path === '/safelink/jobs' && init?.method === 'POST');
    expect(JSON.parse(String(submit?.init?.body))).toEqual({ url: 'https://pndk.to/opaque-code' });
    expect(new Headers(submit?.init?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(open).not.toHaveBeenCalled();
    await waitFor(() => expect(jobLoads).toBeGreaterThanOrEqual(2));
  });
});
