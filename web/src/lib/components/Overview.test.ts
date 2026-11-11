import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

const mockApi = vi.hoisted(() => vi.fn());
vi.mock('$lib/api', () => ({ api: mockApi }));

import Overview from './Overview.svelte';

describe('Overview operations dashboard', () => {
  beforeEach(() => {
    mockApi.mockReset();
    mockApi.mockImplementation(async (path: string) => {
      if (path === '/dashboard/summary') return { jobs: { active: 2, failed: 1 }, profile: 'default', worker: 'local' };
      if (path.includes('status=queued')) return { items: [{
        id: 'job-active', kind: 'storage_upload', worker: 'local', status: 'running', progress: { active_file: 'paket/episode-7.zip' }
      }] };
      if (path.includes('status=failed')) return { items: [{
        id: 'job-failed', kind: 'download', worker: 'remote-1', status: 'failed', error: { code: 'TDL_DOWNLOAD_FAILED' }, finished_at: '2026-11-10T14:00:00Z'
      }] };
      if (path === '/jobs/metrics?scope=current') return { workers: [{ worker: 'local', status: 'busy', active_jobs: 1, enabled: true }] };
      if (path === '/profiles/local') return { runtime_readiness: {
        workers: [{ name: 'local', status: 'success' }],
        cells: [{ worker: 'local', profile: 'default', runtime: 'tts_helper', status: 'ready' }]
      } };
      throw new Error(`Unexpected API request: ${path}`);
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('shows active work, worker readiness and recent failures together', async () => {
    render(Overview);

    expect(await screen.findByText('episode-7.zip')).toBeTruthy();
    expect(screen.getByText('Worker & layanan')).toBeTruthy();
    expect(screen.getByText('TDL_DOWNLOAD_FAILED')).toBeTruthy();
    expect(screen.getByText('local · default · TTS runtime siap')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Lihat semua aktivitas/ })).toBeTruthy();
    expect(mockApi).toHaveBeenCalledTimes(5);
  });

  it('refreshes only on operator action and does not poll the overview', async () => {
    vi.useFakeTimers();
    render(Overview);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(5));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(mockApi).toHaveBeenCalledTimes(5);

    await fireEvent.click(screen.getByRole('button', { name: 'Muat ulang ringkasan' }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(10));
  });
});
