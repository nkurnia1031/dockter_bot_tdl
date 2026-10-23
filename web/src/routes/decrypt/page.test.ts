import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import DecryptPage from './+page.svelte';

describe('DecryptPage Resolver worker selection', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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
