import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import JobTable from './JobTable.svelte';

describe('JobTable', () => {
  const dialogMethodDescriptors = Object.fromEntries(['showModal', 'close'].map((name) => [name, Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)]));
  const visibilityStateDescriptor = Object.getOwnPropertyDescriptor(document, 'visibilityState');
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    if (visibilityStateDescriptor) Object.defineProperty(document, 'visibilityState', visibilityStateDescriptor);
    else delete (document as any).visibilityState;
    for (const [name, descriptor] of Object.entries(dialogMethodDescriptors)) {
      if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
      else delete (HTMLDialogElement.prototype as any)[name];
    }
  });

  async function flushPromises() {
    for (let index = 0; index < 6; index += 1) await Promise.resolve();
  }

  it('shows an accessible empty state and global terminate action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    render(JobTable, { title: 'Daftar aktivitas' });
    expect(await screen.findByText('Belum ada job.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Terminate semua aktif' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh daftar job' })).toBeTruthy();
  });

  it('restores a completed backup verification report from history with a download action', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const report = { worker: 'remote-2', profile: 'default', run_id: 'run-123', status: 'verified' };
    const job = {
      id: 'backup-verify-1', kind: 'backup_verify', status: 'succeeded', profile: 'default', worker: 'remote-2',
      result: { value: { report } }, updated_at: '2026-10-11T08:00:00Z'
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.endsWith('/jobs/backup-verify-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(JobTable, { kind: 'backup_verify', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Unduh JSON verifikasi')).toBeTruthy();
  });

  it('uses Download and Export labels in operator worker logs without changing the raw API record', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const job = {
      id: 'export-log-1', kind: 'export', status: 'failed', profile: 'default', worker: 'local',
      created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:01Z'
    };
    const rawCommand = 'tdl --storage type=bolt,path=/data/user1/.tdl/data -n default chat export';
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/jobs/export-log-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ log: { lines: [rawCommand], order: 'oldest_first' } }), { status: 200 });
      if (url.endsWith('/events?after_sequence=0')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'export', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Log' }));

    const log = await screen.findByText(/tdl --storage/);
    expect(log.textContent).toContain('Export');
    expect(log.textContent).toContain('[lane Export]');
    expect(log.textContent).toContain('/data/user1/.tdl/data');
    expect(rawCommand).toContain('/data/user1/.tdl');
  });

  it('filters Quick Mode globally and retries a failed attempt', async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [{ id: 'failed-1', kind: 'export', status: 'failed', profile: 'archive', worker: 'remote-1', updated_at: '2026-09-17T00:00:00Z', error: { message: 'gagal upload' } }] }), { status: 200 });
      if (url.endsWith('/retry')) return new Response(JSON.stringify({ id: 'retry-1', status: 'queued' }), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, retryable: true });
    const retryButton = await screen.findByRole('button', { name: 'Retry' });
    await fireEvent.click(retryButton);

    expect(calls.some((call) => call.url.includes('scope=global') && call.url.includes('kind=export') && call.url.includes('quick_mode=true'))).toBe(true);
    expect(calls.some((call) => call.url.endsWith('/retry') && call.method === 'POST')).toBe(true);
  });

  it('shows TTS titles and a legacy fallback directly in history rows', async () => {
    const jobs = [
      {
        id: 'tts-with-title', kind: 'tts', status: 'succeeded', worker: 'local',
        payload: { title: 'Narasi: Ringkasan Perjalanan' }, updated_at: '2026-10-15T00:00:00Z'
      },
      {
        id: 'tts-without-title', kind: 'tts', status: 'failed', worker: 'remote-1',
        payload: {}, updated_at: '2026-10-14T00:00:00Z'
      }
    ];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: jobs }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'tts', view: 'history' });

    expect(await screen.findByRole('heading', { name: 'Narasi: Ringkasan Perjalanan' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Judul tidak tersedia' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Report' })).toHaveLength(2);
  });

  it('shows per-file Storage outcomes and retries only after safe-file confirmation', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const calls: { url: string; method?: string }[] = [];
    const job = {
      id: 'storage-1', kind: 'storage_upload', status: 'failed', profile: 'default', worker: 'local',
      created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:01Z', retryable: true,
      result: { value: { outcome: 'partial_failure', items: [
        { path: 'safe.txt', name: 'safe.txt', status: 'failed', attempt: 1, retryable: true, error: 'File gagal sebelum dikirim.' },
        { path: 'ambiguous.txt', name: 'ambiguous.txt', status: 'needs_reconciliation', upload_status: 'needs_reconciliation', cleanup_status: 'retained_ambiguous', attempt: 2, profile: 'archive', retryable: false, error: 'Hasil belum pasti.' },
        { path: 'changed.txt', name: 'changed.txt', status: 'succeeded', upload_status: 'succeeded', cleanup_status: 'skipped_source_changed', attempt: 1, retryable: false },
        { path: 'exists.txt', name: 'exists.txt', status: 'skipped', upload_status: 'skipped', cleanup_status: 'retained_existing_target', reason_code: 'STORAGE_TARGET_EXISTS', reason: 'File sudah ada di tujuan; file dilewati tanpa menimpa.', attempt: 1, retryable: false },
      ] } }
    };
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        return new Response(JSON.stringify({ items: query.get('kind') === 'storage_upload' ? [job] : [] }), { status: 200 });
      }
      if (url.endsWith('/jobs/storage-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.endsWith('/events?after_sequence=0') || url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/retry')) return new Response(JSON.stringify({ id: 'storage-2', status: 'queued' }), { status: 200 });
      if (url.endsWith('/reconcile')) return new Response(JSON.stringify({ id: 'reconcile-1', status: 'queued' }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'storage_upload', retryable: true, view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Retry file aman' }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('File dengan hasil ambigu tidak ikut dikirim'));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-1/retry') && call.method === 'POST')).toBe(true);
    await fireEvent.click(await screen.findByRole('button', { name: 'Rekonsiliasi' }));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-1/reconcile') && call.method === 'POST')).toBe(true);
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Hasil per file')).toBeTruthy();
    expect(screen.getByText('safe.txt')).toBeTruthy();
    expect(screen.getByText('ambiguous.txt')).toBeTruthy();
    expect(screen.getByText('Perlu verifikasi')).toBeTruthy();
    expect(screen.getByText('Upload: Perlu verifikasi')).toBeTruthy();
    expect(screen.getByText('Sumber: Dilewati · sumber berubah')).toBeTruthy();
    expect(screen.getByText('exists.txt')).toBeTruthy();
    expect(screen.getByText('Dilewati · target sudah ada')).toBeTruthy();
    expect(screen.getByText('File sudah ada di tujuan; file dilewati tanpa menimpa.')).toBeTruthy();
    expect(screen.getByText('Sumber: Sumber disimpan · target sudah ada')).toBeTruthy();
  });

  it('verifies one Storage file, keeps incomplete results ambiguous, and retries only a confirmed missing file', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const source: Record<string, any> = {
      id: 'storage-item-actions', kind: 'storage_upload', status: 'failed', profile: 'default', worker: 'local',
      created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:01Z',
      result: { value: { items: [
        { path: 'confirmed-missing.zip', name: 'confirmed-missing.zip', status: 'needs_reconciliation', retryable: false },
        { path: 'still-ambiguous.zip', name: 'still-ambiguous.zip', status: 'needs_reconciliation', retryable: false },
      ] } }
    };
    const calls: { url: string; method?: string }[] = [];
    let activeReconciliation: Record<string, any> | null = null;
    let verifiedIndex: number | null = null;
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        const items = query.get('kind') === 'storage_upload'
          ? [source]
          : query.get('kind') === 'storage_reconcile' && activeReconciliation
            ? [activeReconciliation]
            : [];
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      if (url.endsWith('/jobs/storage-item-actions')) return new Response(JSON.stringify(source), { status: 200 });
      if (url.endsWith('/events?after_sequence=0') || url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.includes('/jobs/storage-item-actions/reconcile?item_index=')) {
        verifiedIndex = Number(new URL(url, 'http://localhost').searchParams.get('item_index'));
        activeReconciliation = {
          id: `storage-reconcile-${verifiedIndex}`, kind: 'storage_reconcile', status: 'running',
          payload: { source_job_id: source.id, item_index: verifiedIndex },
        };
        return new Response(JSON.stringify(activeReconciliation), { status: 200 });
      }
      if (url.includes('/jobs/storage-item-actions/retry?item_index=')) {
        source.result.value.items[0] = {
          ...source.result.value.items[0],
          status: 'retrying',
          retryable: false,
          retry_job_id: 'storage-item-retry',
        };
        return new Response(JSON.stringify({ id: 'storage-item-retry', status: 'queued' }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'storage_upload', retryable: true, view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    const ambiguousRow = screen.getByText('still-ambiguous.zip').closest('article')!;
    await fireEvent.click(within(ambiguousRow).getByRole('button', { name: 'Verifikasi file' }));

    expect(calls.some((call) => call.url.endsWith('/jobs/storage-item-actions/reconcile?item_index=1') && call.method === 'POST')).toBe(true);
    expect(verifiedIndex).toBe(1);
    expect(await within(ambiguousRow).findByRole('button', { name: 'Memverifikasi…' })).toBeTruthy();
    expect(within(ambiguousRow).getByRole('button', { name: 'Memverifikasi…' })).toHaveProperty('disabled', true);

    activeReconciliation = null;
    window.dispatchEvent(new CustomEvent('tme3:job-finished'));
    await waitFor(() => expect(within(ambiguousRow).getByRole('button', { name: 'Verifikasi file' })).toBeTruthy());
    expect(within(ambiguousRow).queryByRole('button', { name: 'Retry file' })).toBeNull();

    const missingRow = screen.getByText('confirmed-missing.zip').closest('article')!;
    await fireEvent.click(within(missingRow).getByRole('button', { name: 'Verifikasi file' }));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-item-actions/reconcile?item_index=0') && call.method === 'POST')).toBe(true);
    activeReconciliation = null;
    source.result.value.items[0] = {
      ...source.result.value.items[0],
      status: 'failed',
      retryable: true,
      error: 'Ekspor lengkap tidak menemukan file.',
      reconciliation: { job_id: 'storage-reconcile-0', status: 'failed', match_count: 0 },
    };
    window.dispatchEvent(new CustomEvent('tme3:job-finished'));

    const retryButton = await within(missingRow).findByRole('button', { name: 'Retry file' });
    await fireEvent.click(retryButton);
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('file ini saja'));
    expect(calls.some((call) => call.url.endsWith('/jobs/storage-item-actions/retry?item_index=0') && call.method === 'POST')).toBe(true);
    const retryingButton = await within(missingRow).findByRole('button', { name: 'Retry berjalan' });
    expect(retryingButton).toHaveProperty('disabled', true);
    expect(within(ambiguousRow).queryByRole('button', { name: 'Retry file' })).toBeNull();
  });

  it('does not expose per-file reconcile or retry actions for Rclone uploads', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const source = {
      id: 'rclone-item-actions', kind: 'storage_upload', status: 'failed',
      profile: 'default', worker: 'local', payload: { provider: 'rclone' },
      created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:01Z',
      result: { value: { items: [
        { path: 'archive/file.bin', name: 'file.bin', status: 'needs_reconciliation', retryable: false },
        { path: 'archive/other.bin', name: 'other.bin', status: 'failed', retryable: true,
          reconciliation: { job_id: 'old-reconcile', status: 'failed', match_count: 0 } },
      ] } },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) {
        return new Response(JSON.stringify({ items: url.includes('kind=storage_upload') ? [source] : [] }), { status: 200 });
      }
      if (url.endsWith('/jobs/rclone-item-actions')) return new Response(JSON.stringify(source), { status: 200 });
      if (url.endsWith('/events?after_sequence=0') || url.endsWith('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'storage_upload', retryable: true, view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));

    expect(screen.queryByRole('button', { name: 'Verifikasi file' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry file' })).toBeNull();
  });

  it('shows completed Storage download results per file in the report', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const job = {
      id: 'storage-download-1', kind: 'storage_download', status: 'failed', profile: 'default', worker: 'remote-1',
      created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:01Z',
      result: { value: {
        outcome: 'partial_failure', succeeded: 1, failed: 1, cancelled_items: 0, public_links_failed: 0,
        items: [
          { name: 'report.pdf', relative_path: 'Reports/2026/report.pdf', download_status: 'succeeded', link_status: 'succeeded', public_url: 'https://files.example.test/public/download/' + 'a'.repeat(43) },
          { name: 'existing.zip', relative_path: 'Reports/existing.zip', download_status: 'failed', link_status: 'not_created', error: 'File tujuan sudah ada; file tidak ditimpa.' },
        ],
      } },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/jobs/storage-download-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'storage_download', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));

    expect(await screen.findByRole('region', { name: 'Hasil download per file' })).toBeTruthy();
    expect(screen.getByText('Reports/2026/report.pdf')).toBeTruthy();
    expect(screen.getByText('Download berhasil')).toBeTruthy();
    expect(screen.getByText('Link siap')).toBeTruthy();
    expect(screen.getByRole('link', { name: /files\.example\.test\/public\/download/ })).toBeTruthy();
    expect(screen.getByText('File tujuan sudah ada; file tidak ditimpa.')).toBeTruthy();
    expect(screen.getByText('Download gagal')).toBeTruthy();
    expect(screen.queryByText(/^items$/)).toBeNull();
  });

  it('shows media files skipped by the savings preflight in the job report', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const job = {
      id: 'media-preflight-1', kind: 'utility', status: 'succeeded', profile: 'default', worker: 'local',
      payload: { utility: 'video_convert' },
      result: { value: {
        outcome: 'succeeded',
        summary: { files_total: 1, files_succeeded: 0, files_failed: 0, files_skipped: 1 },
        details: [{
          file: '/workspace/videos/clip.mkv', status: 'skipped',
          estimated_savings_percent: 35, minimum_estimated_savings_percent: 40,
          reason: 'Perkiraan penghematan 35.0% tidak melewati ambang 40%.',
        }],
      } },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/jobs/media-preflight-1')) return new Response(JSON.stringify(job), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'utility', view: 'history' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));

    expect(await screen.findByRole('region', { name: 'Hasil konversi media per file' })).toBeTruthy();
    expect(screen.getByText('clip.mkv')).toBeTruthy();
    expect(screen.getByText('Perkiraan hemat 35.0% · ambang 40%')).toBeTruthy();
    expect(screen.getByText('Perkiraan penghematan 35.0% tidak melewati ambang 40%.')).toBeTruthy();
    expect(screen.getByText('0 berhasil · 0 gagal · 1 dilewati')).toBeTruthy();
  });

  it('keeps the media category summary visible after a job enters Activity history', async () => {
    const job = {
      id: 'media-history-1', kind: 'utility', status: 'succeeded', profile: 'default', worker: 'local',
      payload: { utility: 'media_pipeline' },
      result: { value: { summary: {
        media: {
          scan_complete: true,
          video: { total: 3, running: 0, succeeded: 2, failed: 0, skipped: 1 },
          image: { total: 2, running: 0, succeeded: 2, failed: 0, skipped: 0 },
          skipped: { estimated_savings_below_threshold: 1, recode_output_exists: 0 },
        },
      } } },
      progress: { phase: 'completed', counters: { succeeded: 4, failed: 0, skipped: 1 } },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(JobTable, { kind: 'utility', view: 'history' });

    expect(await screen.findByText('Video: 3 total · 0 berjalan · 2 berhasil · 0 gagal')).toBeTruthy();
    expect(screen.getByText('Gambar: 2 total · 0 berjalan · 2 berhasil · 0 gagal')).toBeTruthy();
    expect(screen.getByText('Estimasi hemat ≤40%: 1')).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Daftar hasil konversi media' })).toBeNull();
  });

  it('identifies Utility history by operation, selected folder, and result while keeping the full report', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const extract = {
      id: 'utility-extract-history', kind: 'utility', status: 'partial_failure', worker: 'remote-1',
      payload: { utility: 'extract', folders: ['/workspace/Series/Season 2'] },
      result: { value: { summary: { archives_succeeded: 4, archives_partial: 1, archives_failed: 1 } } },
      updated_at: '2026-11-20T09:00:00Z',
    };
    const flatten = {
      id: 'utility-flatten-history', kind: 'utility', status: 'succeeded', worker: 'local',
      payload: {
        utility: 'flatten', flatten_action: 'preview',
        folders: ['/workspace/Alpha', '/workspace/Beta', '/workspace/Gamma'],
      },
      result: { value: {
        summary: { moves: 7, replaced: 1, suffixed: 2, deleted: 3, skipped: 4 },
        details: [{ folder: '/workspace/Alpha', flatten_preview: { passes: [] } }],
      } },
      updated_at: '2026-11-20T09:01:00Z',
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [extract, flatten] }), { status: 200 });
      if (url.endsWith('/jobs/utility-flatten-history')) return new Response(JSON.stringify(flatten), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'utility', view: 'history' });

    expect(await screen.findByText('Extract')).toBeTruthy();
    expect(screen.getByText('/workspace/Series/Season 2')).toBeTruthy();
    expect(screen.getByText('4 arsip berhasil · 1 gagal · 1 parsial')).toBeTruthy();
    expect(screen.getByText('Flatten')).toBeTruthy();
    expect(screen.getByText('/workspace/Alpha')).toBeTruthy();
    expect(screen.getByText('+2 folder')).toBeTruthy();
    expect(screen.getByText('7 operasi · 1 diganti · 2 suffix · 3 folder kosong dihapus · 4 dilewati')).toBeTruthy();

    const flattenRow = screen.getByText('Flatten').closest('article');
    expect(flattenRow).toBeTruthy();
    await fireEvent.click(within(flattenRow!).getByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Preview Flatten tersimpan')).toBeTruthy();
    expect(screen.getByText('/workspace/Alpha', { selector: 'h4' })).toBeTruthy();
    expect(screen.getByText('/workspace/Beta')).toBeTruthy();
    expect(screen.getByText('/workspace/Gamma')).toBeTruthy();
  });

  it('lists and reopens safe Storage reconciliation results without exposing caption or path', async () => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
      configurable: true,
      value(this: HTMLDialogElement) { this.setAttribute('open', ''); },
    });
    Object.defineProperty(HTMLDialogElement.prototype, 'close', {
      configurable: true,
      value(this: HTMLDialogElement) { this.removeAttribute('open'); },
    });
    const reconciliation = {
      id: 'reconcile-1', kind: 'storage_reconcile', status: 'succeeded', profile: 'default', worker: 'local',
      payload: { source_job_id: 'storage-1' }, created_at: '2026-10-15T00:00:00Z', updated_at: '2026-10-15T00:00:01Z',
      result: { value: { items: [
        { index: 0, name: 'archive.zip', profile: 'archive', status: 'succeeded', match_count: 1, retryable: false, error: 'Caption ditemukan.' },
        { index: 1, name: 'missing.zip', profile: 'default', status: 'failed', match_count: 0, retryable: true, error: 'Aman untuk Retry.' },
      ] } }
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs?')) {
        const query = new URL(url, 'http://localhost').searchParams;
        return new Response(JSON.stringify({ items: query.get('kind') === 'storage_reconcile' ? [reconciliation] : [] }), { status: 200 });
      }
      if (url.endsWith('/jobs/reconcile-1')) return new Response(JSON.stringify(reconciliation), { status: 200 });
      if (url.includes('/events') || url.includes('/log-snapshot')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    const { container } = render(JobTable, { kind: 'storage_upload', view: 'history' });
    expect(await screen.findByText('Storage reconcile')).toBeTruthy();
    await fireEvent.click(await screen.findByRole('button', { name: 'Report' }));
    expect(await screen.findByText('Hasil rekonsiliasi caption')).toBeTruthy();
    expect(screen.getByText('archive.zip')).toBeTruthy();
    expect(screen.getByText('Caption cocok: 1')).toBeTruthy();
    expect(container.textContent).not.toContain('/workspace/');
  });

  it('uses a live active monitor query separate from terminal history', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running', profile: 'default', worker: 'local', payload: { quick_mode: true }, progress: { phase: 'downloading' } }] }), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, view: 'active', title: 'Monitor aktif' });

    expect(await screen.findByText('Sedang berjalan')).toBeTruthy();
    expect(urls.some((url) => decodeURIComponent(url).includes('status=queued,dispatched,running,paused'))).toBe(true);
    expect(screen.queryByText('History terbaru')).toBeNull();
  });

  it('keeps active job order stable when polling returns a different update order', async () => {
    const older = {
      id: 'job-older', kind: 'utility', status: 'running', created_at: '2026-10-05T09:00:00Z',
      updated_at: '2026-10-05T09:05:00Z', progress: { phase: 'compressing', message: 'Job lama' }
    };
    const newer = {
      id: 'job-newer', kind: 'utility', status: 'running', created_at: '2026-10-05T09:01:00Z',
      updated_at: '2026-10-05T09:04:00Z', progress: { phase: 'compressing', message: 'Job baru' }
    };
    let jobRequest = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequest += 1;
        const items = jobRequest === 1 ? [newer, older] : [older, newer];
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    const { container } = render(JobTable, { scope: 'global', view: 'active' });
    const order = () => Array.from(container.querySelectorAll('.idm-row b.truncate')).map((item) => item.textContent);

    await screen.findByText('Job lama');
    expect(order()).toEqual(['Job lama', 'Job baru']);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh monitor' }));
    await waitFor(() => expect(jobRequest).toBe(2));
    expect(order()).toEqual(['Job lama', 'Job baru']);
  });

  it('shows queue latency and worker activity from monitor metrics', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) {
        return new Response(JSON.stringify({
          active_jobs: 1,
          queued_jobs: 2,
          average_queue_wait_seconds: 8,
          event_latency: { count: 12, average_ms: 34.6 },
          workers: [{ worker: 'remote-1', status: 'busy', active_jobs: 1, queued_jobs: 2, last_seen_age_seconds: 4 }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running', profile: 'default', worker: 'remote-1', payload: {}, progress: { phase: 'downloading' } }] }), { status: 200 });
    }));

    render(JobTable, { scope: 'global', view: 'active' });

    expect(await screen.findByText('8 dtk')).toBeTruthy();
    expect(screen.getByText('35 ms · 12 event')).toBeTruthy();
    expect(screen.getByText('remote-1 · sibuk · 1 aktif · 2 antre')).toBeTruthy();
  });

  it('pauses and resumes Quick Mode jobs from the active monitor', async () => {
    const calls: { url: string; method?: string }[] = [];
    const job = {
      id: 'quick-live-1',
      kind: 'export',
      status: 'running',
      profile: 'default',
      worker: 'local',
      payload: { quick_mode: true },
      progress: { phase: 'downloading', message: 'file.mp4' },
      created_at: new Date().toISOString()
    };
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [job] }), { status: 200 });
      if (url.endsWith('/pause')) {
        job.status = 'paused';
        return new Response(JSON.stringify({ ...job }), { status: 200 });
      }
      if (url.endsWith('/resume')) {
        job.status = 'queued';
        return new Response(JSON.stringify({ ...job }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(JobTable, { kind: 'export', scope: 'global', quickMode: true, view: 'active' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Jeda job' }));
    expect(await screen.findByRole('button', { name: 'Lanjutkan job' })).toBeTruthy();
    expect(calls.some((call) => call.url.endsWith('/pause') && call.method === 'POST')).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: 'Lanjutkan job' }));
    expect(calls.some((call) => call.url.endsWith('/resume') && call.method === 'POST')).toBe(true);
  });

  it('keeps a feature job list manual while idle', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await fireEvent.click(screen.getByRole('button', { name: 'Refresh daftar job' }));
    await flushPromises();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('refreshes feature job progress only while a relevant job is active', async () => {
    vi.useFakeTimers();
    let jobStatus = 'running';
    let jobRequests = 0;
    const metricsRequests: string[] = [];
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) {
        metricsRequests.push(url);
        return new Response(JSON.stringify({ active_jobs: 1 }), { status: 200 });
      }
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        const job = { id: 'active-1', kind: 'utility', status: jobStatus, progress: { phase: 'compressing' } };
        return new Response(JSON.stringify({ items: jobStatus === 'running' ? [job] : [{ ...job, status: 'succeeded' }] }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    expect(await screen.findByText('Progress otomatis · job aktif')).toBeTruthy();
    expect(jobRequests).toBe(1);

    jobStatus = 'succeeded';
    await vi.advanceTimersByTimeAsync(2500);
    await flushPromises();
    expect(jobRequests).toBe(2);
    expect(metricsRequests).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(jobRequests).toBe(2);
  });

  it('stops feature job polling when the page is left', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'utility', status: 'running' }] }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { unmount } = render(JobTable, { kind: 'utility', title: 'Riwayat utility' });
    await flushPromises();
    const initialRequests = fetchMock.mock.calls.length;
    unmount();

    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(initialRequests);
  });

  it('uses a faster Activity cadence for active jobs and slows down while idle', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    let jobRequests = 0;
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        const items = jobRequests === 1
          ? [{ id: 'active-1', kind: 'export', status: 'running' }]
          : [];
        return new Response(JSON.stringify({ items }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { title: 'Daftar aktivitas', pollingMode: 'activity' });
    await flushPromises();
    expect(screen.getByText('Live · 2,5 dtk aktif / 10 dtk idle')).toBeTruthy();

    await vi.advanceTimersByTimeAsync(2499);
    expect(jobRequests).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(jobRequests).toBe(2);

    await vi.advanceTimersByTimeAsync(9999);
    expect(jobRequests).toBe(2);
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(jobRequests).toBe(3);
  });

  it('pauses the Activity monitor while its tab is hidden and refreshes when visible', async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    let jobRequests = 0;
    const fetchMock = vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/jobs/metrics?')) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes('/jobs?')) {
        jobRequests += 1;
        return new Response(JSON.stringify({ items: [{ id: 'active-1', kind: 'export', status: 'running' }] }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(JobTable, { title: 'Daftar aktivitas', pollingMode: 'activity' });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(jobRequests).toBe(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    await flushPromises();
    expect(jobRequests).toBe(2);
  });
});
