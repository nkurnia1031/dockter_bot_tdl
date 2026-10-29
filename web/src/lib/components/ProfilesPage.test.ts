import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ProfilesPage from './ProfilesPage.svelte';

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
    expect(hierarchy.textContent).toMatch(/Worker local[\s\S]*Resolver Belum dipindai/);
    expect(hierarchy.textContent).toMatch(/TorTTS Belum dipindai/);
    expect(hierarchy.textContent).toMatch(/Quick Mode runtime Belum dipindai/);
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
    expect(hierarchy.textContent).toMatch(/Worker local[\s\S]*default[\s\S]*Export.*Siap/);
    expect(hierarchy.textContent).toMatch(/Worker remote-1[\s\S]*Resolver Tidak siap[\s\S]*Profil irang[\s\S]*Export Tidak siap/);
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
    expect(hierarchy.textContent).toContain('Resolver Tidak siap');
    expect(hierarchy.textContent).toContain('Addon Resolver tidak dapat digunakan pada worker.');
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
    expect(hierarchy.textContent).toContain('Storage rclone Siap');
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
    expect(hierarchy.textContent).toMatch(/Profil default[\s\S]*Export Siap/);
    expect(hierarchy.textContent).toMatch(/Quick Mode Tidak siap/);
    expect(hierarchy.textContent).toContain('Bukti akses kirim tidak ada atau sudah stale');
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
    expect(hierarchy.textContent).toMatch(/Profil default[\s\S]*Storage Siap/);
    expect(hierarchy.textContent).toMatch(/Profil archive[\s\S]*Storage Tidak siap/);
    expect(hierarchy.textContent).toContain('Bukti akses kirim tidak ada atau sudah stale');
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
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai login TDL' }));

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
    await fireEvent.click(screen.getByRole('button', { name: 'Validasi dan simpan lokal' }));

    expect(requests).toContainEqual({
      url: '/api/v1/profiles/provisionings/upload?name=archive-profile&worker=local&local_only=true',
      method: 'POST'
    });
    expect(await screen.findByText('Memasang sesi pada worker terpilih')).toBeTruthy();
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

    expect(await screen.findByRole('region', { name: 'Status scan semua worker' })).toBeTruthy();
    const statuses = screen.getByRole('region', { name: 'Status scan semua worker' }).textContent || '';
    expect(statuses).toMatch(/local.*Gagal/);
    expect(statuses).toMatch(/remote-2.*Berhasil/);
    const hierarchy = screen.getByRole('region', { name: 'Kesiapan per worker dan profil' });
    expect(hierarchy.textContent).toMatch(/Worker local Gagal.*Worker offline/);
    expect(hierarchy.textContent).toMatch(/Worker remote-2[\s\S]*Profil irang[\s\S]*TTS Tidak siap.*Bukti akses kirim tidak ada atau sudah stale/);
    expect(screen.queryByRole('region', { name: 'Kesiapan Utility per worker' })).toBeNull();
    expect(hierarchy.getAttribute('aria-label')).toBe('Kesiapan per worker dan profil');
    expect(requests).toContainEqual({ url: '/api/v1/profiles/local/scan', method: 'POST' });

    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });

    expect(await screen.findByText('irang')).toBeTruthy();
    expect(screen.getByText(/Download.*Siap/)).toBeTruthy();
    expect(screen.getByText(/future_session.*Siap/)).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Lane Upload irang' }).textContent).toMatch(/Lane Upload.*Siap/s);
    expect(screen.getByText(/Hasil scan.*remote-2/)).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Kesiapan Export irang pada remote-2' }).textContent).toMatch(/runtime Export · Siap/);
    expect(await screen.findByRole('button', { name: 'Adopsi profil irang dari remote-2 ke Vault' })).toBeTruthy();
    expect(requests.some((item) => item.url === '/api/v1/workers/remote-2/profiles/scan')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang worker' }));
    expect(await screen.findByText(/katalog tetap memakai hasil Scan terakhir/i)).toBeTruthy();
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
    expect(await screen.findByText('Bundle tersimpan di Vault; belum didistribusikan')).toBeTruthy();
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

    expect((await screen.findByRole('region', { name: 'Status scan semua worker' })).textContent).toMatch(/remote-1.*Gagal/);
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
    expect(lane.textContent).toMatch(/70%/);
    expect(lane.textContent).toMatch(/Memvalidasi sesi Upload/);

    expect(await screen.findByText('Sesi Upload terpisah sudah tervalidasi dan cocok dengan identitas profil.', {}, { timeout: 3000 })).toBeTruthy();
    expect(requests).toContain('GET /api/v1/workers/local/profiles/local');
    expect(requests.filter((request) => request.startsWith('GET /api/v1/workers/') && request.endsWith('/profiles/local'))).toHaveLength(1);
  });

  it('ignores a delayed progress response after selecting another worker', async () => {
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
    expect((await screen.findByRole('region', { name: 'Lane Upload default' })).textContent).toMatch(/35%/);

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

    expect(screen.queryByRole('region', { name: 'Lane Upload default' })).toBeNull();
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

    expect(await screen.findByText('Menunggu worker online')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Hapus profil archive dari local' }).hasAttribute('disabled')).toBe(true);
  });
});
