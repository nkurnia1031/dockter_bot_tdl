import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import JobProgressCard from './JobProgressCard.svelte';

describe('JobProgressCard', () => {
  afterEach(cleanup);

  it('shows current file, progress, speed, ETA and counters', () => {
    render(JobProgressCard, {
      job: {
        kind: 'download',
        status: 'running',
        profile: 'default',
        worker: 'local',
        created_at: new Date().toISOString(),
        progress: {
          phase: 'uploading',
          message: 'batch.json',
          batch: { name: 'batch.json', index: 1, total: 2, unit: 'json' },
          overall: { current: 3, total: 10, percent: 32, unit: 'files' },
          item: { name: 'archive.7z.001', index: 4, total: 10, size_bytes: 10485760, percent: 64 },
          transfer: { speed_bps: 1048576, eta_seconds: 12 },
          counters: { succeeded: 3, failed: 1, skipped: 0 },
          elapsed_seconds: 45
        }
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn()
    });
    expect(screen.getByText('batch.json')).toBeTruthy();
    expect(screen.getByText('JSON 1/2')).toBeTruthy();
    expect(screen.getByText('File 4/10')).toBeTruthy();
    expect(screen.getByText('1.0 MB/dtk')).toBeTruthy();
    expect(screen.getByText('12 dtk')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
  });

  it('toggles detail drawer when clicking Detail button', async () => {
    render(JobProgressCard, {
      job: {
        kind: 'download',
        status: 'running',
        profile: 'default',
        worker: 'local',
        created_at: new Date().toISOString(),
        progress: {
          phase: 'uploading',
          message: 'batch.json',
          overall: { current: 3, total: 10, percent: 32, unit: 'files' },
          counters: { succeeded: 3, failed: 1, skipped: 0 }
        }
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn()
    });
    expect(screen.queryByText('Detail Progress Job')).toBeNull();
    const toggleBtn = screen.getByRole('button', { name: /toggle detail progress/i });
    await fireEvent.click(toggleBtn);
    expect(screen.getByText('Detail Progress Job')).toBeTruthy();
    await fireEvent.click(toggleBtn);
    expect(screen.queryByText('Detail Progress Job')).toBeNull();
  });

  it('shows queue wait, phase age, event latency and accumulated phase time', async () => {
    render(JobProgressCard, {
      job: {
        id: 'quick-observe-1',
        kind: 'export',
        status: 'running',
        profile: 'default',
        worker: 'local',
        created_at: new Date().toISOString(),
        payload: { quick_mode: true },
        progress: {
          phase: 'compressing',
          timing: { queue_wait_seconds: 4 },
          observability: {
            phase: 'compressing',
            phase_started_at: new Date(Date.now() - 6000).toISOString(),
            phase_elapsed_seconds: 6,
            event_latency: { count: 3, average_ms: 28.4 },
            phase_durations_seconds: { downloading: 12 }
          }
        }
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn()
    });

    expect(screen.getByText('Antre 4 dtk')).toBeTruthy();
    expect(screen.getByText('Latensi event 28 ms')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /toggle detail progress/i }));
    expect(screen.getByText('Durasi per fase')).toBeTruthy();
    expect(screen.getByText('Mendownload media · 12 dtk')).toBeTruthy();
  });
});
