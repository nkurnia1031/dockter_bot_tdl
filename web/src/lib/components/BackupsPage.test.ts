import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/backups/status') return { enabled: true, items: [{ run_id: 'full-run-id-for-test', node_name: 'remote-2', status: 'complete' }] };
      if (path === '/workers') return { items: [{ name: 'local', enabled: true }, { name: 'remote-2', enabled: true }] };
      if (path === '/profiles') return { items: [{ name: 'default' }, { name: 'irang' }] };
      if (path.startsWith('/jobs?')) return { items: [] };
      if (path.startsWith('/jobs/metrics?')) return {};
      throw new Error(`Unexpected GET ${path}`);
    });
    postMock.mockResolvedValue(diagnostic);
  });

  it('requests the selected worker/profile and shows the matching JSON and per-session results', async () => {
    render(BackupsPage);

    const worker = await screen.findByLabelText('Worker');
    await waitFor(() => expect((worker as HTMLSelectElement).options.length).toBe(3));
    await fireEvent.change(worker, { target: { value: 'remote-2' } });
    await fireEvent.change(screen.getByLabelText('Profil'), { target: { value: 'default' } });
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
});
