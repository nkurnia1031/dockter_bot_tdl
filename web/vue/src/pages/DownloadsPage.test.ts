import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DownloadsPage from './DownloadsPage.vue';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  post: vi.fn(),
  remove: vi.fn()
}));

vi.mock('../lib/api', () => ({ api: mocks.api, post: mocks.post, remove: mocks.remove }));
vi.mock('../session', () => ({
  session: {
    workers: [{ name: 'local', enabled: true }, { name: 'remote-1', enabled: true }],
    profileCatalog: [
      { name: 'default', workers: ['local'], exclusive_worker: 'local' },
      { name: 'archive', workers: ['remote-1'], exclusive_worker: 'remote-1' }
    ]
  }
}));

const pendingArtifact = {
  id: 'artifact-pending', filename: 'backup.json', profile: 'default', worker: 'local',
  status: 'pending', available: true, label: 'Daily', chat_ref: '@storagechat',
  message_count: 12, json_bytes: 1024, created_at: '2026-11-10T10:00:00Z'
};
const missingArtifact = {
  id: 'artifact-missing', filename: 'missing.json', profile: 'archive', worker: 'remote-1',
  status: 'deleted', available: false, missing_at: '2026-11-10T10:00:00Z'
};

function setupApi(items = [pendingArtifact]) {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/profiles/local') return { runtime_readiness: { checked_at: '2026-11-10T10:00:00Z', workers: [{ name: 'local', status: 'success' }], cells: [{ worker: 'local', profile: 'default', runtime: 'download', status: 'not_ready', reason_code: 'TDL_ACCESS_NOT_VERIFIED' }] } };
    if (path.startsWith('/downloads/artifacts?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      const filtered = items.filter((item) => {
        if ((params.get('archived') === 'true') !== Boolean((item as typeof pendingArtifact & { archived_at?: string }).archived_at)) return false;
        if (params.get('status') && item.status !== params.get('status')) return false;
        if (params.get('available') === 'false' && item.available !== false) return false;
        if (params.get('profile') && item.profile !== params.get('profile')) return false;
        if (params.get('worker') && item.worker !== params.get('worker')) return false;
        if (params.get('label') && !(item.label || '').toLowerCase().includes(params.get('label')!.toLowerCase())) return false;
        if (params.get('chat_ref') && (item.chat_ref || '').toLowerCase() !== params.get('chat_ref')!.replace(/^@/, '').toLowerCase()) return false;
        return true;
      });
      const offset = Number(params.get('offset') || 0);
      const limit = Number(params.get('limit') || 200);
      return { items: filtered.slice(offset, offset + limit), total: filtered.length };
    }
    if (path.startsWith('/jobs/metrics')) return { workers: [] };
    if (path.startsWith('/jobs/')) return { id: path.split('/').at(-1), status: 'succeeded' };
    if (path.startsWith('/jobs?')) return { items: [] };
    throw new Error(`Unexpected GET ${path}`);
  });
  mocks.post.mockResolvedValue({ groups: [{ profile: 'default', worker: 'local', job_id: 'job-1' }] });
  mocks.remove.mockResolvedValue({ purged: true });
}

describe('DownloadsPage', () => {
  beforeEach(() => { vi.clearAllMocks(); setupApi(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it('loads the global catalog without reconciling and stays idle until manual refresh', async () => {
    vi.useFakeTimers();
    render(DownloadsPage);
    expect(await screen.findByText('backup.json')).toBeTruthy();
    const initialReads = mocks.api.mock.calls.filter(([path]) => String(path).startsWith('/downloads/artifacts?')).length;
    expect(initialReads).toBe(2);
    expect(mocks.post).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(30_000);
    expect(mocks.api.mock.calls.filter(([path]) => String(path).startsWith('/downloads/artifacts?'))).toHaveLength(initialReads);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh katalog unduhan' }));
    await waitFor(() => expect(mocks.api.mock.calls.filter(([path]) => String(path).startsWith('/downloads/artifacts?'))).toHaveLength(initialReads + 2));
    expect(mocks.api.mock.calls.filter(([path]) => path === '/profiles/local')).toHaveLength(2);
    expect(mocks.post).not.toHaveBeenCalledWith(expect.stringContaining('/downloads/artifacts/reconcile'), expect.anything());
  });

  it('passes origin filters to catalog and manual reconcile only', async () => {
    render(DownloadsPage);
    await screen.findByText('backup.json');
    await fireEvent.change(screen.getByLabelText('Profile'), { target: { value: 'archive' } });
    await fireEvent.change(screen.getByLabelText('Worker / VPS'), { target: { value: 'remote-1' } });
    await fireEvent.input(screen.getByPlaceholderText('Cari label'), { target: { value: 'quarterly' } });
    await fireEvent.change(screen.getByPlaceholderText('@username, link, ID, atau telepon'), { target: { value: '@teamstore' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Reconcile global' }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/downloads/artifacts/reconcile?scope=global&profile=archive&worker=remote-1'));
    const listCalls = mocks.api.mock.calls.map(([path]) => String(path)).filter((path) => path.startsWith('/downloads/artifacts?'));
    expect(listCalls.some((path) => {
      const params = new URLSearchParams(path.split('?')[1]);
      return params.get('scope') === 'global' && params.get('profile') === 'archive' && params.get('worker') === 'remote-1'
        && params.get('label') === 'quarterly' && params.get('chat_ref') === '@teamstore';
    })).toBe(true);
  });

  it('queries pending separately so older pending artifacts are not hidden by the global limit', async () => {
    const items = Array.from({ length: 200 }, (_, index) => ({
      id: `done-${index}`, filename: `done-${index}.json`, profile: 'default', worker: 'local',
      status: 'downloaded', available: true, created_at: `2026-11-10T${String(23 - Math.floor(index / 60)).padStart(2, '0')}:00:00Z`
    })).concat([pendingArtifact] as never[]);
    setupApi(items as typeof pendingArtifact[]);
    render(DownloadsPage);
    expect(await screen.findByText('backup.json')).toBeTruthy();
    expect(mocks.api.mock.calls.some(([path]) => new URLSearchParams(String(path).split('?')[1]).get('status') === 'pending')).toBe(true);
  });

  it('submits downloads despite an unready informational scan result', async () => {
    render(DownloadsPage);
    expect(await screen.findByText('Scan terakhir: belum siap')).toBeTruthy();
    const start = screen.getByRole('button', { name: 'Mulai' });
    expect((start as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(start);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/downloads/batch', { artifact_ids: ['artifact-pending'], priority: 'normal' }));
  });

  it('keeps missing artifacts in history without offering retry or starting a scan', async () => {
    setupApi([missingArtifact]);
    render(DownloadsPage);
    await screen.findByText('Tidak ada artifact pada tab ini.');
    await fireEvent.click(screen.getByRole('tab', { name: 'History' }));
    expect(await screen.findByText('missing.json')).toBeTruthy();
    expect(screen.getByText('File tidak tersedia')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mulai' })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('restores archived metadata and purges only after confirmation', async () => {
    const archived = { ...pendingArtifact, id: 'archived-1', filename: 'old.json', status: 'archived', archived_at: '2026-11-10T11:00:00Z' };
    setupApi([archived]);
    render(DownloadsPage);
    await fireEvent.click(await screen.findByRole('tab', { name: 'Archived' }));
    expect(await screen.findByText('old.json')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Purge' }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(mocks.remove).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Lanjutkan' }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith('/downloads/artifacts/archived-1'));
  });
});
