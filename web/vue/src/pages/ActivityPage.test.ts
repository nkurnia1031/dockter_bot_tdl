import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ActivityPage from './ActivityPage.vue';
import JobMonitor from '../components/JobMonitor.vue';
import { session } from '../session';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn() }));
vi.mock('../lib/api', () => ({ api: mocks.api, post: mocks.post }));

const mountedWrappers: ReturnType<typeof mount>[] = [];
function mountPage() {
  const wrapper = mount(ActivityPage);
  mountedWrappers.push(wrapper);
  return wrapper;
}
function mountMonitor(props: Record<string, unknown>) {
  const wrapper = mount(JobMonitor, { props });
  mountedWrappers.push(wrapper);
  return wrapper;
}
function unmountTracked(wrapper: ReturnType<typeof mount>) {
  wrapper.unmount();
  const index = mountedWrappers.indexOf(wrapper);
  if (index >= 0) mountedWrappers.splice(index, 1);
}

describe('ActivityPage', () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.post.mockReset();
    session.current = { authenticated: true, actor: { telegram_user_id: 17, profile: 'default', worker_route: 'local' }, profiles: ['default'] };
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [], active_jobs: 0, queued_jobs: 0 });
      return Promise.resolve({ items: [] });
    });
  });
  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('polls at 2.5 seconds for active jobs, then slows to 10 seconds while idle', async () => {
    vi.useFakeTimers();
    let reads = 0;
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) {
        reads += 1;
        return Promise.resolve({ items: reads === 1 ? [{ id: 'job-1', kind: 'storage_upload', worker: 'local', status: 'running', progress: { phase: 'uploading', message: 'Mengirim file', overall: { files_current: 1, files_total: 3, bytes_current: 1048576, bytes_total: 4194304 }, active_items: [{ name: 'a.zip', profile: 'default', percent: 31, bytes_current: 350, size_bytes: 1000, speed_text: '4 MiB/s' }, { name: 'b.zip', profile: 'irang', percent: 16, bytes_current: 320, size_bytes: 2000, speed_text: '2 MiB/s' }] } }] : [] });
      }
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [], active_jobs: 1, queued_jobs: 0 });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('Mengirim file');
    expect(wrapper.text()).toContain('default · a.zip');
    expect(wrapper.text()).toContain('irang · b.zip');
    expect(wrapper.text()).toContain('4 MiB/s');
    expect(wrapper.text()).toContain('350 B / 1000 B');
    expect(wrapper.text()).toContain('Batch 1/3 file');
    expect(wrapper.text()).toContain('1.0 MB / 4.0 MB batch');
    await vi.advanceTimersByTimeAsync(2499);
    expect(reads).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(reads).toBe(2);
    await vi.advanceTimersByTimeAsync(9999);
    expect(reads).toBe(2);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(reads).toBe(3);
    unmountTracked(wrapper);
  });

  it('stops polling while hidden, refreshes when visible, and cleans up on unmount', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    let reads = 0;
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) {
        reads += 1;
        return Promise.resolve({ items: [{ id: 'job-1', kind: 'export', worker: 'local', status: 'running' }] });
      }
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountPage();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reads).toBe(1);
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    await flushPromises();
    expect(reads).toBe(2);
    unmountTracked(wrapper);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reads).toBe(2);
  });

  it('filters jobs and cancels a selected job through the existing API', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [
        { id: 'job-active', kind: 'export', worker: 'local', status: 'running', progress: { message: 'Masih berjalan' } },
        { id: 'job-failed', kind: 'storage_upload', worker: 'remote-1', status: 'failed', error: { code: 'TDL_UPLOAD_FAILED' } }
      ] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [], active_jobs: 1, queued_jobs: 0 });
      return Promise.resolve({});
    });
    mocks.post.mockResolvedValue({ cancel_requested: 1 });

    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('Masih berjalan');
    expect(wrapper.text()).toContain('TDL_UPLOAD_FAILED');
    await wrapper.get('select[aria-label="Filter status"]').setValue('failed');
    expect(wrapper.text()).toContain('TDL_UPLOAD_FAILED');
    expect(wrapper.text()).not.toContain('Masih berjalan');

    await wrapper.get('select[aria-label="Filter status"]').setValue('all');
    await wrapper.get('button[aria-label="Hentikan job job-active"]').trigger('click');
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true);
    await wrapper.get('button[aria-label="Konfirmasi hentikan job"]').trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/jobs/job-active/cancel');
    unmountTracked(wrapper);
  });

  it('stops feature-scoped progress polling after its active job reaches a terminal state', async () => {
    vi.useFakeTimers();
    let reads = 0;
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) {
        reads += 1;
        const job = { id: 'feature-job', kind: 'utility', worker: 'local', status: reads === 1 ? 'running' : 'succeeded' };
        return Promise.resolve({ items: [job] });
      }
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ active_jobs: 1 });
      return Promise.resolve({});
    });

    const wrapper = mountMonitor({ kind: 'utility', title: 'Utility', pollingMode: 'active' });
    await flushPromises();
    expect(reads).toBe(1);
    await vi.advanceTimersByTimeAsync(2500);
    await flushPromises();
    expect(reads).toBe(2);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(reads).toBe(2);
    unmountTracked(wrapper);
  });

  it('forwards worker/profile filters and avoids unscoped bulk stop in a worker-filtered monitor', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'utility-1', kind: 'utility', worker: 'remote-1', status: 'running' }] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    const wrapper = mountMonitor({ title: 'Utility', kind: 'utility', scope: 'global', worker: 'remote-1', profile: 'ruth', pollingMode: 'activity' });
    await flushPromises();
    const jobsRequest = mocks.api.mock.calls.map(([path]) => String(path)).find((path) => path.startsWith('/jobs?'));
    expect(jobsRequest).toContain('worker=remote-1');
    expect(jobsRequest).toContain('profile=ruth');
    expect(wrapper.find('button[aria-label="Terminate semua job aktif"]').exists()).toBe(false);
    expect(wrapper.find('button[aria-label="Hentikan job utility-1"]').exists()).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
    unmountTracked(wrapper);
  });

  it('keeps profile-scoped terminate-all limited to that profile', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'profile-job', kind: 'storage_upload', worker: 'local', status: 'running' }] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    mocks.post.mockResolvedValue({ cancel_requested: 1 });

    const wrapper = mountMonitor({ title: 'Upload profil', kind: 'storage_upload', profile: 'ruth', pollingMode: 'activity' });
    await flushPromises();
    await wrapper.get('button[aria-label="Terminate semua job aktif"]').trigger('click');
    await wrapper.get('button[aria-label="Konfirmasi hentikan job"]').trigger('click');
    await flushPromises();
    expect(mocks.post.mock.calls[0][0]).toBe('/jobs/terminate-active?scope=current&profile=ruth&kind=storage_upload');
    unmountTracked(wrapper);
  });

  it('limits current-scope terminate-all to the authenticated profile', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'current-job', kind: 'utility', worker: 'local', status: 'running' }] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    mocks.post.mockResolvedValue({ cancel_requested: 1 });
    const wrapper = mountMonitor({ title: 'Utility', kind: 'utility', scope: 'current', pollingMode: 'activity' });
    await flushPromises();
    await wrapper.get('button[aria-label="Terminate semua job aktif"]').trigger('click');
    await wrapper.get('button[aria-label="Konfirmasi hentikan job"]').trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/jobs/terminate-active?scope=current&profile=default&kind=utility');
    unmountTracked(wrapper);
  });

  it('uses per-job cancellation instead of unscoped bulk stop in a worker-filtered monitor', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'worker-job', kind: 'utility', worker: 'remote-1', status: 'running' }] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    mocks.post.mockResolvedValue({ status: 'running' });
    const wrapper = mountMonitor({ title: 'Worker Utility', kind: 'utility', worker: 'remote-1', scope: 'global', pollingMode: 'activity' });
    await flushPromises();
    expect(wrapper.find('button[aria-label="Terminate semua job aktif"]').exists()).toBe(false);
    await wrapper.get('button[aria-label="Hentikan job worker-job"]').trigger('click');
    await wrapper.get('button[aria-label="Konfirmasi hentikan job"]').trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/jobs/worker-job/cancel');
    expect(mocks.post).not.toHaveBeenCalledWith(expect.stringContaining('/jobs/terminate-active'));
    unmountTracked(wrapper);
  });

  it('avoids unscoped bulk stop in a global monitor filtered by profile', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'profile-filtered-job', kind: 'utility', worker: 'remote-1', profile: 'ruth', status: 'running' }] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    const wrapper = mountMonitor({ title: 'Profil Ruth', kind: 'utility', profile: 'ruth', scope: 'global', pollingMode: 'activity' });
    await flushPromises();
    const jobsRequest = mocks.api.mock.calls.map(([path]) => String(path)).find((path) => path.startsWith('/jobs?'));
    expect(jobsRequest).toContain('profile=ruth');
    expect(wrapper.find('button[aria-label="Terminate semua job aktif"]').exists()).toBe(false);
    await wrapper.get('button[aria-label="Hentikan job profile-filtered-job"]').trigger('click');
    await wrapper.get('button[aria-label="Konfirmasi hentikan job"]').trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/jobs/profile-filtered-job/cancel');
    expect(mocks.post.mock.calls.some(([path]) => String(path).includes('/jobs/terminate-active'))).toBe(false);
    unmountTracked(wrapper);
  });

  it('keeps active ordering stable and shows worker queue and event metrics', async () => {
    const jobs = [
      { id: 'newer', kind: 'utility', worker: 'remote-1', status: 'running', created_at: '2026-11-11T09:01:00Z' },
      { id: 'older', kind: 'utility', worker: 'remote-1', status: 'running', created_at: '2026-11-11T09:00:00Z' }
    ];
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: jobs });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ active_jobs: 2, queued_jobs: 3, average_queue_wait_seconds: 8, event_latency: { average_ms: 34.6 }, workers: [{ worker: 'remote-1', status: 'busy', active_jobs: 2, queued_jobs: 3 }] });
      return Promise.resolve({});
    });

    const wrapper = mountPage();
    await flushPromises();
    const rowLabels = wrapper.findAll('tbody tr td:first-child strong').map((node) => node.text());
    expect(rowLabels).toEqual(['utility', 'utility']);
    const ids = wrapper.findAll('tbody tr td:first-child small').map((node) => node.text());
    expect(ids[0]).toContain('#older');
    expect(ids[1]).toContain('#newer');
    expect(wrapper.text()).toContain('8 dtk');
    expect(wrapper.text()).toContain('35 ms');
    expect(wrapper.text()).toContain('remote-1 · busy · 2 aktif · 3 antre');
    unmountTracked(wrapper);
  });

  it('asks before safe Storage retry and displays structured per-file outcomes without raw details', async () => {
    const job = {
      id: 'storage-safe-retry', kind: 'storage_upload', status: 'failed', worker: 'local', retryable: true,
      result: { value: { items: [
        { name: 'exists.zip', status: 'skipped', upload_status: 'skipped', cleanup_status: 'retained_existing_target', reason_code: 'STORAGE_TARGET_EXISTS', error: 'private caption and /workspace/private.zip' },
        { name: 'safe.zip', status: 'failed', retryable: true, error: 'internal error details' }
      ] } }
    };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: path.includes('kind=storage_upload') ? [job] : [] });
      if (path === '/jobs/storage-safe-retry') return Promise.resolve(job);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });
    mocks.post.mockResolvedValue({ id: 'retry-job' });
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);

    const wrapper = mountMonitor({ title: 'Storage', kind: 'storage_upload', retryable: true, view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text() === 'Retry file aman')!.trigger('click');
    await flushPromises();
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('File dengan hasil ambigu tidak ikut dikirim'));
    expect(mocks.post).toHaveBeenCalledWith('/jobs/storage-safe-retry/retry');
    await wrapper.get('button[aria-label="Detail job storage-safe-retry"]').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('Dilewati · target sudah ada');
    expect(wrapper.text()).toContain('Sumber disimpan · target sudah ada');
    expect(wrapper.text()).toContain('STORAGE_TARGET_EXISTS');
    expect(wrapper.text()).not.toContain('private caption');
    expect(wrapper.text()).not.toContain('/workspace/private.zip');
    expect(wrapper.text()).not.toContain('internal error details');
    unmountTracked(wrapper);
  });

  it('shows safe Storage reconciliation matches without caption or local path details', async () => {
    const job = {
      id: 'storage-reconcile-safe', kind: 'storage_reconcile', status: 'succeeded', worker: 'local',
      result: { value: { items: [{ name: 'archive.zip', status: 'succeeded', match_count: 1, profile: 'default', error: 'CAPTION_SECRET /workspace/private/archive.zip' }] } }
    };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: path.includes('kind=storage_reconcile') ? [job] : [] });
      if (path === '/jobs/storage-reconcile-safe') return Promise.resolve(job);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountMonitor({ title: 'Storage', kind: 'storage_reconcile', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job storage-reconcile-safe"]').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('archive.zip');
    expect(wrapper.text()).toContain('Berhasil');
    expect(wrapper.text()).toContain('caption cocok: 1');
    expect(wrapper.text()).not.toContain('CAPTION_SECRET');
    expect(wrapper.text()).not.toContain('/workspace/private/archive.zip');
    unmountTracked(wrapper);
  });

  it('restores the accepted cancellation acknowledgement from the latest job snapshot', async () => {
    const job = { id: 'cancel-accepted', kind: 'export', status: 'running', worker: 'local', progress: { phase: 'exporting', cancel_request: { status: 'accepted' } } };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain('Permintaan berhenti diterima; menunggu konfirmasi worker');
    expect(wrapper.find('[role="status"].cancel-accepted').exists()).toBe(true);
    unmountTracked(wrapper);
  });

  it('keeps checking a disappeared job until its detail endpoint confirms a terminal state', async () => {
    let jobListReads = 0;
    let detailReads = 0;
    const finished = vi.fn();
    const onFinished = (event: Event) => finished((event as CustomEvent).detail.jobIds);
    window.addEventListener('tme3:job-finished', onFinished);
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) {
        jobListReads += 1;
        return Promise.resolve({ items: jobListReads === 1 ? [{ id: 'vanished-job', kind: 'export', status: 'running', worker: 'local' }] : [] });
      }
      if (path === '/jobs/vanished-job') {
        detailReads += 1;
        return Promise.resolve({ id: 'vanished-job', kind: 'export', status: detailReads === 1 ? 'running' : 'succeeded', worker: 'local' });
      }
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    vi.useFakeTimers();

    const wrapper = mountPage();
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2500);
    await flushPromises();
    expect(detailReads).toBe(1);
    expect(finished).not.toHaveBeenCalled();
    await wrapper.get('button[aria-label="Refresh daftar job"]').trigger('click');
    await flushPromises();
    expect(detailReads).toBe(2);
    expect(finished).toHaveBeenCalledWith(['vanished-job']);
    window.removeEventListener('tme3:job-finished', onFinished);
    unmountTracked(wrapper);
  });

  it('shows each Storage download result, relative path, and public link in job details', async () => {
    const job = {
      id: 'download-links', kind: 'storage_download', status: 'failed', worker: 'remote-1',
      result: { value: { succeeded: 1, failed: 1, items: [
        { name: 'report.pdf', relative_path: 'Reports/2026/report.pdf', download_status: 'succeeded', link_status: 'succeeded', public_url: 'https://worker.example/public/download/token-1' },
        { name: 'existing.zip', relative_path: 'Reports/existing.zip', download_status: 'failed', link_status: 'not_created', error: 'File tujuan sudah ada; file tidak ditimpa.' }
      ] } }
    };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/download-links') return Promise.resolve(job);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountMonitor({ title: 'Download', kind: 'storage_download', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job download-links"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[aria-label="Hasil download per file"]').text()).toContain('Reports/2026/report.pdf');
    expect(wrapper.text()).toContain('Download berhasil · Link siap');
    expect(wrapper.get('a[href="https://worker.example/public/download/token-1"]').attributes('href')).toBe('https://worker.example/public/download/token-1');
    expect(wrapper.text()).toContain('Download gagal · Link tidak dibuat');
    expect(wrapper.text()).toContain('File tujuan sudah ada; file tidak ditimpa.');
    unmountTracked(wrapper);
  });

  it('uses the legacy fallback for TTS jobs with a missing or blank title', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [
        { id: 'tts-empty-title', kind: 'tts', status: 'succeeded', worker: 'local', payload: { title: '  ' } },
        { id: 'tts-no-title', kind: 'tts', status: 'failed', worker: 'remote-1', payload: {} }
      ] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    const wrapper = mountMonitor({ title: 'TTS', kind: 'tts', view: 'history', pollingMode: 'active' });
    await flushPromises();
    expect(wrapper.findAll('tbody tr td:first-child strong').map((node) => node.text())).toEqual(['Judul tidak tersedia', 'Judul tidak tersedia']);
    unmountTracked(wrapper);
  });

  it('filters Quick Mode globally and retries the failed export through the existing API', async () => {
    const job = { id: 'quick-failed', kind: 'export', status: 'failed', worker: 'remote-1', profile: 'archive', payload: { quick_mode: true } };
    const jobReads: string[] = [];
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) {
        jobReads.push(path);
        return Promise.resolve({ items: [job] });
      }
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    mocks.post.mockResolvedValue({ id: 'quick-retry', status: 'queued' });
    const wrapper = mountMonitor({ title: 'Quick Mode', kind: 'export', scope: 'global', quickMode: true, retryable: true, view: 'history', pollingMode: 'active' });
    await flushPromises();
    const params = new URL(jobReads[0], 'http://localhost').searchParams;
    expect(params.get('scope')).toBe('global');
    expect(params.get('kind')).toBe('export');
    expect(params.get('quick_mode')).toBe('true');
    await wrapper.findAll('button').find((button) => button.text() === 'Retry')!.trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/jobs/quick-failed/retry');
    unmountTracked(wrapper);
  });

  it('labels raw worker TDL log lines by Download and Export lane without changing API data', async () => {
    const job = { id: 'tdl-lane-log', kind: 'export', status: 'failed', worker: 'local' };
    const rawLines = [
      'tdl --storage type=bolt,path=/database/tdl/default/root/.tdl/data --timeout 20',
      'tdl --storage type=bolt,path=/database/tdl/default/user1/.tdl/data -n default chat export'
    ];
    const rawSnapshot = { log: { lines: rawLines, order: 'oldest_first' } };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/tdl-lane-log') return Promise.resolve(job);
      if (path.endsWith('/log-snapshot')) return Promise.resolve(rawSnapshot);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountMonitor({ title: 'Export', kind: 'export', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job tdl-lane-log"]').trigger('click');
    await flushPromises();
    await wrapper.get('.detail-tabs button:nth-of-type(3)').trigger('click');
    expect(wrapper.get('.log-body pre').text()).toContain('[lane Download]');
    expect(wrapper.get('.log-body pre').text()).toContain('[lane Export]');
    expect(wrapper.get('.log-body pre').text()).toContain('/database/tdl/default/user1/.tdl');
    expect(rawSnapshot.log.lines).toEqual(rawLines);
    unmountTracked(wrapper);
  });

  it('preserves command, output, exit code, duration, and truncation details in events', async () => {
    const job = { id: 'command-event', kind: 'export', status: 'failed', worker: 'local' };
    const events = [{
      sequence: 4,
      event_type: 'command.completed',
      status: 'failed',
      created_at: '2026-11-11T10:00:00Z',
      result: { command: ['tdl', 'chat', 'export', '--limit', '1'], output_tail: ['export failed'], returncode: 2, duration_seconds: 3.25, output_truncated: true }
    }];
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/command-event') return Promise.resolve(job);
      if (path === '/jobs/command-event/events?after_sequence=0') return Promise.resolve({ items: events });
      if (path.endsWith('/log-snapshot')) return Promise.resolve({ log: { lines: [] } });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountMonitor({ title: 'Export', kind: 'export', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job command-event"]').trigger('click');
    await flushPromises();
    await wrapper.get('.detail-tabs button:nth-of-type(2)').trigger('click');
    expect(wrapper.get('.event-list .command-line').text()).toContain('$ tdl chat export --limit 1');
    expect(wrapper.get('.event-list .command-output').text()).toBe('export failed');
    expect(wrapper.get('.event-list').text()).toContain('exit 2 · 3.25 dtk · output lama dipangkas');
    unmountTracked(wrapper);
  });

  it('shows and copies the raw job plus event JSON from the detail modal', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const job = { id: 'raw-json-job', kind: 'export', status: 'failed', worker: 'local', error: { code: 'TDL_FAILED' } };
    const events = [{ sequence: 1, event_type: 'job.failed', status: 'failed', result: { reason_code: 'TDL_FAILED' } }];
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/raw-json-job') return Promise.resolve(job);
      if (path === '/jobs/raw-json-job/events?after_sequence=0') return Promise.resolve({ items: events });
      if (path.endsWith('/log-snapshot')) return Promise.resolve({ log: { lines: [] } });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountMonitor({ title: 'Export', kind: 'export', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job raw-json-job"]').trigger('click');
    await flushPromises();
    await wrapper.get('.detail-tabs button:nth-of-type(4)').trigger('click');
    const rawJson = wrapper.get('.raw-body pre').text();
    expect(rawJson).toContain('raw-json-job');
    expect(rawJson).toContain('job.failed');
    await wrapper.findAll('button').find((button) => button.text() === 'Salin JSON')!.trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith(rawJson);
    expect(wrapper.get('[role="dialog"] [role="status"]').text()).toContain('JSON job disalin');
    unmountTracked(wrapper);
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor);
    else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
  });

  it('reports clipboard failure instead of claiming a job log was copied', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const job = { id: 'clipboard-job', kind: 'export', status: 'failed', worker: 'local' };
    const writeText = vi.fn().mockRejectedValue(new Error('permission denied'));
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/clipboard-job') return Promise.resolve(job);
      if (path.endsWith('/log-snapshot')) return Promise.resolve({ log: { lines: ['log line'] } });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountMonitor({ title: 'Export', kind: 'export', view: 'history', pollingMode: 'active' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job clipboard-job"]').trigger('click');
    await flushPromises();
    await wrapper.get('.detail-tabs button:nth-of-type(3)').trigger('click');
    await wrapper.findAll('button').find((button) => button.text() === 'Salin log')!.trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith('log line');
    expect(wrapper.get('[role="dialog"] [role="alert"]').text()).toContain('Log tidak dapat disalin');
    expect(wrapper.find('.job-monitor > .notice-error').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('Log disalin.');
    unmountTracked(wrapper);
    if (descriptor) Object.defineProperty(navigator, 'clipboard', descriptor);
    else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
  });

  it('returns focus to the monitor when refresh removes the dialog opener', async () => {
    let removed = false;
    const job = { id: 'vanishing-detail', kind: 'export', status: 'running', worker: 'local' };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: removed ? [] : [job] });
      if (path === '/jobs/vanishing-detail') return Promise.resolve(job);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mount(JobMonitor, { attachTo: document.body, props: { title: 'Active', kind: 'export', view: 'active', pollingMode: 'active' } });
    mountedWrappers.push(wrapper);
    await flushPromises();
    const opener = wrapper.get('button[aria-label="Detail job vanishing-detail"]').element as unknown as HTMLElement;
    opener.focus();
    await wrapper.get('button[aria-label="Detail job vanishing-detail"]').trigger('click');
    await flushPromises();
    removed = true;
    await wrapper.get('button[aria-label="Refresh daftar job"]').trigger('click');
    await flushPromises();
    await wrapper.get('button[aria-label="Tutup detail"]').trigger('click');
    await flushPromises();
    expect(document.activeElement).toBe(wrapper.get('.job-monitor').element);
    unmountTracked(wrapper);
  });

  it('pauses and resumes Quick Mode using the shared job actions', async () => {
    const job = { id: 'quick-active', kind: 'export', status: 'running', worker: 'local', payload: { quick_mode: true }, created_at: new Date().toISOString() };
    const calls: string[] = [];
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    mocks.post.mockImplementation((path: string) => {
      calls.push(path);
      if (path.endsWith('/pause')) job.status = 'paused';
      if (path.endsWith('/resume')) job.status = 'queued';
      return Promise.resolve(job);
    });

    const wrapper = mountMonitor({ title: 'Quick Mode', kind: 'export', scope: 'global', quickMode: true, pollingMode: 'activity' });
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text() === 'Jeda')!.trigger('click');
    expect(calls).toContain('/jobs/quick-active/pause');
    expect(wrapper.text()).toContain('paused');
    await flushPromises();
    await wrapper.findAll('button').find((button) => button.text() === 'Lanjutkan')!.trigger('click');
    await flushPromises();
    expect(calls).toContain('/jobs/quick-active/resume');
    expect(wrapper.text()).toContain('queued');
    unmountTracked(wrapper);
  });

  it('keeps the backup verification report download action in the job detail', async () => {
    const backup = { id: 'backup-1', kind: 'backup_verify', status: 'succeeded', worker: 'local', result: { value: { report: { worker: 'local', profile: 'default', run_id: 'run-1', checked: 7 } } } };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [backup] });
      if (path === '/jobs/backup-1') return Promise.resolve(backup);
      if (path.endsWith('/events?after_sequence=0')) return Promise.resolve({ items: [] });
      if (path.endsWith('/log-snapshot')) return Promise.resolve({ log: { lines: [] } });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });
    const createObjectUrl = vi.fn(() => 'blob:verification-report');
    const revokeObjectUrl = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL: createObjectUrl, revokeObjectURL: revokeObjectUrl });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    const wrapper = mountMonitor({ title: 'Aktivitas', pollingMode: 'activity' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job backup-1"]').trigger('click');
    await flushPromises();
    vi.useFakeTimers();
    await wrapper.get('button[aria-label="Unduh JSON verifikasi"]').trigger('click');
    await vi.advanceTimersByTimeAsync(1000);
    expect(createObjectUrl).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:verification-report');
    unmountTracked(wrapper);
  });

  it('shows an event fetch error instead of claiming the job has no events', async () => {
    const job = { id: 'event-job', kind: 'export', status: 'failed', worker: 'local' };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/event-job') return Promise.resolve(job);
      if (path.endsWith('/events?after_sequence=0')) return Promise.reject(new Error('event endpoint unavailable'));
      if (path.endsWith('/log-snapshot')) return Promise.resolve({ log: { lines: [] } });
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({});
    });

    const wrapper = mountMonitor({ title: 'Aktivitas', pollingMode: 'activity' });
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job event-job"]').trigger('click');
    await flushPromises();
    await wrapper.get('.detail-tabs button:nth-of-type(2)').trigger('click');
    expect(wrapper.get('[role="alert"]').text()).toContain('event endpoint unavailable');
    expect(wrapper.text()).not.toContain('Belum ada event.');
    unmountTracked(wrapper);
  });

  it('keeps the newest detail request in control when requests finish out of order', async () => {
    const first = { id: 'job-first', kind: 'export', status: 'succeeded', worker: 'worker-first' };
    const second = { id: 'job-second', kind: 'export', status: 'succeeded', worker: 'worker-second' };
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstResponse = new Promise((resolve) => { resolveFirst = resolve; });
    const secondResponse = new Promise((resolve) => { resolveSecond = resolve; });
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [first, second] });
      if (path === '/jobs/job-first') return firstResponse;
      if (path === '/jobs/job-second') return secondResponse;
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mountPage();
    await flushPromises();
    await wrapper.get('button[aria-label="Detail job job-first"]').trigger('click');
    await wrapper.get('button[aria-label="Detail job job-second"]').trigger('click');
    resolveFirst(first);
    await flushPromises();
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('Detail job job-second');
    expect(wrapper.text()).toContain('Memuat detail…');
    resolveSecond(second);
    await flushPromises();
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('Detail job job-second');
    expect(wrapper.get('.job-detail-modal .detail-summary').text()).toContain('worker-second');
    expect(wrapper.get('.job-detail-modal .detail-summary').text()).not.toContain('worker-first');
    unmountTracked(wrapper);
  });

  it('traps focus in detail and confirmation dialogs and closes them with Escape', async () => {
    const job = { id: 'job-active', kind: 'export', status: 'running', title: 'Active job' };
    mocks.api.mockImplementation((path: string) => {
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [job] });
      if (path === '/jobs/job-active') return Promise.resolve(job);
      if (path.startsWith('/jobs/metrics?')) return Promise.resolve({ workers: [] });
      return Promise.resolve({ items: [] });
    });

    const wrapper = mount(ActivityPage, { attachTo: document.body });
    mountedWrappers.push(wrapper);
    await flushPromises();
    const opener = wrapper.get('button[aria-label="Detail job job-active"]').element as HTMLButtonElement;
    opener.focus();
    await wrapper.get('button[aria-label="Detail job job-active"]').trigger('click');
    await flushPromises();
    const detailDialog = wrapper.get('[role="dialog"]');
    const closeDetail = wrapper.get('button[aria-label="Tutup detail"]').element as HTMLButtonElement;
    expect(document.activeElement).toBe(closeDetail);
    expect(wrapper.get('.detail-tabs button[aria-pressed="true"]').text()).toBe('Ringkasan');
    await wrapper.get('.detail-tabs button:nth-of-type(2)').trigger('click');
    expect(wrapper.get('.detail-tabs button[aria-pressed="true"]').text()).toBe('Event');
    await detailDialog.trigger('keydown', { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(wrapper.get('.job-detail-modal .modal-actions button:last-child').element);
    await wrapper.get('.job-detail-modal .modal-actions button:last-child').trigger('keydown', { key: 'Tab' });
    expect(document.activeElement).toBe(closeDetail);
    const stopButton = wrapper.get('.job-detail-modal .modal-actions button:first-child').element as HTMLButtonElement;
    stopButton.focus();
    await wrapper.get('.job-detail-modal .modal-actions button:first-child').trigger('click');
    await flushPromises();
    const confirmDialog = wrapper.get('.confirm-card');
    expect(confirmDialog.attributes('aria-modal')).toBe('true');
    expect(wrapper.get('.job-detail-modal').attributes('aria-modal')).toBeUndefined();
    expect(wrapper.get('.job-detail-modal').attributes('aria-hidden')).toBe('true');
    expect(wrapper.get('.job-detail-modal').attributes('inert')).toBeDefined();
    const cancelConfirm = wrapper.get('.confirm-card button:first-child').element as HTMLButtonElement;
    expect(document.activeElement).toBe(cancelConfirm);
    await confirmDialog.trigger('keydown', { key: 'Escape' });
    await flushPromises();
    expect(wrapper.find('.confirm-card').exists()).toBe(false);
    expect(wrapper.get('.job-detail-modal').attributes('aria-hidden')).toBeUndefined();
    expect(wrapper.get('.job-detail-modal').attributes('inert')).toBeUndefined();
    expect(document.activeElement).toBe(stopButton);
    await wrapper.get('.job-detail-modal').trigger('keydown', { key: 'Escape' });
    await flushPromises();
    expect(wrapper.find('.job-detail-modal').exists()).toBe(false);
    expect(document.activeElement).toBe(opener);
    unmountTracked(wrapper);
  });
});
