import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import UtilityPage from './UtilityPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), remove: vi.fn() }));
vi.mock('../lib/api', () => mocks);
vi.mock('../session', () => ({ session: { workers: [{ name: 'local', enabled: true }, { name: 'remote-1', enabled: true }], current: { actor: { profile: 'default', worker_route: 'local' } } } }));
const monitorStub = { props: ['kind', 'title'], template: '<div data-testid="utility-job-monitor">{{ title }} · {{ kind }}</div>' };

function renderPage() { return render(UtilityPage, { global: { stubs: { JobMonitor: monitorStub } } }); }
function setupApi() {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/utility/folders') return { items: [] };
    if (path.startsWith('/utility/tree?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      return { path: params.get('path') || '/workspace', items: [{ name: 'demo', path: '/workspace/demo', kind: 'directory', files: 0, directories: 1, has_children: true }] };
    }
    if (path === '/jobs/preview-1') return { id: 'preview-1', status: 'succeeded', result: { value: { summary: { moves: 1, deleted: 0, skipped: 1, action_count: 1 }, details: [{ folder: '/workspace/demo', flatten_preview: { fingerprint: 'f'.repeat(64), passes: [{ index: 1, actions: [{ type: 'move', folder: 'single', source: 'single/file.txt', destination: 'file.txt', collision: false }, { type: 'skip_multiple', folder: 'many', item_count: 2 }] }], action_count: 1, moves: 1, deleted: 0, skipped: 1 } }] } } };
    if (path === '/jobs/apply-1') return { id: 'apply-1', status: 'succeeded', result: { value: {} } };
    throw new Error(`Unexpected API request ${path}`);
  });
}

describe('UtilityPage', () => {
  beforeEach(() => { vi.clearAllMocks(); setupApi(); });
  afterEach(() => cleanup());

  it('submits selected Workspace folders to the selected worker without profile readiness calls', async () => {
    mocks.post.mockResolvedValue({ id: 'utility-1', kind: 'utility', status: 'queued' });
    renderPage();
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker target' }), { target: { value: 'remote-1' } });
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih demo' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Jalankan utility' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/utility/jobs', { utility: 'pindah', folders: ['/workspace/demo'], worker: 'remote-1' }));
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes('/profiles/local'))).toBe(false);
    expect(screen.getByTestId('utility-job-monitor').textContent).toContain('utility');
  });

  it('previews Flatten completely and submits a separate confirmed apply job', async () => {
    mocks.post.mockImplementation(async (_path: string, body: Record<string, any>) => ({ id: body.flatten_action === 'preview' ? 'preview-1' : 'apply-1', kind: 'utility', status: 'dispatched' }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih demo' }));
    await fireEvent.change(screen.getByRole('combobox', { name: 'Jenis operasi' }), { target: { value: 'flatten' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Preview Flatten' }));
    expect(await screen.findByRole('region', { name: 'Preview Flatten' })).toBeTruthy();
    expect(screen.getByText(/single\/file\.txt/)).toBeTruthy();
    expect(screen.getByText(/many/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Terapkan Flatten' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1]).toEqual({ utility: 'flatten', folders: ['/workspace/demo'], worker: 'local', flatten_action: 'apply', flatten_fingerprints: { '/workspace/demo': 'f'.repeat(64) } });
    expect(confirm).toHaveBeenCalledOnce();
    expect(await screen.findByText('Flatten selesai.')).toBeTruthy();
  });
});
