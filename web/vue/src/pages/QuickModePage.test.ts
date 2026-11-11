import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import QuickModePage from './QuickModePage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));
vi.mock('../lib/api', () => ({ ...mocks }));
vi.mock('../session', () => ({ session: {
  current: { profiles: ['default'], actor: { profile: 'default', worker_route: 'local' } },
  workers: [{ name: 'local', enabled: true }, { name: 'remote-1', enabled: true }],
  profileCatalog: [{ name: 'default', workers: ['local'], exclusive_worker: 'local' }],
  selectedTargetProfile: 'default'
} }));
const monitorStub = { props: ['kind', 'title', 'scope', 'profile', 'worker', 'quickMode', 'view', 'status', 'retryable'], template: '<div :data-testid="view === \'active\' ? \'quick-active-monitor\' : \'quick-history-monitor\'">{{ kind }} · quick={{ quickMode }} · {{ view }}</div>' };

function readiness(quickStatus = 'ready') {
  return { runtime_readiness: {
    workers: [{ name: 'local', status: 'success' }],
    cells: [
      { worker: 'local', profile: 'default', runtime: 'quick_mode', status: quickStatus, checked_at: '2026-11-10T10:00:00Z', reason_code: quickStatus === 'ready' ? '' : 'PROFILE_CANARY_QUICK_MODE_FAILED' },
      { worker: 'local', profile: null, runtime: 'rclone_storage', status: 'ready', checked_at: '2026-11-10T10:00:00Z', reason_code: '' }
    ]
  } };
}

function setupApi(options: { quickStatus?: string; activeStage?: boolean; stage?: Record<string, unknown> } = {}) {
  const stage = options.stage || {
    stage_job_id: 'stage-one', folder_name: 'batch-one', worker: 'local', profile: 'default', phase: 'thumbnailing',
    json_present: true, expected_media_count: 1, actual_media_count: 1, thumbnail_present: false, archive_parts: 0,
    tdl_export_present: true, tdl_download_present: true, staging_path: '/workspace/quickmode/stage-one'
  };
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/profiles/local') return readiness(options.quickStatus);
    if (path.startsWith('/sources')) return { items: [{ chat_ref: 'example', last_id: 40, label: 'arsip' }] };
    if (path === '/labels') return { items: [{ label: '1cans' }] };
    if (path === '/jobs?limit=200&scope=global&kind=export&quick_mode=true&archived=false') return { items: options.activeStage ? [{
      id: 'active-stage-job', kind: 'export', status: 'running', profile: 'default', worker: 'local', payload: { quick_mode: true, quick_retry: { stage_job_id: 'stage-one' } }
    }] : [] };
    if (path === '/quick-mode/limits') return { items: [{ worker: 'local', max_concurrent: 2, active: 1, queued: 3 }] };
    if (path === '/quick-mode/staging') return { items: [stage], errors: [] };
    if (path.startsWith('/storage/rclone/browser?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      return { path: params.get('path') || '', breadcrumbs: [], items: params.get('path') ? [] : [{ name: 'reports', path: 'reports', is_dir: true, size: 0, updated_at: 'now' }], total: 1, limit: 100, offset: 0 };
    }
    throw new Error(`Unexpected API ${path}`);
  });
  mocks.post.mockResolvedValue({ id: 'quick-job-1', status: 'queued' });
  mocks.put.mockResolvedValue({});
  mocks.remove.mockResolvedValue({ deleted: true });
}

function renderPage() { return render(QuickModePage, { global: { stubs: { JobMonitor: monitorStub } } }); }

describe('QuickModePage', () => {
  beforeEach(() => { vi.clearAllMocks(); setupApi(); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('shows scan status as informational and creates a Quick Mode export without manual verification', async () => {
    setupApi({ quickStatus: 'not_ready' });
    renderPage();
    expect(await screen.findByText('Scan terakhir: Quick Mode belum siap')).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Tambah Quick Mode' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/exports', expect.objectContaining({ chat_ref: 'example', quick_mode: true, profile: 'default', worker: 'local' })));
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes('/context/verify'))).toBe(false);
    expect(screen.getByTestId('quick-active-monitor').textContent).toContain('export · quick=true · active');
  });

  it('submits a selected existing rclone folder only for this job', async () => {
    renderPage();
    await fireEvent.click(await screen.findByRole('button', { name: 'Pilih folder' }));
    await screen.findByRole('button', { name: 'Pilih' });
    await fireEvent.click(screen.getByRole('button', { name: 'Pilih' }));
    expect(await screen.findByText('Folder terpilih: reports')).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Tambah Quick Mode' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/exports', expect.objectContaining({ quick_mode: true, quick_rclone_path: 'reports', quick_rclone_create: false })));
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('rclone_destination');
  });

  it('creates a new child rclone folder under the current browser folder', async () => {
    renderPage();
    await fireEvent.click(await screen.findByRole('button', { name: 'Pilih folder' }));
    await fireEvent.input(await screen.findByPlaceholderText('Nama subfolder baru'), { target: { value: 'November' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Buat tujuan baru' }));
    expect(await screen.findByText('Subfolder baru: November')).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Tambah Quick Mode' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/exports', expect.objectContaining({ quick_rclone_path: 'November', quick_rclone_create: true })));
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('rclone_destination');
  });

  it('shows manual stats and limit refresh controls with per-worker limit updates', async () => {
    renderPage();
    const limit = await screen.findByLabelText('Maksimum aktif') as HTMLInputElement;
    await fireEvent.input(limit, { target: { value: '4' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/quick-mode/limits/local', { max_concurrent: 4 }));
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh statistik Quick Mode' }));
    expect(mocks.api.mock.calls.some(([path]) => path === '/jobs?limit=200&scope=global&kind=export&quick_mode=true&archived=false')).toBe(true);
  });

  it('exposes cancel for an active staging folder and hides destructive actions', async () => {
    setupApi({ activeStage: true });
    renderPage();
    await fireEvent.click(await screen.findByRole('button', { name: 'Refresh scan' }));
    expect(await screen.findByText('Sedang processing (#active-s)')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Hapus staging' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Thumbnail' })).toBeNull();
  });

  it('recovers an inactive staging folder through the explicit recovery endpoint', async () => {
    setupApi({ stage: {
      stage_job_id: 'stage-one', folder_name: 'batch-one', worker: 'local', profile: 'default', phase: 'downloading',
      json_present: true, expected_media_count: 2, actual_media_count: 1, thumbnail_present: false, archive_parts: 0,
      tdl_export_present: true, tdl_download_present: true, staging_path: '/workspace/quickmode/stage-one'
    } });
    renderPage();
    await fireEvent.click(await screen.findByRole('button', { name: 'Refresh scan' }));
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Resume Download' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/quick-mode/recover', expect.objectContaining({
      worker: 'local', stage_job_id: 'stage-one', profile: 'default', resume_phase: 'downloading', single_phase: true, chat_ref: 'example'
    })));
  });

  it('confirms deletion of inactive staging and refreshes the scan', async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);
    renderPage();
    await fireEvent.click(await screen.findByRole('button', { name: 'Refresh scan' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Hapus staging' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('dihapus permanen'));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith('/quick-mode/staging/local/stage-one'));
  });
});
