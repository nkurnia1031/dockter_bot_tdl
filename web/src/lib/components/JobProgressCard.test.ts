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

  it('shows the relative Workspace path during direct chat delivery', () => {
    render(JobProgressCard, {
      job: {
        kind: 'chat_send', status: 'running', profile: 'default', worker: 'local',
        created_at: new Date().toISOString(),
        progress: {
          phase: 'uploading', message: 'Mengirim chapter.txt',
          overall: { current: 0, total: 1, percent: 0, unit: 'files' },
          item: { name: 'chapter.txt', path: 'Books/Volume 1/chapter.txt', index: 1, total: 1, profile: 'default', percent: 12 },
          transfer: {}, counters: { succeeded: 0, failed: 0, ambiguous: 0 },
        },
      },
      onReport: vi.fn(), onLog: vi.fn(), onTerminate: vi.fn(),
    });

    expect(screen.getByText('Books/Volume 1/chapter.txt')).toBeTruthy();
  });

  it('shows rclone transfer bytes and per-file plus batch progress', () => {
    render(JobProgressCard, {
      job: {
        kind:'storage_upload', status:'running', profile:'default', worker:'remote-1',
        created_at:new Date().toISOString(),
        progress:{
          phase:'uploading', message:'Mengupload archive.zip ke rclone',
          overall:{current:1,total:3,percent:42,files_current:1,files_total:3,bytes_current:1048576,bytes_total:4194304},
          item:{name:'archive.zip',index:2,total:3,percent:50,size_bytes:2097152},
          transfer:{bytes_current:1048576,bytes_total:2097152,speed_bps:524288,eta_seconds:2},
          counters:{succeeded:1,failed:0,skipped:0},
        },
      },
      onReport:vi.fn(), onLog:vi.fn(), onTerminate:vi.fn(),
    });

    expect(screen.getByText('File 2/3')).toBeTruthy();
    expect(screen.getByText('Batch 1/3 file')).toBeTruthy();
    expect(screen.getByText('1.0 MB / 4.0 MB batch')).toBeTruthy();
    expect(screen.getAllByText('archive.zip').length).toBeGreaterThan(0);
    expect(screen.getByText('1.0 MB / 2.0 MB')).toBeTruthy();
    expect(screen.getByText('512.0 KB/dtk')).toBeTruthy();
    expect(screen.getByText('2 dtk')).toBeTruthy();
  });

  it('shows every active Storage upload with its profile and file', () => {
    render(JobProgressCard, {
      job: {
        kind: 'storage_upload',
        status: 'running',
        profile: 'default',
        worker: 'local',
        created_at: new Date().toISOString(),
        progress: {
          phase: 'uploading',
          message: 'Mengupload archive.zip',
          active_items: [
            { profile: 'default', name: 'camera.zip', phase: 'uploading', percent: 35, size_bytes: 1000, bytes_current: 350 },
            { profile: 'archive', name: 'archive.zip', phase: 'uploading', percent: 72, size_bytes: 2000, bytes_current: 1440 }
          ]
        }
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn()
    });

    expect(screen.getByText('Profil default')).toBeTruthy();
    expect(screen.getByText('camera.zip')).toBeTruthy();
    expect(screen.getByText('35%')).toBeTruthy();
    expect(screen.getByText('Profil archive')).toBeTruthy();
    expect(screen.getByText('archive.zip')).toBeTruthy();
    expect(screen.getByText('72%')).toBeTruthy();
  });

  it('shows each Storage download result and its public link status', async () => {
    render(JobProgressCard, {
      job: {
        id: 'storage-download-job',
        kind: 'storage_download',
        status: 'failed',
        profile: 'default',
        worker: 'remote-1',
        created_at: new Date().toISOString(),
        payload: { provider: 'telegram' },
        result: { value: {
          succeeded: 1,
          failed: 1,
          cancelled_items: 0,
          items: [
            {
              name: 'report.pdf',
              relative_path: 'Reports/2026/report.pdf',
              download_status: 'succeeded',
              link_status: 'succeeded',
              public_url: 'https://files.example.test/public/download/' + 'a'.repeat(43),
            },
            {
              name: 'existing.zip',
              relative_path: 'Reports/existing.zip',
              download_status: 'failed',
              link_status: 'not_created',
              error: 'File tujuan sudah ada; file tidak ditimpa.',
            },
          ],
        } },
        progress: { phase: 'partial_failure', overall: { current: 2, total: 2, percent: 100 } },
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn()
    });

    await fireEvent.click(screen.getByRole('button', { name: /toggle detail progress/i }));
    expect(screen.getByRole('region', { name: 'Hasil download per file' })).toBeTruthy();
    expect(screen.getByText('Reports/2026/report.pdf')).toBeTruthy();
    expect(screen.getByText('Download berhasil')).toBeTruthy();
    expect(screen.getByText('Link siap')).toBeTruthy();
    expect(screen.getByRole('link', { name: /files\.example\.test\/public\/download/ })).toBeTruthy();
    expect(screen.getByText('existing.zip')).toBeTruthy();
    expect(screen.getByText('Download gagal')).toBeTruthy();
    expect(screen.getByText('Link tidak dibuat')).toBeTruthy();
    expect(screen.getByText('File tujuan sudah ada; file tidak ditimpa.')).toBeTruthy();
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

  it('distinguishes an accepted stop request from a stopped process', () => {
    render(JobProgressCard, {
      job: {
        id: 'cancel-pending',
        kind: 'storage_upload',
        status: 'running',
        profile: 'default',
        worker: 'local',
        created_at: new Date().toISOString(),
        progress: {
          phase: 'uploading',
          cancel_request: { status: 'accepted' },
        },
      },
      onReport: vi.fn(),
      onLog: vi.fn(),
      onTerminate: vi.fn(),
    });

    expect(screen.getByRole('status').textContent).toContain(
      'menunggu konfirmasi worker',
    );
  });
});
