import { describe, expect, it } from 'vitest';
import { formatDuration, normalizeJobProgress } from './job-progress';

describe('job progress normalization', () => {
  it('normalizes the structured telemetry contract', () => {
    const value = normalizeJobProgress({
      kind: 'storage_upload',
      status: 'running',
      progress: {
        phase: 'uploading',
        message: 'batch.json',
        batch: { name: 'batch.json', index: 1, total: 2, unit: 'json' },
        overall: { current: 2, total: 5, percent: 40 },
        item: { name: 'a.7z', percent: 55 },
        transfer: { speed_bps: 1024, eta_seconds: 12 },
        counters: { succeeded: 2, failed: 0 }
      }
    });
    expect(value.overall.percent).toBe(40);
    expect(value.batch.name).toBe('batch.json');
    expect(value.batch.total).toBe(2);
    expect(value.item.name).toBe('a.7z');
    expect(value.transfer.eta_seconds).toBe(12);
  });

  it('keeps legacy download progress readable', () => {
    const value = normalizeJobProgress({
      status: 'running',
      progress: { current_json_index: 2, total_json: 4, tdl_percent: 75, tdl_file_name: 'video.mp4' }
    });
    expect(value.overall.percent).toBe(50);
    expect(value.batch.index).toBe(2);
    expect(value.batch.total).toBe(4);
    expect(value.item.percent).toBe(75);
    expect(formatDuration(403)).toBe('6m 43d');
  });

  it('reads terminal media summaries from the job result', () => {
    const value = normalizeJobProgress({
      kind: 'utility',
      status: 'completed',
      payload: { utility: 'media_pipeline' },
      result: {
        summary: {
          media: {
            scan_complete: true,
            video: { total: 3, running: 0, succeeded: 2, failed: 0, skipped: 1 },
            image: { total: 2, running: 0, succeeded: 1, failed: 1, skipped: 0 },
            skipped: { estimated_savings_below_threshold: 1, recode_output_exists: 0 },
          },
        },
      },
      progress: { phase: 'completed', counters: { succeeded: 3, failed: 1, skipped: 1 } },
    });

    expect(value.media).toEqual({
      scanComplete: true,
      video: { total: 3, running: 0, succeeded: 2, failed: 0, skipped: 1 },
      image: { total: 2, running: 0, succeeded: 1, failed: 1, skipped: 0 },
      skipped: { estimatedSavingsBelowThreshold: 1, recodeOutputExists: 0 },
    });
  });
});
