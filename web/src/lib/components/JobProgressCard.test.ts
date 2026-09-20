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
});
