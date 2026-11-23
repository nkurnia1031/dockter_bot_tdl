import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

const mockApi = vi.hoisted(() => vi.fn());
vi.mock('$lib/api', () => ({ api: mockApi }));

import Overview from './Overview.svelte';
import { setGatewayMode } from '$lib/gateway-mode.svelte';

describe('Overview operations dashboard', () => {
  beforeEach(() => {
    setGatewayMode('full');
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
    setGatewayMode('full');
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

  it('shows cached remote health in Lite without probing local profile readiness', async () => {
    setGatewayMode('lite');
    mockApi.mockImplementation(async (path: string) => {
      if (path === '/dashboard/summary') return { jobs: { active: 1, failed: 0 }, profile: 'default', worker: 'local' };
      if (path.includes('status=queued')) return { items: [{ id: 'remote-active', kind: 'download', worker: 'remote-1', status: 'running' }] };
      if (path.includes('status=failed')) return { items: [] };
      if (path === '/jobs/metrics?scope=current') return { workers: [{ worker: 'remote-1', status: 'busy', active_jobs: 1, enabled: true }] };
      if (path === '/workers') return { items: [
        { name: 'remote-1', enabled: true, health_status: 'ready' },
        { name: 'local', enabled: true, health_status: 'unknown' },
      ] };
      throw new Error(`Unexpected API request in Lite: ${path}`);
    });

    render(Overview);

    expect(await screen.findByText('Remote per job')).toBeTruthy();
    expect(await screen.findByText('Siap')).toBeTruthy();
    expect(screen.queryByText(/TTS runtime/)).toBeNull();
    expect(mockApi).toHaveBeenCalledWith('/workers');
    expect(mockApi.mock.calls.some(([path]) => path === '/profiles/local')).toBe(false);
    expect(screen.queryByText('local · 0 job aktif')).toBeNull();
  });

  it('refreshes Lite every ten seconds only while visible and a job is active', async () => {
    vi.useFakeTimers();
    setGatewayMode('lite');
    let active = true;
    mockApi.mockImplementation(async (path: string) => {
      if (path === '/dashboard/summary') return { jobs: { active: active ? 1 : 0, failed: 0 }, profile: 'default', worker: 'local' };
      if (path.includes('status=queued')) return { items: active ? [{ id: 'remote-active', kind: 'download', worker: 'remote-1', status: 'running' }] : [] };
      if (path.includes('status=failed')) return { items: [] };
      if (path === '/jobs/metrics?scope=current') return { workers: [{ worker: 'remote-1', status: active ? 'busy' : 'idle', active_jobs: active ? 1 : 0, enabled: true }] };
      if (path === '/workers') return { items: [{ name: 'remote-1', enabled: true, health_status: 'ready' }] };
      throw new Error(`Unexpected API request in Lite: ${path}`);
    });
    render(Overview);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(5));

    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(10));
    expect(screen.getByText('download · remote-1')).toBeTruthy();

    active = false;
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(15));
    await vi.advanceTimersByTimeAsync(20_000);
    expect(mockApi).toHaveBeenCalledTimes(15);
  });

  it('pauses Lite refresh while the document is hidden and resumes when visible', async () => {
    vi.useFakeTimers();
    setGatewayMode('lite');
    let hidden = true;
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
    mockApi.mockImplementation(async (path: string) => {
      if (path === '/dashboard/summary') return { jobs: { active: 1, failed: 0 }, profile: 'default', worker: 'local' };
      if (path.includes('status=queued')) return { items: [{ id: 'remote-active', kind: 'download', worker: 'remote-1', status: 'running' }] };
      if (path.includes('status=failed')) return { items: [] };
      if (path === '/jobs/metrics?scope=current') return { workers: [{ worker: 'remote-1', status: 'busy', active_jobs: 1, enabled: true }] };
      if (path === '/workers') return { items: [{ name: 'remote-1', enabled: true, health_status: 'ready' }] };
      throw new Error(`Unexpected API request in Lite: ${path}`);
    });
    render(Overview);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(5));
    await vi.advanceTimersByTimeAsync(20_000);
    expect(mockApi).toHaveBeenCalledTimes(5);

    hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.waitFor(() => expect(mockApi).toHaveBeenCalledTimes(10));

    hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(20_000);
    expect(mockApi).toHaveBeenCalledTimes(10);
  });
});
