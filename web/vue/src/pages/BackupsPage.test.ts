import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BackupsPage from './BackupsPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), put: vi.fn(), calls: [] as Array<{ path: string; init?: RequestInit }> }));
vi.mock('../lib/api', () => ({ api: mocks.api, post: mocks.post, put: mocks.put }));
const backupJobStub = { props: ['kind', 'title', 'view'], template: '<div data-testid="backup-job-monitor">{{ title }} · {{ kind }} · {{ view }}</div>' };

const diagnostic = {
  worker: 'remote-2', profile: 'default', checked_at: '2026-10-11T06:46:22+00:00', ready: false, identity_match: false,
  reason_codes: ['PROFILE_USER1_SESSION_TDL_INVALID'],
  sessions: [
    { name: 'root', ready: true, code: 'OK', identity_matches_metadata: true },
    { name: 'user1', ready: false, code: 'PROFILE_USER1_SESSION_TDL_INVALID', identity_matches_metadata: false }
  ]
};
const report = {
  worker: 'remote-2', profile: 'default', run_id: 'full-run-id-for-test', status: 'verified', part_count: 2,
  reason_codes: [], canary_evidence_status: 'ready_for_operator_review', checksum_validation: 'unavailable',
  sessions: [{ name: 'root', included: true, content_test: 'passed', tdl_test: 'passed', identity_match: true }, { name: 'user1', included: true, content_test: 'passed', tdl_test: 'passed', identity_match: true }],
  download: { matched_parts: [{ name: 'backup.7z.001', message_id: 733 }, { name: 'backup.7z.002', message_id: 734 }] },
  tdl_diagnostics: { ready: true, identity_match: true }
};

function renderPage() { return render(BackupsPage, { global: { stubs: { JobMonitor: backupJobStub } } }); }
function setupApi() {
  mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
    mocks.calls.push({ path, init });
    if (path === '/backups/status') return { enabled: true, schedule: '03:00', timezone: 'Asia/Jakarta', retention: 7, volume_size: '45m', channel: '@backup', items: [{ run_id: 'full-run-id-for-test', node_name: 'remote-2', status: 'complete', started_at: '2026-10-11T00:00:00Z' }] };
    if (path === '/workers') return { items: [{ name: 'local', enabled: true }, { name: 'remote-2', enabled: true }] };
    if (path === '/profiles/local') return { profiles: [{ name: 'default', workers: ['local', 'remote-2'], exclusive_worker: '' }, { name: 'remote-only', workers: ['remote-2'], exclusive_worker: 'remote-2' }] };
    if (path === '/backups/verify' && init?.method === 'POST') return { id: 'backup-verify-job', kind: 'backup_verify', worker: 'remote-2', profile: 'default', status: 'queued' };
    if (path === '/jobs/backup-verify-job') return { id: 'backup-verify-job', kind: 'backup_verify', worker: 'remote-2', profile: 'default', status: 'succeeded', result: { value: { report } } };
    throw new Error(`Unexpected API request ${path}`);
  });
  mocks.post.mockResolvedValue(diagnostic);
  mocks.put.mockResolvedValue({});
}

