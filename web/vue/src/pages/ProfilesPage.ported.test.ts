import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render as vueRender, screen, waitFor, within } from '@testing-library/vue';
import type { Component } from 'vue';
import ProfilesPage from './ProfilesPage.vue';

function render(component: Component) {
  return vueRender(component, {
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  });
}

function scanResponse(worker: string, checked_at: string, items: unknown[]) {
  return new Response(JSON.stringify({
    checked_at,
    workers: [{ name: worker, status: 'success', checked_at, error_code: '' }],
    inventories: [{ worker, checked_at, items }]
  }), { status: 200 });
}

describe('ProfilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('shows worker service readiness placeholders before the first profile scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'local', checked_at: '2026-10-23T05:00:00Z', items: [] }],
          runtime_readiness: {
            checked_at: '2026-10-23T05:00:00Z',
            workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
            cells: [],
          },
        }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    const worker = within(hierarchy).getByRole('article', { name: 'Worker local' });
    expect(within(worker).getByRole('status', { name: 'Resolver: Belum dipindai' })).toBeTruthy();
    expect(within(worker).getByRole('status', { name: 'TorTTS: Belum dipindai' })).toBeTruthy();
    expect(within(worker).getByRole('status', { name: 'Quick Mode runtime: Belum dipindai' })).toBeTruthy();
  });

  it('offers delete for a non-default profile directly in its worker group', async () => {
    const requests: { url: string; method: string }[] = [];
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-1', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-24T05:00:00Z',
          workers: [{ name: 'remote-1', status: 'success', checked_at: '2026-10-24T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'remote-1', checked_at: '2026-10-24T05:00:00Z', items: [{
            name: 'irang', ready: true, deletable: true, reason_codes: [], checks: [],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' },
          }] }],
          runtime_readiness: {
            checked_at: '2026-10-24T05:00:00Z',
            workers: [{ name: 'remote-1', status: 'success' }],
            cells: [],
          },
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [] }), { status: 200 });
      }
      if (url === '/api/v1/workers/remote-1/profiles/local/irang' && method === 'DELETE') {
        return new Response(JSON.stringify({
          operation_id: 'delete-irang', kind: 'profile.local_delete',
          target: { worker: 'remote-1', profile: 'irang' }, status: 'queued',
          phase: 'queued', progress: {}, error: null, created_at: '2026-10-24T05:00:01Z',
        }), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const deleteButton = await screen.findByRole('button', { name: 'Hapus profil irang dari remote-1' });
    await fireEvent.click(deleteButton);
    await waitFor(() => expect(requests).toContainEqual({
      url: '/api/v1/workers/remote-1/profiles/local/irang', method: 'DELETE',
    }));
  });

  it('shows durable scan progress and readiness grouped by worker then profile', async () => {
    let scanReads = 0;
    const catalog = {
      checked_at: '2026-10-24T05:00:00Z',
      workers: [
        { name: 'local', status: 'success', checked_at: '2026-10-24T05:00:00Z', error_code: '' },
        { name: 'remote-1', status: 'success', checked_at: '2026-10-24T05:00:00Z', error_code: '' },
      ],
      inventories: [
        { worker: 'local', checked_at: '2026-10-24T05:00:00Z', items: [{
          name: 'default', ready: true, reason_codes: [], checks: [],
          upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' },
        }] },
        { worker: 'remote-1', checked_at: '2026-10-24T05:00:00Z', items: [{
          name: 'irang', ready: true, reason_codes: [], checks: [],
          upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' },
        }] },
      ],
      runtime_readiness: {
        checked_at: '2026-10-24T05:00:00Z',
        workers: [{ name: 'local', status: 'success' }, { name: 'remote-1', status: 'success' }],
        cells: [
          { worker: 'local', profile: null, runtime: 'resolver', status: 'ready', checked_at: '2026-10-24T05:00:00Z', reason_code: '' },
          { worker: 'local', profile: 'default', runtime: 'export', status: 'ready', checked_at: '2026-10-24T05:00:00Z', reason_code: '' },
          { worker: 'remote-1', profile: null, runtime: 'resolver', status: 'not_ready', checked_at: '2026-10-24T05:00:00Z', reason_code: 'RESOLVER_RUNTIME_UNAVAILABLE' },
          { worker: 'remote-1', profile: 'irang', runtime: 'export', status: 'not_ready', checked_at: '2026-10-24T05:00:00Z', reason_code: 'PROFILE_SESSION_UNAVAILABLE' },
        ],
      },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [
        { name: 'local', enabled: true, selected: true },
        { name: 'remote-1', enabled: true, selected: false },
      ] }), { status: 200 });
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify(catalog), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan' && method === 'POST') {
        return new Response(JSON.stringify({
          id: 'scan-1', status: 'running', error_code: '',
          progress: { workers: [{ name: 'remote-1', status: 'running', phase: 'runtime_probe', profiles: [
            { name: 'irang', status: 'running', phase: 'runtime_probe', error_code: '' },
          ] }], total_workers: 1, completed_workers: 0, total_profiles: 1, completed_profiles: 0 },
        }), { status: 202 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({ operation: null }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan/scan-1') {
        scanReads += 1;
        return new Response(JSON.stringify({
          id: 'scan-1', status: scanReads === 1 ? 'running' : 'succeeded', error_code: '',
          progress: { workers: [{ name: 'remote-1', status: scanReads === 1 ? 'running' : 'succeeded', phase: 'runtime_probe', profiles: [
            { name: 'irang', status: scanReads === 1 ? 'running' : 'succeeded', phase: 'runtime_probe', error_code: '' },
          ] }], total_workers: 1, completed_workers: scanReads === 1 ? 0 : 1, total_profiles: 1, completed_profiles: scanReads === 1 ? 0 : 1 },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-1' });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));

    const progress = await screen.findByRole('status', { name: 'Progress Scan Profil' });
    expect(progress.textContent).toMatch(/remote-1.*irang/);
    await waitFor(() => expect(progress.textContent).toMatch(/Scan selesai/), { timeout: 4000 });

    const hierarchy = screen.getByRole('region', { name: 'Kesiapan per worker dan profil' });
    const localWorker = within(hierarchy).getByRole('article', { name: 'Worker local' });
    const remoteWorker = within(hierarchy).getByRole('article', { name: 'Worker remote-1' });
    expect(within(localWorker).getByRole('region', { name: 'Profil default pada worker local' })).toBeTruthy();
    expect(within(localWorker).getByRole('status', { name: 'Export default: Siap' })).toBeTruthy();
    expect(within(remoteWorker).getByRole('status', { name: 'Resolver: Tidak siap' })).toBeTruthy();
    expect(within(remoteWorker).getByRole('region', { name: 'Profil irang pada worker remote-1' })).toBeTruthy();
    expect(within(remoteWorker).getByRole('status', { name: 'Export irang: Tidak siap' })).toBeTruthy();
  });

  it('scans only the selected worker and streams its raw log in a worker modal', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    let logReads = 0;
    const scan = {
      id: 'worker-scan-1', status: 'running', target: { kind: 'worker', worker: 'remote-1' },
      error_code: '', created_at: '2026-11-02T09:00:00Z', updated_at: '2026-11-02T09:00:00Z',
      progress: { workers: [{
        name: 'remote-1', status: 'running', phase: 'profile_probe', error_code: '',
        profiles: [{ name: 'default', status: 'running', phase: 'export_canary', error_code: '' }],
      }], total_workers: 1, completed_workers: 0, total_profiles: 1, completed_profiles: 0 },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [
        { name: 'local', enabled: true }, { name: 'remote-1', enabled: true },
      ] }), { status: 200 });
      if (url === '/api/v1/profiles/local') return new Response(JSON.stringify({
        checked_at: '2026-11-02T09:00:00Z',
        workers: [{ name: 'local', status: 'success', checked_at: 'local-old', error_code: '' },
          { name: 'remote-1', status: 'success', checked_at: 'remote-old', error_code: '' }],
        inventories: [{ worker: 'local', checked_at: 'local-old', items: [] },
          { worker: 'remote-1', checked_at: 'remote-old', items: [] }],
        runtime_readiness: { checked_at: '2026-11-02T09:00:00Z', workers: [], cells: [] },
      }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan/worker' && method === 'POST') {
        return new Response(JSON.stringify(scan), { status: 202 });
      }
      if (url.startsWith('/api/v1/profiles/local/scan/worker-scan-1/logs?')) {
        logReads += 1;
        const event = logReads === 1
          ? { sequence: 1, worker: 'remote-1', profile: 'default', runtime: 'export', kind: 'command', stream: 'system', text: '$ tdl chat export -c 123', exit_code: null, created_at: '2026-11-02T09:00:01Z' }
          : { sequence: 2, worker: 'remote-1', profile: 'default', runtime: 'export', kind: 'output', stream: 'stdout', text: '\u001b[32mExported 1\u001b[0m <script>raw</script>\r\n', exit_code: null, created_at: '2026-11-02T09:00:02Z' };
        return new Response(JSON.stringify({ events: [event], next_sequence: event.sequence, has_more: false }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan/worker-scan-1') return new Response(JSON.stringify(scan), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    const workerPicker = await screen.findByRole('combobox', { name: 'Worker' });
    await waitFor(() => expect(workerPicker.hasAttribute('disabled')).toBe(false));
    await fireEvent.change(workerPicker, {
      target: { value: 'remote-1' },
    });
    const scanButton = screen.getByRole('button', { name: 'Scan worker terpilih' });
    await waitFor(() => expect(scanButton.hasAttribute('disabled')).toBe(false));
    await fireEvent.click(scanButton);

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/local/scan/worker', method: 'POST',
      body: JSON.stringify({ worker: 'remote-1' }),
    });
    expect(requests.some((request) => request.url === '/api/v1/profiles/local/scan' && request.method === 'POST'))
      .toBe(false);
    const progress = await screen.findByRole('status', { name: 'Progress Scan Profil' });
    expect(progress.textContent).toContain('worker remote-1');
    await fireEvent.click(screen.getByRole('button', { name: 'Buka log realtime worker remote-1' }));

    const dialog = await screen.findByRole('dialog', { name: 'Worker remote-1' });
    await waitFor(() => expect(dialog.textContent).toContain('$ tdl chat export -c 123'));
    await waitFor(() => expect(dialog.textContent).toContain('Exported 1'), { timeout: 2500 });
    expect(dialog.textContent).toContain('Log diperbarui realtime');
    expect(dialog.textContent).toContain('<script>raw</script>');
    expect(dialog.querySelector('script')).toBeNull();
    expect(dialog.textContent).not.toContain('local-old');
    expect(requests.some((request) => request.url.includes('worker-scan-1/logs?worker=remote-1')))
      .toBe(true);
  });

  it('keeps worker scan logs available after the operation becomes terminal', async () => {
    const requests: string[] = [];
    const completedScan = {
      id: 'worker-scan-done', status: 'succeeded', target: { kind: 'worker', worker: 'local' },
      error_code: '', created_at: '2026-11-02T09:00:00Z', updated_at: '2026-11-02T09:01:00Z',
      progress: { workers: [{ name: 'local', status: 'succeeded', phase: 'complete', error_code: '',
        profiles: [{ name: 'default', status: 'succeeded', phase: 'complete', error_code: '' }] }],
        total_workers: 1, completed_workers: 1, total_profiles: 1, completed_profiles: 1 },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      requests.push(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url === '/api/v1/profiles/local') return new Response(JSON.stringify({
        checked_at: '2026-11-02T09:00:00Z', workers: [], inventories: [],
        runtime_readiness: { checked_at: '', workers: [], cells: [] },
      }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan/worker' && method === 'POST') return new Response(JSON.stringify(completedScan), { status: 202 });
      if (url.startsWith('/api/v1/profiles/local/scan/worker-scan-done/logs?')) return new Response(JSON.stringify({
        events: [{ sequence: 1, worker: 'local', profile: 'default', runtime: 'download', kind: 'exit', stream: 'system', text: 'process exited with code 1', exit_code: 1, created_at: '2026-11-02T09:00:02Z' }],
        next_sequence: 1, has_more: false,
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    const workerPicker = await screen.findByRole('combobox', { name: 'Worker' });
    await waitFor(() => expect(workerPicker.hasAttribute('disabled')).toBe(false));
    await fireEvent.change(workerPicker, { target: { value: 'local' } });
    const scanButton = screen.getByRole('button', { name: 'Scan worker terpilih' });
    await waitFor(() => expect(scanButton.hasAttribute('disabled')).toBe(false));
    await fireEvent.click(scanButton);
    expect(await screen.findAllByText(/Scan worker local selesai/)).toHaveLength(1);
    await fireEvent.click(screen.getByRole('button', { name: 'Buka log realtime worker local' }));

    const dialog = await screen.findByRole('dialog', { name: 'Worker local' });
    expect(requests.some((url) => url.includes('worker-scan-done/logs?worker=local'))).toBe(true);
    await waitFor(() => expect(dialog.textContent).toContain('process exited with code 1'));
    expect(dialog.textContent).toContain('exit 1');
    expect(requests.some((url) => url.includes('worker-scan-done/logs?worker=local'))).toBe(true);
  });

  it('keeps the worker log action available after a failed scan', async () => {
    const failedScan = {
      id: 'worker-scan-failed', status: 'failed', target: { kind: 'worker', worker: 'local' },
      error_code: 'PROFILE_SCAN_FAILED', created_at: '2026-11-02T09:00:00Z', updated_at: '2026-11-02T09:01:00Z',
      progress: { workers: [{ name: 'local', status: 'failed', phase: 'failed', error_code: 'WORKER_UNAVAILABLE',
        profiles: [{ name: 'default', status: 'failed', phase: 'failed', error_code: 'PROFILE_CANARY_FAILED' }] }],
        total_workers: 1, completed_workers: 1, total_profiles: 1, completed_profiles: 1 },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url === '/api/v1/profiles/local') return new Response(JSON.stringify({
        checked_at: '2026-11-02T09:01:00Z',
        workers: [{ name: 'local', status: 'failed', checked_at: '2026-11-02T09:01:00Z', error_code: 'WORKER_UNAVAILABLE' }],
        inventories: [],
        runtime_readiness: { checked_at: '', workers: [], cells: [] },
      }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan/worker' && method === 'POST') return new Response(JSON.stringify(failedScan), { status: 202 });
      if (url.startsWith('/api/v1/profiles/local/scan/worker-scan-failed/logs?')) return new Response(JSON.stringify({
        events: [{ sequence: 1, worker: 'local', profile: 'default', runtime: 'export', kind: 'error', stream: 'stderr', text: 'tdl exited with code 1', exit_code: 1, created_at: '2026-11-02T09:00:02Z' }],
        next_sequence: 1, has_more: false,
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    const workerPicker = await screen.findByRole('combobox', { name: 'Worker' });
    await waitFor(() => expect(workerPicker.hasAttribute('disabled')).toBe(false));
    await fireEvent.change(workerPicker, { target: { value: 'local' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Scan worker terpilih' }).hasAttribute('disabled')).toBe(false));
    await fireEvent.click(screen.getByRole('button', { name: 'Scan worker terpilih' }));
    await screen.findByRole('alert');
    expect((await screen.findByLabelText('Status scan local')).textContent).toContain('Worker offline');
    await fireEvent.click(screen.getByRole('button', { name: 'Buka log realtime worker local' }));

    const dialog = await screen.findByRole('dialog', { name: 'Worker local' });
    expect(await screen.findByText(/tdl exited with code 1/)).toBeTruthy();
    expect(dialog.textContent).toContain('exit 1');
  });

  it('shows worker-only Resolver readiness saved by Profile scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'local', checked_at: '2026-10-23T05:00:00Z', items: [] }],
          runtime_readiness: {
            checked_at: '2026-10-23T05:00:00Z',
            workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
            cells: [{ worker: 'local', profile: null, runtime: 'resolver', status: 'not_ready', checked_at: '2026-10-23T05:00:00Z', reason_code: 'RESOLVER_RUNTIME_UNAVAILABLE' }],
          },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    expect(within(hierarchy).getByRole('status', { name: 'Resolver: Tidak siap' })).toBeTruthy();
    expect(hierarchy.textContent).toContain('Addon Resolver tidak dapat digunakan pada worker.');
  });

  it('scans only the selected worker runtime and opens its safe attempt log', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    const catalog = {
      checked_at: '2026-10-31T10:00:00Z',
      workers: [{ name: 'local', status: 'success', checked_at: '2026-10-31T10:00:00Z', error_code: '' }],
      inventories: [{ worker: 'local', checked_at: '2026-10-31T10:00:00Z', items: [] }],
      runtime_readiness: {
        checked_at: '2026-10-31T10:00:00Z',
        workers: [{ name: 'local', status: 'success', checked_at: '2026-10-31T10:00:00Z', reason_code: '' }],
        cells: [{
          worker: 'local', profile: null, runtime: 'resolver', status: 'ready',
          checked_at: '2026-10-31T10:00:00Z', reason_code: '',
          last_attempt: {
            target: { worker: 'local', profile: null, runtime: 'resolver' },
            checked_at: '2026-10-31T10:00:00Z', phase: 'runtime_probe',
            checks: [{ name: 'resolver', status: 'ready', reason_code: '' }],
            status: 'ready', reason_code: '', dependencies: [],
            cleanup: { status: 'not_needed', reason_code: '' },
            stdout: 'NEVER-SHOW-RAW-OUTPUT',
          },
        }],
      },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') return new Response(JSON.stringify(catalog), { status: 200 });
      if (url === '/api/v1/profiles/local/scan') return new Response(JSON.stringify({ operation: null }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan/runtime' && method === 'POST') {
        return new Response(JSON.stringify({
          id: 'runtime-scan-1', status: 'running', target: {
            kind: 'worker_runtime', worker: 'local', runtime: 'resolver',
          }, error_code: '', progress: { workers: [{
            name: 'local', status: 'running', phase: 'runtime_probe', error_code: '',
            runtime: 'resolver', checks: { resolver: { ready: true, reason_code: '' } }, profiles: [],
          }], total_workers: 1, completed_workers: 0, total_profiles: 0, completed_profiles: 0 },
        }), { status: 202 });
      }
      if (url === '/api/v1/profiles/local/scan/runtime-scan-1') {
        return new Response(JSON.stringify({
          id: 'runtime-scan-1', status: 'succeeded', target: {
            kind: 'worker_runtime', worker: 'local', runtime: 'resolver',
          }, error_code: '', progress: { workers: [{
            name: 'local', status: 'succeeded', phase: 'complete', error_code: '',
            runtime: 'resolver', checks: { resolver: { ready: true, reason_code: '' } }, profiles: [],
          }], total_workers: 1, completed_workers: 1, total_profiles: 0, completed_profiles: 0 },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const scanButton = await screen.findByRole('button', { name: 'Scan Resolver worker local' });
    await fireEvent.click(scanButton);

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/local/scan/runtime',
      method: 'POST',
      body: JSON.stringify({ worker: 'local', runtime: 'resolver' }),
    });
    const progress = await screen.findByRole('article', { name: 'Progress worker local' });
    expect(progress.textContent).toContain('Resolver: Siap');
    await waitFor(() => expect(
      requests.some((request) => request.url === '/api/v1/profiles/local/scan/runtime-scan-1')
    ).toBe(true), { timeout: 2000 });
    expect(await screen.findByText('Resolver pada worker local: Siap.')).toBeTruthy();
    const logButton = screen.getByRole('button', { name: 'Lihat log uji Resolver worker local' });
    await fireEvent.click(logButton);
    const dialog = screen.getByRole('dialog', { name: 'Log uji Resolver · Worker local' });
    expect(dialog.textContent).toContain('Memeriksa runtime dan profil');
    expect(dialog.textContent).toContain('2026');
    expect(dialog.textContent).toContain('Siap');
    expect(dialog.textContent).not.toContain('NEVER-SHOW-RAW-OUTPUT');
  });

  it('targets profile service scans to one worker and profile and opens that cell log', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    const catalog = {
      checked_at: '2026-10-31T10:00:00Z',
      workers: [{ name: 'local', status: 'success', checked_at: '2026-10-31T10:00:00Z', error_code: '' }],
      inventories: [{ worker: 'local', checked_at: '2026-10-31T10:00:00Z', items: [{
        name: 'default', ready: true, deletable: false, reason_codes: [], checks: [],
        upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' },
      }] }],
      runtime_readiness: {
        checked_at: '2026-10-31T10:00:00Z',
        workers: [{ name: 'local', status: 'success', checked_at: '2026-10-31T10:00:00Z', reason_code: '' }],
        cells: [{
          worker: 'local', profile: 'default', runtime: 'storage', status: 'ready',
          checked_at: '2026-10-31T10:00:00Z', reason_code: '',
          last_attempt: {
            target: { worker: 'local', profile: 'default', runtime: 'storage' },
            checked_at: '2026-10-31T10:00:00Z', phase: 'storage_access_canary',
            checks: [{ name: 'upload', status: 'ready', reason_code: '' }, { name: 'storage', status: 'ready', reason_code: '' }],
            status: 'ready', reason_code: '', dependencies: ['upload'],
            cleanup: { status: 'succeeded', reason_code: '' },
            stdout: 'NEVER-SHOW-CANARY-OUTPUT',
          },
        }],
      },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url === '/api/v1/profiles/local') return new Response(JSON.stringify(catalog), { status: 200 });
      if (url === '/api/v1/profiles/local/scan') return new Response(JSON.stringify({ operation: null }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan/service' && method === 'POST') {
        const target = JSON.parse(String(init?.body || '{}')) as { worker: string; profile: string; runtime: string };
        return new Response(JSON.stringify({
          id: `profile-${target.runtime}-scan-1`, status: 'succeeded', target: {
            kind: 'profile_runtime', ...target,
          }, error_code: '', progress: { workers: [{
            name: 'local', status: 'succeeded', phase: 'complete', error_code: '',
            profiles: [{ name: 'default', status: 'succeeded', phase: 'complete', error_code: '', checks: {
              [target.runtime]: { ready: true, reason_code: '' },
            } }],
          }], total_workers: 1, completed_workers: 1, total_profiles: 1, completed_profiles: 1 },
        }), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Scan Storage profil default worker local' }));

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/local/scan/service',
      method: 'POST',
      body: JSON.stringify({ worker: 'local', profile: 'default', runtime: 'storage' }),
    });
    const logButton = screen.getByRole('button', { name: 'Lihat log uji Storage profil default worker local' });
    await fireEvent.click(logButton);
    const dialog = screen.getByRole('dialog', { name: 'Log uji Storage · Profil default · Worker local' });
    expect(dialog.textContent).toContain('Menguji akses Storage (export last 1)');
    expect(dialog.textContent).toContain('Upload');
    expect(dialog.textContent).toContain('Cleanup');
    expect(dialog.textContent).not.toContain('NEVER-SHOW-CANARY-OUTPUT');
    await fireEvent.click(screen.getByRole('button', { name: 'Tutup log uji' }));
    expect(screen.queryByRole('button', { name: 'Scan Quick Mode profil default worker local' })).toBeNull();
    expect(requests.some((request) => request.body?.includes('quick_mode'))).toBe(false);
  });

  it('shows worker-only rclone Storage readiness saved by Profile scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-1', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-29T05:00:00Z',
          workers: [{ name: 'remote-1', status: 'success', checked_at: '2026-10-29T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'remote-1', checked_at: '2026-10-29T05:00:00Z', items: [] }],
          runtime_readiness: {
            checked_at: '2026-10-29T05:00:00Z',
            workers: [{ name: 'remote-1', status: 'success', checked_at: '2026-10-29T05:00:00Z', reason_code: '' }],
            cells: [{ worker: 'remote-1', profile: null, runtime: 'rclone_storage', status: 'ready', checked_at: '2026-10-29T05:00:00Z', reason_code: '' }],
          },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    expect(within(hierarchy).getByRole('status', { name: 'Storage rclone: Siap' })).toBeTruthy();
  });

  it('shows Quick Mode and Export readiness under their worker profile', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'local', checked_at: '2026-10-23T05:00:00Z', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' },
          }] }],
          runtime_readiness: {
            checked_at: '2026-10-23T05:00:00Z',
            workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
            cells: [
              { worker: 'local', profile: 'default', runtime: 'export', status: 'ready', checked_at: '2026-10-23T05:00:00Z', reason_code: '' },
              { worker: 'local', profile: 'default', runtime: 'quick_mode', status: 'not_ready', checked_at: '2026-10-23T05:00:00Z', reason_code: 'TDL_ACCESS_NOT_VERIFIED' }
            ],
          },
        }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    const defaultProfile = within(within(hierarchy).getByRole('article', { name: 'Worker local' })).getByRole('region', { name: 'Profil default pada worker local' });
    expect(within(defaultProfile).getByRole('status', { name: 'Export default: Siap' })).toBeTruthy();
    expect(within(defaultProfile).getByRole('status', { name: 'Quick Mode default: Tidak siap' })).toBeTruthy();
    expect(hierarchy.textContent).toContain('Belum ada hasil command aktual untuk akses ini. Job tetap dapat dijalankan.');
  });

  it('shows Storage readiness per profile and worker from the saved scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', error_code: '' }],
          inventories: [{ worker: 'local', checked_at: '2026-10-23T05:00:00Z', items: [
            { name: 'default', ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } },
            { name: 'archive', ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } },
          ] }],
          runtime_readiness: {
            checked_at: '2026-10-23T05:00:00Z',
            workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
            cells: [
              { worker: 'local', profile: 'default', runtime: 'storage', status: 'ready', checked_at: '2026-10-23T05:00:00Z', reason_code: '' },
              { worker: 'local', profile: 'archive', runtime: 'storage', status: 'not_ready', checked_at: '2026-10-23T05:00:00Z', reason_code: 'TDL_ACCESS_NOT_VERIFIED' },
            ],
          },
        }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    const worker = within(hierarchy).getByRole('article', { name: 'Worker local' });
    const defaultProfile = within(worker).getByRole('region', { name: 'Profil default pada worker local' });
    const archiveProfile = within(worker).getByRole('region', { name: 'Profil archive pada worker local' });
    expect(within(defaultProfile).getByRole('status', { name: 'Storage default: Siap' })).toBeTruthy();
    expect(within(archiveProfile).getByRole('status', { name: 'Storage archive: Tidak siap' })).toBeTruthy();
    expect(hierarchy.textContent).toContain('Belum ada hasil command aktual untuk akses ini. Job tetap dapat dijalankan.');
  });

  it('starts a new profile login from the profile menu and displays the QR prompt', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true, selected: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [
          { name: 'local', enabled: true, online: true, secure: true }
        ] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/provisionings/login' && method === 'POST') {
        return new Response(JSON.stringify({ id: 'login-1', status: 'authenticating' }), { status: 200 });
      }
      if (url === '/api/v1/profiles/provisionings/login-1') {
        return new Response(JSON.stringify({
          id: 'login-1', profile: 'new-profile', source: 'login', status: 'authenticating', workers: [],
          login: { status: 'waiting', step: 'qr', qr_text: 'LOCAL-QR-CONTENT' }
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);

    const provisioningWorker = screen.getByRole('combobox', { name: 'Worker untuk menyiapkan sesi' });
    await waitFor(() => expect(provisioningWorker.querySelector('option[value="local"]')).toBeTruthy());
    await fireEvent.input(await screen.findByRole('textbox', { name: 'Nama profil' }), { target: { value: 'new-profile' } });
    await fireEvent.change(provisioningWorker, { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Login TDL' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai login QR' }));

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/provisionings/login',
      method: 'POST',
      body: JSON.stringify({ name: 'new-profile', worker: 'local', method: 'qr', phone: '', local_only: true })
    });
    expect(await screen.findByText('LOCAL-QR-CONTENT')).toBeTruthy();
    expect(screen.getByText('Pindai QR dengan Telegram pada perangkat yang ingin ditambahkan.')).toBeTruthy();
  });

  it('uploads a new profile only to the selected worker', async () => {
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true, selected: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/management') {
        return new Response(JSON.stringify({ items: [], workers: [
          { name: 'local', enabled: true, online: true, secure: true }
        ] }), { status: 200 });
      }
      if (url.startsWith('/api/v1/profiles/provisionings/upload?') && method === 'POST') {
        return new Response(JSON.stringify({ id: 'upload-1', status: 'distributing' }), { status: 200 });
      }
      if (url === '/api/v1/profiles/provisionings/upload-1') {
        return new Response(JSON.stringify({
          id: 'upload-1', profile: 'archive-profile', source: 'local_upload', status: 'distributing',
          workers: [{ worker: 'local', status: 'installing' }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    const { container } = render(ProfilesPage);

    const provisioningWorker = screen.getByRole('combobox', { name: 'Worker untuk menyiapkan sesi' });
    await waitFor(() => expect(provisioningWorker.querySelector('option[value="local"]')).toBeTruthy());
    await fireEvent.input(await screen.findByRole('textbox', { name: 'Nama profil' }), { target: { value: 'archive-profile' } });
    await fireEvent.change(provisioningWorker, { target: { value: 'local' } });
    const archiveInput = container.querySelector('input[type="file"]');
    expect(archiveInput).toBeTruthy();
    await fireEvent.change(archiveInput!, {
      target: { files: [new File(['session'], 'profile.zip', { type: 'application/zip' })] }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Validasi dan pasang profil' }));

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/provisionings/upload?name=archive-profile&worker=local&local_only=true',
      method: 'POST'
    });
    const operation = await screen.findByRole('article', { name: 'Penambahan profil archive-profile' });
    expect(operation.textContent).toContain('archive-profile · local');
    expect(operation.textContent).toContain('distributing');
  });

  it('scans every worker without a selection and shows partial results from the saved catalog', async () => {
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [
          { name: 'local', enabled: true, selected: true },
          { name: 'remote-2', enabled: true, selected: false }
        ] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan' && method === 'POST') {
        return new Response(JSON.stringify({
          checked_at: '2026-10-12T05:00:00+00:00',
          workers: [
            { name: 'local', status: 'failed', checked_at: '2026-10-12T05:00:00+00:00', error_code: 'WORKER_UNAVAILABLE' },
            { name: 'remote-2', status: 'success', checked_at: '2026-10-12T05:00:00+00:00', error_code: '' }
          ],
          runtime_readiness: {
            checked_at: '2026-10-12T05:00:00+00:00',
            workers: [
              { name: 'local', status: 'failed', checked_at: '2026-10-12T05:00:00+00:00', reason_code: 'WORKER_UNAVAILABLE' },
              { name: 'remote-2', status: 'success', checked_at: '2026-10-12T05:00:00+00:00', reason_code: '' }
            ],
            cells: [
              { worker: 'local', profile: 'irang', runtime: 'export', status: 'ready', checked_at: '2026-10-11T05:00:00+00:00', reason_code: '' },
              { worker: 'remote-2', profile: 'irang', runtime: 'export', status: 'ready', checked_at: '2026-10-12T05:00:00+00:00', reason_code: '' },
              { worker: 'remote-2', profile: 'archive', runtime: 'export', status: 'not_ready', checked_at: '2026-10-12T05:00:00+00:00', reason_code: 'PROFILE_SESSION_TDL_INVALID' },
              { worker: 'local', profile: 'irang', runtime: 'tts', status: 'ready', checked_at: '2026-10-11T05:00:00+00:00', reason_code: '' },
              { worker: 'remote-2', profile: 'irang', runtime: 'tts', status: 'not_ready', checked_at: '2026-10-12T05:00:00+00:00', reason_code: 'TDL_ACCESS_NOT_VERIFIED' },
              { worker: 'local', profile: null, runtime: 'tts_helper', status: 'ready', checked_at: '2026-10-12T05:00:00+00:00', reason_code: '' },
              { worker: 'local', profile: null, runtime: 'quick_mode_runtime', status: 'ready', checked_at: '2026-10-12T05:00:00+00:00', reason_code: '' }
            ]
          },
          inventories: [{ worker: 'remote-2', checked_at: '2026-10-12T05:00:00+00:00', items: [{
            name: 'irang', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' },
              { name: 'future_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-12T05:00:00+00:00' }
          }] }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    expect(screen.getByRole('link', { name: /Kelola Vault/ }).getAttribute('href')).toBe('/profiles/vault/');
    expect(requests.some((item) => item.url.endsWith('/profiles/local/scan') && item.method === 'POST')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));

    await waitFor(() => expect(document.body.textContent).toContain('Scan selesai: 1 worker berhasil, 1 gagal, 0 nonaktif.'));
    expect(screen.getByRole('alert').textContent).toContain('Worker offline');
    const hierarchy = screen.getByRole('region', { name: 'Kesiapan per worker dan profil' });
    expect(hierarchy.textContent).toMatch(/Worker local[\s\S]*Gagal · Worker offline/);
    const remoteWorker = within(hierarchy).getByRole('article', { name: 'Worker remote-2' });
    expect(remoteWorker.textContent).toContain('Profil irang');
    expect(within(remoteWorker).getByRole('status', { name: 'TTS irang: Tidak siap' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Kesiapan Utility per worker' })).toBeNull();
    expect(hierarchy.getAttribute('aria-label')).toBe('Kesiapan per worker dan profil');
    expect(requests).toContainEqual({ url: '/api/v1/profiles/local/scan', method: 'POST' });

    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });

    expect(await screen.findByText('irang')).toBeTruthy();
    expect(screen.getByText(/future session.*Siap/)).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Lane Upload irang' }).textContent).toMatch(/Lane Upload.*Siap/s);
    expect(screen.getByRole('region', { name: 'Hasil scan profil lokal' }).textContent).toContain('remote-2');
    expect(screen.getByRole('status', { name: 'Kesiapan Export irang pada remote-2' }).textContent).toMatch(/runtime Export · Siap/);
    expect(await screen.findByRole('button', { name: 'Adopsi profil irang dari remote-2 ke Vault' })).toBeTruthy();
    expect(requests.some((item) => item.url === '/api/v1/workers/remote-2/profiles/scan')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang worker' }));
    expect(screen.getByRole('region', { name: 'Kesiapan per worker dan profil' })).toBeTruthy();
    expect(screen.getByText('irang')).toBeTruthy();
    expect(requests.filter((item) => item.url.endsWith('/profiles/local/scan') && item.method === 'POST')).toHaveLength(1);
  });

  it('adopts a verified local profile into Vault without triggering distribution', async () => {
    const requests: { url: string; method: string; body?: string }[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: init?.body ? String(init.body) : undefined });
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan') return scanResponse(
        'local', '2026-10-15T00:00:00+00:00', [{
          name: 'archive', ready: true, deletable: true, reason_codes: [], checks: [
            { name: 'identity', ready: true, code: 'OK' },
            { name: 'root_session', ready: true, code: 'OK' },
            { name: 'user1_session', ready: true, code: 'OK' }
          ], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' }
        }]
      );
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url === '/api/v1/profiles/management') return new Response(JSON.stringify({ items: [
        { name: 'archive', vault: false, status: 'legacy' }
      ] }), { status: 200 });
      if (url === '/api/v1/profiles/archive/adopt' && method === 'POST') return new Response(JSON.stringify({ id: 'adopt-1', status: 'validating' }), { status: 200 });
      if (url === '/api/v1/profiles/provisionings/adopt-1') return new Response(JSON.stringify({
        id: 'adopt-1', profile: 'archive', source: 'adoption', status: 'stored', error: '', workers: []
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Adopsi profil archive dari local ke Vault' }));

    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('worker lain tidak akan diubah'));
    expect(requests).toContainEqual({
      url: '/api/v1/profiles/archive/adopt', method: 'POST', body: JSON.stringify({ worker: 'local' })
    });
    await waitFor(() => expect(document.body.textContent).toContain('Profil archive tersimpan di Vault. Tidak ada worker lain yang diubah.'));
    expect(screen.queryByRole('button', { name: 'Adopsi profil archive dari local ke Vault' })).toBeNull();
    expect(requests.some((request) => /sync|distribut|install_profile_bundle/i.test(request.url))).toBe(false);
  });

  it('shows worker failure and retries only after the operator presses Scan again', async () => {
    const requests: string[] = [];
    let scans = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push(`${method} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-1', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan' && method === 'POST') {
        scans += 1;
        if (scans === 1) {
          return new Response(JSON.stringify({
            checked_at: '2026-10-12T05:10:00+00:00',
            workers: [{ name: 'remote-1', status: 'failed', checked_at: '2026-10-12T05:10:00+00:00', error_code: 'WORKER_UNAVAILABLE' }],
            inventories: []
          }), { status: 200 });
        }
        return scanResponse('remote-1', '2026-10-12T05:10:00+00:00', []);
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-1' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-1' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Worker offline');
    const hierarchy = await screen.findByRole('region', { name: 'Kesiapan per worker dan profil' });
    expect(within(hierarchy).getByRole('article', { name: 'Worker remote-1' }).textContent).toContain('Gagal');
    expect(scans).toBe(1);
    await waitFor(() => {
      const scanButton = screen.getByRole('button', { name: 'Scan semua worker' });
      expect((scanButton as HTMLButtonElement).disabled).toBe(false);
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    expect(await screen.findByText(/Worker ini tidak memiliki profil lokal/)).toBeTruthy();
    expect(scans).toBe(2);
    expect(requests.filter((item) => item === 'POST /api/v1/profiles/local/scan')).toHaveLength(2);
  });

  it('refreshes Upload progress only while its preparation is running', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const requests: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push(`${method} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'running', phase: 'validating_upload', progress: 70, code: 'OK', updated_at: '2026-10-14T00:00:00+00:00' }
          }]
        }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({ checked_at: '', workers: [], inventories: [] }), { status: 200 });
      }
      if (url === '/api/v1/workers/local/profiles/local') {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:02+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [
              { name: 'identity', ready: true, code: 'OK' },
              { name: 'root_session', ready: true, code: 'OK' },
              { name: 'user1_session', ready: true, code: 'OK' }
            ],
            upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-14T00:00:02+00:00' }
          }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    const lane = await screen.findByRole('region', { name: 'Lane Upload default' });
    expect((within(lane).getByRole('progressbar', { name: 'Progress lane Upload default' }) as HTMLProgressElement).value).toBe(70);
    expect(lane.textContent).toContain('validating_upload');

    await waitFor(() => expect(requests).toContain('GET /api/v1/workers/local/profiles/local'), { timeout: 3000 });
    await waitFor(() => expect(lane.textContent).toContain('ready'));
    expect(requests.filter((request) => request.startsWith('GET /api/v1/workers/') && request.endsWith('/profiles/local'))).toHaveLength(1);
  });

  it('ignores a delayed progress response after selecting another worker', async () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const requests: string[] = [];
    let resolveOldWorkerStatus: ((response: Response) => void) | undefined;
    let finishOldWorkerRequest: (() => void) | undefined;
    const oldWorkerStatus = new Promise<Response>((resolve) => {
      resolveOldWorkerStatus = resolve;
    });
    const oldWorkerRequestFinished = new Promise<void>((resolve) => {
      finishOldWorkerRequest = resolve;
    });
    let markOldWorkerRequestStarted: (() => void) | undefined;
    const oldWorkerRequestStarted = new Promise<void>((resolve) => {
      markOldWorkerRequestStarted = resolve;
    });
    let runProgressRefresh: (() => void) | undefined;
    const realSetTimeout = globalThis.setTimeout.bind(globalThis);
    const setTimeoutMock = (handler: TimerHandler, timeout?: number, ...handlerArgs: unknown[]) => {
      const timer = realSetTimeout(handler, timeout, ...handlerArgs);
      if (timeout === 1500 && typeof handler === 'function') {
        runProgressRefresh = () => handler(...handlerArgs);
      }
      return timer;
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push(`${method} ${url}`);
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [
          { name: 'local', enabled: true },
          { name: 'remote-2', enabled: true }
        ] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [{
            name: 'default', ready: true, reason_codes: [], checks: [],
            upload_lane: { status: 'running', phase: 'copying', progress: 35, code: 'OK', updated_at: '2026-10-14T00:00:00+00:00' }
          }]
        }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local') {
        return new Response(JSON.stringify({ checked_at: '', workers: [], inventories: [] }), { status: 200 });
      }
      if (url === '/api/v1/workers/local/profiles/local') {
        markOldWorkerRequestStarted?.();
        return oldWorkerStatus.then((response) => {
          finishOldWorkerRequest?.();
          return response;
        });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    vi.stubGlobal('setTimeout', setTimeoutMock);
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    const lane = await screen.findByRole('region', { name: 'Lane Upload default' });
    expect((within(lane).getByRole('progressbar', { name: 'Progress lane Upload default' }) as HTMLProgressElement).value).toBe(35);

    runProgressRefresh?.();
    await oldWorkerRequestStarted;
    expect(requests).toContain('GET /api/v1/workers/local/profiles/local');
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    resolveOldWorkerStatus?.(new Response(JSON.stringify({
      worker: 'local', checked_at: '2026-10-14T00:00:02+00:00', items: [{
        name: 'default', ready: true, reason_codes: [], checks: [],
        upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '2026-10-14T00:00:02+00:00' }
      }]
    }), { status: 200 }));
    await oldWorkerRequestFinished;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByRole('progressbar', { name: 'Progress lane Upload default' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Adopsi profil default dari remote-2 ke Vault' })).toBeNull();
    expect(screen.queryByText('Sesi Upload terpisah sudah tervalidasi dan cocok dengan identitas profil.')).toBeNull();
  });

  it('confirms deletion with worker and profile names, then shows the durable result', async () => {
    const requests: { url: string; method: string; headers?: Headers }[] = [];
    const confirmation = vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, headers: new Headers(init?.headers) });
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'remote-2', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({
          worker: 'remote-2', checked_at: '2026-10-14T00:00:00+00:00', items: [
            { name: 'default', deletable: false, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } },
            { name: 'archive', deletable: true, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ],
          pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          operation_id: 'delete-op-1', kind: 'profile.local_delete', profile: 'archive',
          target: { profile: 'archive', worker: 'remote-2' }, status: 'succeeded',
          phase: 'completed', revision: 3, attempt: 1,
          progress: { identity_mapping_status: 'removed' }, created_at: '2026-10-14T00:00:00+00:00'
        }), { status: 202 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'remote-2' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));

    expect(await screen.findByText('archive')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Hapus profil default dari remote-2' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari remote-2' }));

    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('archive'));
    expect(confirmation).toHaveBeenCalledWith(expect.stringContaining('remote-2'));
    const request = requests.find((item) => item.method === 'DELETE');
    expect(request?.url).toBe('/api/v1/workers/remote-2/profiles/local/archive');
    expect(request?.headers?.get('Idempotency-Key')).toBeTruthy();
    expect(await screen.findByRole('region', { name: 'Operasi penghapusan profil' })).toBeTruthy();
    expect(screen.getByText('Mapping identitas dihapus setelah semua worker terverifikasi.')).toBeTruthy();
  });

  it('removes a stale local row when the fresh worker inventory confirms the profile is absent', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-15T00:00:00+00:00', items: [
            { name: 'archive', deletable: true, ready: false, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ], pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          error: { code: 'PROFILE_NOT_IN_LOCAL_SCAN', message: 'Profil archive tidak ditemukan pada hasil scan terbaru worker local.' }
        }), { status: 404 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    expect(await screen.findByRole('heading', { name: 'archive' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari local' }));

    expect(await screen.findByText(/Profil archive tidak ditemukan.*dihapus dari daftar lokal/i)).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'archive' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'Operasi penghapusan profil' })).toBeNull();
  });

  it('keeps the local row when the worker inventory is unavailable during delete preflight', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (url === '/api/v1/workers') {
        return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      }
      if (url === '/api/v1/profiles/local/scan') {
        return new Response(JSON.stringify({
          worker: 'local', checked_at: '2026-10-15T00:00:00+00:00', items: [
            { name: 'archive', deletable: true, ready: false, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
          ], pending_identity_cleanup: []
        }), { status: 200 });
      }
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/profiles/local/archive') && method === 'DELETE') {
        return new Response(JSON.stringify({
          error: { code: 'WORKER_UNAVAILABLE', message: 'Inventaris profil worker local tidak dapat dipastikan; tidak ada data yang dihapus.' }
        }), { status: 503 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));
    expect(await screen.findByRole('heading', { name: 'archive' })).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Hapus profil archive dari local' }));

    expect((await screen.findByRole('alert')).textContent).toMatch(/Inventaris profil worker local tidak dapat dipastikan/);
    expect(screen.getByRole('heading', { name: 'archive' })).toBeTruthy();
  });

  it('restores a pending deletion operation after a new page scan', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url === '/api/v1/workers') return new Response(JSON.stringify({ items: [{ name: 'local', enabled: true }] }), { status: 200 });
      if (url === '/api/v1/profiles/local/scan') return new Response(JSON.stringify({
        worker: 'local', checked_at: '2026-10-14T00:00:00+00:00', items: [
          { name: 'archive', deletable: true, ready: true, reason_codes: [], checks: [], upload_lane: { status: 'ready', phase: 'ready', progress: 100, code: 'OK', updated_at: '' } }
        ], pending_identity_cleanup: []
      }), { status: 200 });
      if (url === '/api/v1/operations?limit=100') return new Response(JSON.stringify({ items: [{
        operation_id: 'delete-op-recovered', kind: 'profile.local_delete', profile: 'archive',
        target: { profile: 'archive', worker: 'local' }, status: 'waiting_worker', phase: 'waiting_worker',
        revision: 2, attempt: 1, progress: { result: 'waiting_worker' }, created_at: '2026-10-14T00:00:00+00:00'
      }] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'local' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Scan semua worker' }));

    expect(await screen.findByText(/Menunggu worker online/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Hapus profil archive dari local' }).hasAttribute('disabled')).toBe(true);
  });
});
