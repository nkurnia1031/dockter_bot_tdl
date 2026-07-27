export type JobLike = Record<string, any>;

export type NormalizedProgress = {
  phase: string;
  message: string;
  batch: Record<string, any>;
  overall: Record<string, any>;
  item: Record<string, any>;
  transfer: Record<string, any>;
  counters: { succeeded: number; failed: number; skipped: number };
  indeterminate: boolean;
  elapsedSeconds?: number;
};

const number = (value: unknown): number | undefined => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

export function clampPercent(value: unknown): number | undefined {
  const parsed = number(value);
  return parsed === undefined ? undefined : Math.min(100, Math.max(0, parsed));
}

export function normalizeJobProgress(job: JobLike): NormalizedProgress {
  const raw = job.progress || {};
  if (raw.phase && (raw.overall || raw.item || raw.transfer || raw.counters)) {
    return {
      phase: String(raw.phase),
      message: String(raw.message || `${job.kind} sedang diproses`),
      batch: { ...(raw.batch || {}) },
      overall: { ...(raw.overall || {}), percent: clampPercent(raw.overall?.percent) },
      item: { ...(raw.item || {}), percent: clampPercent(raw.item?.percent) },
      transfer: raw.transfer || {},
      counters: {
        succeeded: number(raw.counters?.succeeded) || 0,
        failed: number(raw.counters?.failed) || 0,
        skipped: number(raw.counters?.skipped) || 0
      },
      indeterminate: Boolean(raw.indeterminate),
      elapsedSeconds: number(raw.elapsed_seconds)
    };
  }

  const total = number(raw.total ?? raw.total_json);
  const current = number(raw.current ?? raw.current_json_index);
  const percent = clampPercent(total && current !== undefined ? current * 100 / total : raw.tdl_percent);
  return {
    phase: String(raw.phase || (job.status === 'running' ? 'processing' : job.status || 'queued')),
    message: String(raw.message || raw.tdl_line || raw.current_json_name || 'Menunggu proses'),
    batch: {
      name: raw.current_json_name,
      index: number(raw.current_json_index),
      total: number(raw.total_json),
      unit: raw.total_json ? 'json' : undefined
    },
    overall: { current, total, percent, unit: raw.total_json ? 'json' : 'files' },
    item: {
      name: raw.tdl_file_name || raw.current_json_name || raw.message,
      index: number(raw.tdl_fraction_current),
      total: number(raw.tdl_fraction_total ?? raw.current_media_total),
      percent: clampPercent(raw.tdl_percent)
    },
    transfer: {
      speed_bps: number(raw.tdl_speed_bps),
      speed_text: raw.tdl_speed,
      eta_seconds: number(raw.tdl_eta_seconds),
      bytes_current: number(raw.tdl_bytes_current)
    },
    counters: {
      succeeded: number(raw.success_count ?? raw.succeeded) || 0,
      failed: number(raw.failed_count ?? raw.failed) || 0,
      skipped: number(raw.skipped) || 0
    },
    indeterminate: percent === undefined,
    elapsedSeconds: number(raw.elapsed_seconds)
  };
}

export function formatDuration(value: unknown): string {
  const seconds = Math.max(0, Math.round(number(value) || 0));
  if (seconds < 60) return `${seconds} dtk`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return [hours ? `${hours}j` : '', minutes ? `${minutes}m` : '', !hours && rest ? `${rest}d` : ''].filter(Boolean).join(' ');
}

export function phaseLabel(value: string): string {
  const labels: Record<string,string> = {
    scanning: 'Memindai file',
    connecting: 'Menghubungkan Telegram',
    exporting: 'Mengekspor chat',
    uploading: 'Mengupload file',
    uploading_parts: 'Mengupload part',
    resolving_message: 'Menunggu Telegram',
    hashing: 'Memverifikasi file',
    registering: 'Menyimpan metadata',
    staging: 'Menyiapkan backup',
    compressing: 'Mengompres',
    extracting: 'Mengekstrak',
    downloading: 'Mendownload media',
    processing_json: 'Memproses JSON',
    completed: 'Selesai',
    starting: 'Memulai'
  };
  return labels[value] || value.replaceAll('_', ' ');
}