describe('BackupsPage', () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.calls.length = 0; setupApi(); });
  afterEach(() => cleanup());

  it('creates a backup and saves its scheduling settings without exposing stored passwords', async () => {
    mocks.post.mockImplementation(async (path: string) => path === '/backups' ? { id: 'backup-node-job', status: 'queued' } : diagnostic);
    renderPage();
    await screen.findByText(/03:00 · Asia\/Jakarta · retensi 7/);
    await fireEvent.click(screen.getByRole('button', { name: 'Backup sekarang' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/backups'));
    expect(await screen.findByText('Backup gateway mulai dijalankan.')).toBeTruthy();
    await fireEvent.click(screen.getByText('Ubah pengaturan backup dan operasi'));
    await fireEvent.update(screen.getByLabelText('Zona waktu'), 'UTC');
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan pengaturan' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/backups/settings', expect.objectContaining({ timezone: 'UTC', retention: 7 })));
    expect(screen.queryByLabelText(/password/i)).toBeNull();
    expect(screen.getAllByText('full-run-id-for-test').length).toBeGreaterThan(0);
  });

  it('renders worker backup history as mobile cards with status, timestamps, and error details', async () => {
    mocks.api.mockImplementation(async (path: string) => {
      if (path === '/backups/status') return { enabled: true, items: [{ run_id: 'mobile-run-id', node_name: 'remote-2', status: 'failed', started_at: '2026-11-10T12:00:00Z', completed_at: '2026-11-10T12:05:00Z', error: 'Backup upload failed' }] };
      if (path === '/workers') return { items: [] };
      if (path === '/profiles/local') return { profiles: [] };
      throw new Error(`Unexpected API request ${path}`);
    });

    renderPage();
    const card = await screen.findByTestId('backup-run-card');
    expect(within(card).getByText('remote-2')).toBeTruthy();
    expect(within(card).getByText('mobile-run-id')).toBeTruthy();
    expect(within(card).getByText('failed')).toBeTruthy();
    expect(within(card).getByText('Backup upload failed')).toBeTruthy();
    expect(within(card).getAllByText(/2026/)).toHaveLength(2);
  });

  it('requests the selected worker and profile for TDL diagnosis and exposes structured results', async () => {
    renderPage();
    const worker = await screen.findByRole('combobox', { name: 'Worker' });
    await screen.findByRole('option', { name: 'remote-2' });
    await fireEvent.update(worker, 'remote-2');
    const profile = screen.getByRole('combobox', { name: 'Profil' });
    await waitFor(() => expect([...((profile as HTMLSelectElement).options)].map((option) => option.value)).toEqual(['', 'default', 'remote-only']));
    await fireEvent.update(profile, 'default');
    await fireEvent.click(screen.getByRole('button', { name: 'Buat JSON diagnosis' }));
    expect(await screen.findByText('remote-2 / default · Ada sesi yang gagal')).toBeTruthy();
    expect(mocks.post).toHaveBeenCalledWith('/backups/tdl-diagnostics', { worker: 'remote-2', profile: 'default' });
    expect(screen.getByText('Download · Siap')).toBeTruthy();
    expect(screen.getByText('Export · Gagal')).toBeTruthy();
    expect(screen.getByText(/"worker": "remote-2"/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Unduh JSON' })).toBeTruthy();
  });

  it('submits the selected backup run and renders verification progress and report details', async () => {
    renderPage();
    const worker = await screen.findByRole('combobox', { name: 'Worker' });
    await screen.findByRole('option', { name: 'remote-2' });
    await fireEvent.update(worker, 'remote-2');
    await fireEvent.update(screen.getByRole('combobox', { name: 'Profil' }), 'default');
    expect((await screen.findByRole('combobox', { name: /Run backup lengkap/ }) as HTMLSelectElement).value).toBe('full-run-id-for-test');
    await fireEvent.click(screen.getByRole('button', { name: 'Unduh dari channel & uji sesi' }));
    const submit = mocks.calls.find(({ path, init }) => path === '/backups/verify' && init?.method === 'POST');
    expect(JSON.parse(String(submit?.init?.body))).toEqual({ worker: 'remote-2', profile: 'default', run_id: 'full-run-id-for-test' });
    expect(new Headers(submit?.init?.headers).get('Idempotency-Key')).toBeTruthy();
    expect(screen.getAllByTestId('backup-job-monitor').some((item) => item.textContent?.includes('Job verifikasi arsip backup · backup_verify · history'))).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: 'Muat status' }));
    expect(await screen.findByText('Sesi TDL lolos; bukti siap ditinjau untuk canary.')).toBeTruthy();
    expect(screen.getByText('Sesi Download · TDL lolos')).toBeTruthy();
    expect(screen.getByText('Sesi Export · TDL lolos')).toBeTruthy();
    await fireEvent.click(screen.getByText('Lihat part dan message ID yang diunduh'));
    expect(screen.getByText('733')).toBeTruthy();
    expect(screen.getAllByTestId('backup-job-monitor').some((item) => item.textContent?.includes('backup_verify · history'))).toBe(true);
  });

  it('distinguishes a succeeded job with a failed archive report', async () => {
    mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
      mocks.calls.push({ path, init });
      if (path === '/backups/status') return { enabled: true, items: [{ run_id: 'full-run-id-for-test', node_name: 'remote-2', status: 'complete' }] };
      if (path === '/workers') return { items: [{ name: 'remote-2', enabled: true }] };
      if (path === '/profiles/local') return { profiles: [{ name: 'default', workers: ['remote-2'], exclusive_worker: '' }] };
      if (path === '/backups/verify') return { id: 'backup-verify-job', worker: 'remote-2', profile: 'default', status: 'queued' };
      if (path === '/jobs/backup-verify-job') return { id: 'backup-verify-job', status: 'succeeded', result: { value: { report: { ...report, status: 'failed', reason_codes: ['BACKUP_ARCHIVE_EXTRACTION_FAILED'], canary_evidence_status: 'backup_failed' } } } };
      throw new Error(`Unexpected API request ${path}`);
    });
    renderPage();
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Worker' }) as HTMLSelectElement).value).toBe('remote-2'));
    await waitFor(() => expect((screen.getByRole('combobox', { name: /Run backup lengkap/ }) as HTMLSelectElement).value).toBe('full-run-id-for-test'));
    await fireEvent.click(await screen.findByRole('button', { name: 'Unduh dari channel & uji sesi' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Muat status' }));
    expect(await screen.findByText(/Job selesai dijalankan, tetapi ekstraksi atau pengujian isi gagal/)).toBeTruthy();
    expect(screen.getAllByText(/BACKUP_ARCHIVE_EXTRACTION_FAILED/).length).toBeGreaterThan(0);
  });
});
