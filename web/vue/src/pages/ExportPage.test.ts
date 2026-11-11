import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ExportPage from './ExportPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), remove: vi.fn() }));
vi.mock('../lib/api', () => ({ ...mocks, put: vi.fn() }));
vi.mock('../session', () => ({
  session: {
    current: { profiles: ['default', 'archive'], actor: { profile: 'default', worker_route: 'local' } },
    workers: [{ name: 'local', enabled: true }, { name: 'remote-1', enabled: true }],
    profileCatalog: [], selectedTargetProfile: 'default'
  }
}));

const monitorStub = { props: ['kind', 'title', 'retryable'], template: '<div data-testid="export-monitor">{{ kind }} · retry={{ retryable }}</div>' };

function setupApi() {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/profiles/local') return { runtime_readiness: {
      checked_at: '2026-11-10T10:00:00Z', workers: [{ name: 'local', status: 'success', checked_at: '2026-11-10T10:00:00Z' }],
      cells: [
        { worker: 'local', profile: 'default', runtime: 'export', status: 'not_ready', checked_at: '2026-11-10T10:00:00Z', reason_code: 'PROFILE_CANARY_EXPORT_FAILED' },
        { worker: 'local', profile: 'default', runtime: 'quick_mode', status: 'ready', checked_at: '2026-11-10T10:00:00Z', reason_code: '' }
      ]
    } };
    if (path.startsWith('/sources')) return { items: [{ chat_ref: 'example', last_id: 40, label: 'arsip' }] };
    if (path === '/labels') return { items: [{ label: '1cans' }] };
    if (path.startsWith('/jobs/')) return { id: path.split('/').at(-1), status: 'queued' };
    throw new Error(`Unexpected API ${path}`);
  });
  mocks.post.mockResolvedValue({ id: 'export-1', status: 'queued', progress: { message: 'Menunggu worker' } });
  mocks.remove.mockResolvedValue({});
}

function renderPage() { return render(ExportPage, { global: { stubs: { JobMonitor: monitorStub } } }); }

describe('ExportPage', () => {
  beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); setupApi(); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); sessionStorage.clear(); });

  it('loads label DTO text and shows readiness as informational without verifying before submit', async () => {
    renderPage();
    expect(await screen.findByRole('button', { name: '1cans' })).toBeTruthy();
    expect(await screen.findByText('Scan terakhir: Export belum siap')).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'https://t.me/IYear' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai export' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/exports', expect.objectContaining({
      chat_ref: 'iyear', profile: 'default', worker: 'local', use_url_message_id: false
    })));
    expect(mocks.api).not.toHaveBeenCalledWith('/context/verify', expect.anything());
    expect(screen.getByTestId('export-monitor').textContent).toContain('export · retry=true');
    expect(await screen.findByText(/Export masuk antrean/)).toBeTruthy();
  });

  it('selects a saved source and sends a manual start ID only when overwrite is enabled', async () => {
    const posted: Record<string, unknown>[] = [];
    mocks.post.mockImplementation(async (_path: string, body: Record<string, unknown>) => {
      posted.push(body);
      return { id: `export-${posted.length}`, status: 'succeeded' };
    });
    renderPage();
    await screen.findByRole('option', { name: /example/ });
    await fireEvent.change(screen.getByLabelText('Pilih source tersimpan'), { target: { value: 'example' } });
    expect((screen.getByLabelText('Start message ID') as HTMLInputElement).value).toBe('41');
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai export' }));
    expect(posted[0]).toMatchObject({ chat_ref: 'example', use_url_message_id: false });
    expect(posted[0]).not.toHaveProperty('start_id');
    await fireEvent.click(screen.getByRole('switch', { name: /Overwrite Start ID/ }));
    await fireEvent.input(screen.getByLabelText('Start message ID'), { target: { value: '12' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai export' }));
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted[1]).toMatchObject({ chat_ref: 'example', start_id: 12, use_url_message_id: true });
  });

  it('sends Quick Mode with the stored worker/profile target and keeps the short submit cooldown', async () => {
    vi.useFakeTimers();
    renderPage();
    await vi.waitFor(() => expect(mocks.api).toHaveBeenCalledWith('/labels'));
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('switch', { name: /Quick Mode Export/ }));
    expect(screen.getByText('Scan terakhir: Quick Mode siap')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai export' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/exports', expect.objectContaining({ quick_mode: true })));
    expect(screen.getByRole('button', { name: 'Tunggu sebentar…' })).toBeTruthy();
  });

  it('rejects invalid chat references and malformed persisted notice IDs safely', async () => {
    sessionStorage.setItem('tme3-export-notices', '{bad json');
    renderPage();
    await screen.findByText('Export baru');
    await fireEvent.input(screen.getByLabelText('Referensi chat'), { target: { value: 'not a chat ref' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai export' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
