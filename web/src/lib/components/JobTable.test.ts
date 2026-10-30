import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import JobTable from './JobTable.svelte';

describe('JobTable', () => {
  const dialogMethodDescriptors = Object.fromEntries(['showModal', 'close'].map((name) => [name, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)]));
  const visibilityStateDescriptor = Object.getOwnPropertyDescriptor(document, 'visibilityState');
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    if (visibilityStateDescriptor) Object.defineProperty(document, 'visibilityState', visibilityStateDescriptor);
    else delete (document as any).visibilityState;
    for (const [name, descriptor] of Object.entries(dialogMethodDescriptors)) {
      if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
      else delete (HTMLDialogElement.prototype as any)[name];
    }
  });

  async function flushPromises() {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  }

  it('shows an accessible empty state and global terminate action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    render(JobTable, { title: 'Daftar aktivitas' });
    expect(await screen.findByText('Belum ada job.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Terminate semua aktif' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh daftar job' })).toBeTruthy();
  });

  it('restores a completed backup verification report from history with a download action', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const report = { worker: 'remote-2', profile: 'default', run_id: 'run-123', status: 'verified' };
    const job = {
      id: 'backup-verify-1', kind: 'backup_verify', status: 'succeeded', profile: 'default', worker: 'remote-2',
      result: { value: { report } }, updated_at: '2026-10-11T08:00:00Z'
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.endsWith('/jobs/backup-verify-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(JobTable, { kind: 'backup_verify', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Unduh JSON verifikasi')).toBeTruthy();
  });

  it('uses Download and Export labels in operator worker logs without changing the raw API record', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const job = {
      id: 'export-log-1', kind: 'export', status: 'failed', profile: 'default', worker: 'local',
      created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:01Z'
    };
    const rawCommand = 'tdl --storage type=bolt,path=/data/user1/.tdl/data -n default chat export';
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/jobs/export-log-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ log: { lines: [rawCommand], order: 'oldest_first' } }), { status: 200 });
      if (url.endsWith('/events?after_sequence=0')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'export', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Log' }));

    const log = await screen.findByText(/tdl --storage/);
    expect(log.textContent).toContain('Export');
    expect(log.textContent).toContain('[lane Export]');
    expect(log.textContent).toContain('/data/user1/.tdl/data');
    expect(rawCommand).toContain('/data/user1/.tdl');
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

  it('shows TTS titles and a legacy fallback directly in history rows', async () => {
    const jobs = [
      {
        id: 'tts-with-title', kind: 'tts', status: 'succeeded', worker: 'local',
        payload: { title: 'Narasi: Ringkasan Perjalanan' }, updated_at: '2026-10-15T00:00:00Z'
      },
      {
        id: 'tts-without-title', kind: 'tts', status: 'failed', worker: 'remote-1',
        payload: {}, updated_at: '2026-10-14T00:00:00Z'
      }
    ];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: jobs }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'tts', view: 'history' });

    expect(await screen.findByRole('heading', { name: 'Narasi: Ringkasan Perjalanan' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Judul tidak tersedia' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Report' })).toHaveLength(2);
  });

  it('shows per-file Storage outcomes and retries only after safe-file confirmation', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const calls: { url: string; method?: string }[] = [];
    const job = {
      id: 'storage-1', kind: 'storage_upload', status: 'failed', profile: 'default', worker: 'local',
      created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:01Z', retryable: true,
      result: { value: { outcome: 'partial_failure', items: [
        { path: 'safe.txt', name: 'safe.txt', status: 'failed', attempt: 1, retryable: true, error: 'File gagal sebelum dikirim.' },
        { path: 'ambiguous.txt', name: 'ambiguous.txt', status: 'needs_reconciliation', upload_status: 'needs_reconciliation', cleanup_status: 'retained_ambiguous', attempt: 2, profile: 'archive', retryable: false, error: 'Hasil belum pasti.' },
        { path: 'changed.txt', name: 'changed.txt', status: 'succeeded', upload_status: 'succeeded', cleanup_status: 'skipped_source_changed', attempt: 1, retryable: false },
      ] } }
    };
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        return new Response(JSON.stringify({ items: query.get('kind') === 'storage_upload' ? [job] : [] }), { status: 200 });
      }
      if (url.endsWith('/jobs/storage-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.endsWith('/events?after_sequence=0') || url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/retry')) return new Response(JSON.stringify({ id: 'storage-2', status: 'queued' }), { status: 200 });
      if (url.endsWith('/reconcile')) return new Response(JSON.stringify({ id: 'reconcile-1', status: 'queued' }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'storage_upload', retryable: true, view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Retry file aman' }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('File dengan hasil ambigu tidak ikut dikirim'));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-1/retry') && call.method === 'POST')).toBe(true);
    await fireEvent.click(await screen.findByRole('button', { name: 'Rekonsiliasi' }));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-1/reconcile') && call.method === 'POST')).toBe(true);
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Hasil per file')).toBeTruthy();
    expect(screen.getByText('safe.txt')).toBeTruthy();
    expect(screen.getByText('ambiguous.txt')).toBeTruthy();
    expect(screen.getByText('Perlu verifikasi')).toBeTruthy();
    expect(screen.getByText('Upload: Perlu verifikasi')).toBeTruthy();
    expect(screen.getByText('Sumber: Dilewati · sumber berubah')).toBeTruthy();
  });

  it('lists and reopens safe Storage reconciliation results without exposing caption or path', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const reconciliation = {
      id: 'reconcile-1', kind: 'storage_reconcile', status: 'succeeded', profile: 'default', worker: 'local',
      payload: { source_job_id: 'storage-1' }, created_at: '2026-10-15T00:00:00Z', updated_at: '2026-10-15T00:00:01Z',
      result: { value: { items: [
        { index: 0, name: 'archive.zip', profile: 'archive', status: 'succeeded', match_count: 1, retryable: false, error: 'Caption ditemukan.' },
        { index: 1, name: 'missing.zip', profile: 'default', status: 'failed', match_count: 0, retryable: true, error: 'Aman untuk Retry.' },
      ] } }
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        return new Response(JSON.stringify({ items: query.get('kind') === 'storage_reconcile' ? [reconciliation] : [] }), { status: 200 });
      }
      if (url.endsWith('/jobs/reconcile-1')) return new Response(JSON.stringify(reconciliation), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    const { container } = render(JobTable, { kind: 'storage_upload', view: 'history' });
    expect(await screen.findByText('Storage reconcile')).toBeTruthy();
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Hasil rekonsiliasi caption')).toBeTruthy();
    expect(screen.getByText('archive.zip')).toBeTruthy();
    expect(screen.getByText('Caption cocok: 1')).toBeTruthy();
    expect(container.textContent).not.toContain('/workspace/');
  });

  it('uses a live active monitor query separate from terminal history', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running', profile: 'default', worker: 'local', payload: { quick_mode: true }, progress: { phase: 'downloading' } }] }), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, view: 'active', title: 'Monitor aktif' });

    expect(await screen.findByText('Sedang berjalan')).toBeTruthy();
    expect(urls.some((url) => decodeURIComponent(url).includes('status=queued,dispatched,running,paused'))).toBe(true);
    expect(screen.queryByText('History terbaru')).toBeNull();
  });

  it('keeps active job order stable when polling returns a different update order', async () => {
    const older = {
      id: 'job-older', kind: 'utility', status: 'running', created_at: '2026-10-05T09:00:00Z',
      updated_at: '2026-10-05T09:05:00Z', progress: { phase: 'compressing', message: 'Job lama' }
    };
    const newer = {
      id: 'job-newer', kind: 'utility', status: 'running', created_at: '2026-10-05T09:01:00Z',
      updated_at: '2026-10-05T09:04:00Z', progress: { phase: 'compressing', message: 'Job baru' }
    };
    let jobRequest = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequest += 1;
        const items = jobRequest === 1 ? [newer, older] : [older, newer];
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    const { container } = render(JobTable, { scope: 'global', view: 'active' });
    const order = () => Array.from(container.querySelectorAll('.idm-row b.truncate')).map((item) => item.textContent);

    await screen.findByText('Job lama');
    expect(order()).toEqual(['Job lama', 'Job baru']);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh monitor' }));
    await waitFor(() => expect(jobRequest).toBe(2));
    expect(order()).toEqual(['Job lama', 'Job baru']);
  });

  it('shows queue latency and worker activity from monitor metrics', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) {
        return new Response(JSON.stringify({
          active_jobs: 1,
          queued_jobs: 2,
          average_queue_wait_seconds: 8,
          event_latency: { count: 12, average_ms: 34.6 },
          workers: [{ worker: 'remote-1', status: 'busy', active_jobs: 1, queued_jobs: 2, last_seen_age_seconds: 4 }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running', profile: 'default', worker: 'remote-1', payload: {}, progress: { phase: 'downloading' } }] }), { status: 200 });
    }));

    render(JobTable, { scope: 'global', view: 'active' });

    expect(await screen.findByText('8 dtk')).toBeTruthy();
    expect(screen.getByText('35 ms · 12 event')).toBeTruthy();
    expect(screen.getByText('remote-1 · sibuk · 1 aktif · 2 antre')).toBeTruthy();
  });

  it('pauses and resumes Quick Mode jobs from the active monitor', async () => {
    const calls: { url: string; method?: string }[] = [];
    const job = {
      id: 'quick-live-1',
      kind: 'export',
      status: 'running',
      profile: 'default',
      worker: 'local',
      payload: { quick_mode: true },
      progress: { phase: 'downloading', message: 'file.mp4' },
      created_at: new Date().toISOString()
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/pause')) {
        job.status = 'paused';
        return new Response(JSON.stringify({ ...job }), { status: 200 });
      }
      if (url.endsWith('/resume')) {
        job.status = 'queued';
        return new Response(JSON.stringify({ ...job }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, view: 'active' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Jeda job' }));
    expect(await screen.findByRole('button', { name: 'Lanjutkan job' })).toBeTruthy();
    expect(calls.some((call) => call.url.endsWith('/pause') && call.method === 'POST')).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Lanjutkan job' }));
    expect(calls.some((call) => call.url.endsWith('/resume') && call.method === 'POST')).toBe(true);
  });

  it('keeps a feature job list manual while idle', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh daftar job' }));
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('refreshes feature job progress only while a relevant job is active', async () => {
    vi.useFakeTimers();
    let jobStatus = 'running';
    let jobRequests = 0;
    const metricsRequests: string[] = [];
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) {
        metricsRequests.push(url);
        return new Response(JSON.stringify({ active_jobs: 1 }), { status: 200 });
      }
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        const job = { id: 'active-1', kind: 'utility', status: jobStatus, progress: { phase: 'compressing' } };
        return new Response(JSON.stringify({ items: jobStatus === 'running' ? [job] : [{ ...job, status: 'succeeded' }] }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    await flushPromises();
    expect(jobRequests).toBe(1);
    expect(screen.getByText('Progress otomatis · job aktif')).toBeTruthy();

    jobStatus = 'succeeded';
    await vi.advanceTimersByTimeAsync(2500);
    await flushPromises();
    expect(jobRequests).toBe(2);
    expect(metricsRequests).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(jobRequests).toBe(2);
  });

  it('stops feature job polling when the page is left', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'utility', status: 'running' }] }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { unmount } = render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    await flushPromises();
    const initialRequests = fetchMock.mock.calls.length;
    unmount();

    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(initialRequests);
  });

  it('uses a faster Activity cadence for active jobs and slows down while idle', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    let jobRequests = 0;
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        const items = jobRequests === 1
          ? [{ id: 'active-1', kind: 'export', status: 'running' }]
          : [];
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { title: 'Daftar aktivitas', pollingMode: 'activity' });
    await flushPromises();
    expect(screen.getByText('Live · 2,5 dtk aktif / 10 dtk idle')).toBeTruthy();

    await vi.advanceTimersByTimeAsync(2499);
    expect(jobRequests).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(jobRequests).toBe(2);

    await vi.advanceTimersByTimeAsync(9999);
    expect(jobRequests).toBe(2);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(jobRequests).toBe(3);
  });

  it('pauses the Activity monitor while its tab is hidden and refreshes when visible', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    let jobRequests = 0;
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running' }] }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { title: 'Daftar aktivitas', pollingMode: 'activity' });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(jobRequests).toBe(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    await flushPromises();
    expect(jobRequests).toBe(2);
  });
});
