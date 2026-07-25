export type LabelItem = { label: string; updated_at?: string | null };

export function textValue(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? 'Ya' : 'Tidak';
  if (Array.isArray(value)) return value.map((item) => textValue(item, '')).filter(Boolean).join(', ') || fallback;
  return fallback;
}

export function formatBytes(value: unknown): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return 'Tidak diketahui';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function formatDate(value: unknown): string {
  if (!value) return '-';
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? textValue(value) : date.toLocaleString('id-ID');
}

export function jobMessage(job: Record<string, any>): string {
  return textValue(job.progress?.message || job.result?.message || job.result?.status || job.error?.message, 'Menunggu proses');
}

export function resultEntries(value: unknown): Array<[string, string]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => [
    key,
    typeof item === 'object' && item !== null ? JSON.stringify(item) : textValue(item)
  ]);
}

export function groupIdsByWorker<T extends { id: string; worker?: string | null }>(items: T[]): Map<string, string[]> {
  const groups = new Map<string, string[]>();
  for (const item of items) {
    const worker = item.worker || 'local';
    groups.set(worker, [...(groups.get(worker) || []), item.id]);
  }
  return groups;
}
