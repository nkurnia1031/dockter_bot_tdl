import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock, postMock } = vi.hoisted(() => ({
  apiMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock('$lib/api', () => ({
  api: apiMock,
  patch: vi.fn(),
  post: postMock,
  put: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('$lib/session.svelte', () => ({
  session: {
    current: { actor: { profile: 'default' } },
    chooseWorker: vi.fn(),
  },
}));

import WorkersPage from './WorkersPage.svelte';

const workerSettings = {
  worker: 'remote-tts',
  worker_api_token_configured: true,
  job_stall_timeout_seconds: 600,
  tdl_export_stall_timeout_seconds: 300,
  tdl_download_stall_timeout_seconds: 300,
  storage_profile: 'default',
  storage_profile_available: true,
  available_storage_profiles: ['default'],
  tts_helper_urls: ['http://tts-1', 'http://tts-2', 'http://tts-3'],
  tts_part_retries: 4,
  tts_retry_base_seconds: 2,
  tts_newnym_after_retries: 3,
};

function setupApi() {
  apiMock.mockImplementation(async (path: string) => {
    if (path === '/workers') return { items: [{ name: 'remote-tts', url: 'http://worker', enabled: true }] };
    if (path.endsWith('/settings')) return workerSettings;
    if (path.endsWith('/tts/health')) {
      return {
        worker: 'remote-tts',
        ready: false,
        helpers_ready: false,
        profile_session_ready: true,
        helpers: [
          { slot: 1, status: 'ready', bootstrap_percent: 100, checked_at: 'now' },
          { slot: 2, status: 'bootstrapping', bootstrap_percent: 63, checked_at: 'now' },
          { slot: 3, status: 'helper_unreachable', bootstrap_percent: null, checked_at: 'now' },
        ],
      };
    }
    throw new Error(`Unexpected GET ${path}`);
  });
  postMock.mockResolvedValue({ worker: 'remote-tts', slot: 2, accepted: true, status: 'restarting' });
}

describe('WorkersPage TTS health controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
  });

  it('checks helper status only on manual action and does not poll', async () => {
    render(WorkersPage);
    await screen.findByText('remote-tts');
    await fireEvent.click(screen.getByRole('button', { name: /Runtime/ }));
    await screen.findByText('Diagnosis kesiapan');
    expect(apiMock).not.toHaveBeenCalledWith('/workers/remote-tts/tts/health');

    await fireEvent.click(screen.getByRole('button', { name: 'Periksa ulang TTS remote-tts' }));
    expect(await screen.findByText('Bootstrap 63%')).toBeTruthy();
    expect(screen.getByText('Helper tidak terjangkau')).toBeTruthy();
    expect(screen.getByText(/Profil yang terverifikasi mengirim: belum ada/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pulihkan helper 3 remote-tts' })).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Pulihkan helper 2 remote-tts' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      '/workers/remote-tts/tts/helpers/2/recover', {},
    ));
    expect(apiMock.mock.calls.filter(([path]) => path.endsWith('/tts/health'))).toHaveLength(1);
    expect(await screen.findByText(/Periksa ulang status secara manual/)).toBeTruthy();
  });
});
