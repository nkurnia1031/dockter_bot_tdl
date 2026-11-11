import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock, postMock, putMock } = vi.hoisted(() => ({
  apiMock: vi.fn(),
  postMock: vi.fn(),
  putMock: vi.fn(),
}));

vi.mock('$lib/api', () => ({
  api: apiMock,
  post: postMock,
  put: putMock,
}));

import BackupsPage from './BackupsPage.svelte';

const diagnostic = {
  worker: 'remote-2',
  profile: 'default',
  checked_at: '2026-10-11T06:46:22+00:00',
  ready: false,
  identity_match: false,
  reason_codes: ['PROFILE_USER1_SESSION_TDL_INVALID'],
  sessions: [
    { name: 'root', ready: true, code: 'OK', identity_matches_metadata: true },
    { name: 'user1', ready: false, code: 'PROFILE_USER1_SESSION_TDL_INVALID', identity_matches_metadata: false },
  ],
};

describe('BackupsPage TDL diagnosis', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('crypto', { randomUUID: () => 'backup-verify-test-key' });
    apiMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/backups/status') return { enabled: true, items: [{ run_id: 'full-run-id-for-test', node_name: 'remote-2', status: 'complete' }] };
      if (path === '/workers') return { items: [{ name: 'local', enabled: true }, { name: 'remote-2', enabled: true }] };
      if (path === '/profiles/local') return { profiles: [
        { name: 'default', workers: ['local', 'remote-2'], exclusive_worker: '' },
        { name: 'remote-only', workers: ['remote-2'], exclusive_worker: 'remote-2' },
      ] };
      if (path === '/backups/verify' && init?.method === 'POST') return { id: 'backup-verify-job', kind: 'backup_verify', worker: 'remote-2', profile: 'default', status: 'queued' };
      if (path === '/jobs/backup-verify-job') return {
        id: 'backup-verify-job', kind: 'backup_verify', worker: 'remote-2', profile: 'default', status: 'succeeded',
        result: { value: { report: {
          worker: 'remote-2', profile: 'default', run_id: 'full-run-id-for-test', status: 'verified',
          part_count: 2, reason_codes: [], canary_evidence_status: 'ready_for_operator_review',
          checksum_validation: 'unavailable', checksums_match: null,
          integrity: 'extraction_verified',
          sessions: [
            { name: 'root', included: true, tdl_test: 'passed', identity_match: true },
            { name: 'user1', included: true, tdl_test: 'passed', identity_match: true },
          ],
          download: {
            source: 'tdl_export_json_with_content',
            matched_parts: [
              { name: 'backup-remote-2.7z.001', message_id: 733 },
              { name: 'backup-remote-2.7z.002', message_id: 734 },
            ],
          },
          tdl_diagnostics: { ready: true, identity_match: true },
        } } },
      };
      if (path.startsWith('/jobs?')) return { items: [] };
      if (path.startsWith('/jobs/metrics?')) return {};
      throw new Error(`Unexpected GET ${path}`);
    });
    postMock.mockResolvedValue(diagnostic);
  });

  it('requests the selected worker/profile and shows the matching JSON and per-session results', async () => {
    render(BackupsPage);

    const worker = (await screen.findAllByLabelText('Worker'))[0];
    await waitFor(() => expect((worker as HTMLSelectElement).options.length).toBe(3));
    await fireEvent.change(worker, { target: { value: 'remote-2' } });
    const profile = (await screen.findAllByLabelText('Profil'))[0] as HTMLSelectElement;
    expect([...profile.options].map((option) => option.value)).toEqual(['', 'default', 'remote-only']);
    expect(profile.innerHTML).not.toContain('irang');
    await fireEvent.change(profile, { target: { value: 'default' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Buat JSON diagnosis' }));

    await screen.findByText('remote-2 / default · Ada sesi yang gagal');
    expect(postMock).toHaveBeenCalledWith('/backups/tdl-diagnostics', {
      worker: 'remote-2',
      profile: 'default',
    });
    expect(screen.getByText('PROFILE_USER1_SESSION_TDL_INVALID · identitas tidak cocok')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Unduh JSON' })).toBeTruthy();
    expect(screen.getByText(/"worker": "remote-2"/)).toBeTruthy();
    expect(screen.getByText('full-run-id-for-test')).toBeTruthy();
  });

  it('submits a selected worker/profile/run and exposes the generated canary JSON', async () => {
    render(BackupsPage);

    const worker = (await screen.findAllByLabelText('Worker'))[0];
    await waitFor(() => expect((worker as HTMLSelectElement).options.length).toBe(3));
    await fireEvent.change(worker, { target: { value: 'remote-2' } });
    await fireEvent.change((await screen.findAllByLabelText('Profil'))[0], { target: { value: 'default' } });
    await waitFor(() => expect((screen.getByLabelText('Run backup lengkap untuk remote-2') as HTMLSelectElement).value).toBe('full-run-id-for-test'));
    await fireEvent.click(screen.getAllByRole('button', { name: 'Unduh dari channel & uji sesi' })[0]);

    await screen.findByText(/Job verifikasi.*remote-2 \/ default/);
    const submit = apiMock.mock.calls.find(([path, init]) => path === '/backups/verify' && init?.method === 'POST');
    expect(submit).toBeTruthy();
    expect(JSON.parse(String(submit?.[1]?.body))).toEqual({
      worker: 'remote-2', profile: 'default', run_id: 'full-run-id-for-test',
    });
    expect(submit?.[1]?.headers).toEqual({ 'Idempotency-Key': expect.any(String) });

    await fireEvent.click(screen.getByRole('button', { name: 'Muat status' }));
    await screen.findByText(/Arsip terverifikasi/);
    expect(screen.getByText('Sesi TDL lolos; bukti siap ditinjau untuk canary.')).toBeTruthy();
    expect(screen.getByText('Sesi Download · TDL lolos')).toBeTruthy();
    expect(screen.getByText('Sesi Export · TDL lolos')).toBeTruthy();
    expect(screen.getByText(/Checksum katalog tidak tersedia/)).toBeTruthy();
    await fireEvent.click(screen.getByText('Lihat part dan message ID yang diunduh'));
    expect(screen.getByText('733')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Salin JSON' })).toBeTruthy();
    await fireEvent.click(screen.getByText('Lihat JSON canary lengkap'));
    expect(screen.getByText(/"canary_evidence_status"/)).toBeTruthy();
  });

  it('shows lane labels in TDL diagnosis while keeping raw diagnostic identifiers', async () => {
    render(BackupsPage);

    const worker = (await screen.findAllByLabelText('Worker'))[0];
    await waitFor(() => expect((worker as HTMLSelectElement).options.length).toBe(3));
    await fireEvent.change(worker, { target: { value: 'remote-2' } });
    await fireEvent.change((await screen.findAllByLabelText('Profil'))[0], { target: { value: 'default' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Buat JSON diagnosis' }));

    expect(await screen.findByText('Download · Siap')).toBeTruthy();
    expect(screen.getByText('Export · Gagal')).toBeTruthy();
    expect(screen.getByText(/"name": "root"/)).toBeTruthy();
    expect(screen.getByText(/"name": "user1"/)).toBeTruthy();
  });

  it('distinguishes a completed verification job from an archive that failed verification', async () => {
    const defaultApi = apiMock.getMockImplementation();
    apiMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/jobs/backup-verify-job') return {
        id: 'backup-verify-job', kind: 'backup_verify', worker: 'remote-2', profile: 'default', status: 'succeeded',
        result: { value: { report: {
          worker: 'remote-2', profile: 'default', run_id: 'full-run-id-for-test', status: 'failed',
          part_count: 2, reason_codes: ['BACKUP_ARCHIVE_EXTRACTION_FAILED'], canary_evidence_status: 'backup_failed',
          tdl_diagnostics: { ready: true, identity_match: true },
        } } },
      };
      return defaultApi?.(path, init);
    });

    render(BackupsPage);
    const worker = (await screen.findAllByLabelText('Worker'))[0];
    await waitFor(() => expect((worker as HTMLSelectElement).options.length).toBe(3));
    await fireEvent.change(worker, { target: { value: 'remote-2' } });
    await fireEvent.change((await screen.findAllByLabelText('Profil'))[0], { target: { value: 'default' } });
    await waitFor(() => expect((screen.getByLabelText('Run backup lengkap untuk remote-2') as HTMLSelectElement).value).toBe('full-run-id-for-test'));
    await fireEvent.click(await screen.findByRole('button', { name: 'Unduh dari channel & uji sesi' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Muat status' }));

    expect(await screen.findByText(/Job selesai dijalankan, tetapi ekstraksi atau pengujian isi gagal/)).toBeTruthy();
    expect(screen.getAllByText(/BACKUP_ARCHIVE_EXTRACTION_FAILED/).length).toBeGreaterThan(0);
  });
});
