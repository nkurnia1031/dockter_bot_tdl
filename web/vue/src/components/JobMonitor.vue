<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { api, post } from '../lib/api';
import { formatBytes, formatDate, jobMessage, textValue } from '../../../src/lib/presentation';
import { formatDuration, normalizeJobProgress, phaseLabel } from '../../../src/lib/job-progress';
import { operatorTdlLogText } from '../../../src/lib/tdl-lanes';
import { session } from '../session';

type Job = Record<string, any> & { id: string; kind: string; status: string; worker?: string };
type JobEvent = Record<string, any>;
type MonitorView = 'all' | 'active' | 'history';
type PollingMode = 'active' | 'activity';

const props = withDefaults(defineProps<{
  title?: string;
  kind?: string;
  worker?: string;
  profile?: string;
  scope?: 'current' | 'global';
  status?: string;
  quickMode?: boolean;
  retryable?: boolean;
  view?: MonitorView;
  pollingMode?: PollingMode;
}>(), {
  title: 'Aktivitas terbaru', worker: '', profile: '', scope: 'current', view: 'all', pollingMode: 'active'
});

const jobs = ref<Job[]>([]);
const monitorMetrics = ref<Record<string, any> | null>(null);
const error = ref('');
const notice = ref('');
const loading = ref(false);
const loaded = ref(false);
const lastRefreshed = ref<Date | null>(null);
const statusFilter = ref('all');
const kindFilter = ref('all');
const selected = ref<Job | null>(null);
const detailTab = ref<'summary' | 'events' | 'log' | 'raw'>('summary');
const events = ref<JobEvent[]>([]);
const logSnapshot = ref<Record<string, any> | null>(null);
const eventLoadError = ref('');
const logLoadError = ref('');
const detailFeedback = ref<{ kind: 'success' | 'error'; message: string } | null>(null);
const detailLoading = ref(false);
const detailOpen = ref(false);
const confirmTarget = ref<'all' | 'one' | null>(null);
const detailDialog = ref<HTMLElement | null>(null);
const detailCloseButton = ref<HTMLButtonElement | null>(null);
const confirmDialog = ref<HTMLElement | null>(null);
const confirmCancelButton = ref<HTMLButtonElement | null>(null);
const monitorRegion = ref<HTMLElement | null>(null);
const actionBusy = ref<Record<string, boolean>>({});
const mounted = ref(false);
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let requestGeneration = 0;
let detailRequestGeneration = 0;
let detailReturnFocus: HTMLElement | null = null;
let confirmReturnFocus: HTMLElement | null = null;
const terminalChecks = new Set<string>();
const pendingTerminalChecks = new Set<string>();
let hasLoaded = false;

const activeStates = ['queued', 'dispatched', 'running', 'paused'];
const isActive = (job: Job) => activeStates.includes(job.status);
const activeJobs = computed(() => jobs.value.filter(isActive).sort((a, b) => {
  const left = Date.parse(String(a.created_at || ''));
  const right = Date.parse(String(b.created_at || ''));
  if (Number.isFinite(left) && Number.isFinite(right) && left !== right) return left - right;
  return String(a.id).localeCompare(String(b.id));
}));
const kinds = computed(() => [...new Set(jobs.value.map((job) => job.kind).filter(Boolean))].sort());
const filteredJobs = computed(() => {
  let result = props.view === 'active' ? activeJobs.value : props.view === 'history' ? jobs.value.filter((job) => !isActive(job)) : jobs.value;
  if (statusFilter.value !== 'all') {
    result = statusFilter.value === 'active' ? result.filter(isActive) : result.filter((job) => job.status === statusFilter.value);
  }
  if (kindFilter.value !== 'all') result = result.filter((job) => job.kind === kindFilter.value);
  const active = props.view === 'all'
    ? activeJobs.value.filter((job) => result.some((candidate) => candidate.id === job.id))
    : result.filter(isActive);
  const history = result.filter((job) => !isActive(job)).sort((a, b) => Date.parse(String(b.created_at || '')) - Date.parse(String(a.created_at || '')));
  return props.view === 'history' ? history : [...active, ...history];
});
const detailProgress = computed(() => selected.value ? normalizeJobProgress(selected.value) : null);
const displayedLogLines = computed(() => (logSnapshot.value?.log?.lines || []).map((line: unknown) => operatorTdlLogText(String(line))));
const rawDetailsText = computed(() => JSON.stringify({ job: selected.value, events: events.value }, null, 2));
const isActivity = computed(() => props.pollingMode === 'activity');

function stopPolling() {
  if (pollTimer !== undefined) clearTimeout(pollTimer);
  pollTimer = undefined;
}

function schedulePolling() {
  stopPolling();
  if (!mounted.value || props.view === 'history' || document.visibilityState !== 'visible') return;
  if (props.pollingMode === 'active' && activeJobs.value.length === 0) return;
  pollTimer = setTimeout(() => { void load(true); }, activeJobs.value.length ? 2500 : 10_000);
}

function requestQuery(): URLSearchParams {
  const query = new URLSearchParams({ limit: '30', scope: props.scope });
  if (props.worker) query.set('worker', props.worker);
  if (props.profile) query.set('profile', props.profile);
  if (props.status) query.set('status', props.status);
  if (props.view === 'active') query.set('status', 'queued,dispatched,running,paused');
  if (props.view === 'history') query.set('status', props.status || 'succeeded,failed,cancelled');
  if (props.quickMode) query.set('quick_mode', 'true');
  return query;
}

async function load(scheduled = false) {
  if (!scheduled) stopPolling();
  const generation = ++requestGeneration;
  const previousActive = new Set(jobs.value.filter(isActive).map((job) => String(job.id)));
  loading.value = true;
  error.value = '';
  const query = requestQuery();
  const selectedKinds = props.kind === 'storage_upload' ? ['storage_upload', 'storage_reconcile'] : props.kind ? [props.kind] : [''];
  try {
    const requests = selectedKinds.map((kind) => {
      const params = new URLSearchParams(query);
      if (kind) params.set('kind', kind);
      return api<{ items?: Job[] }>(`/jobs?${params.toString()}`);
    });
    const metricsParams = new URLSearchParams({ scope: props.scope });
    if (props.worker) metricsParams.set('worker', props.worker);
    if (props.profile) metricsParams.set('profile', props.profile);
    const metricsRequest = props.view === 'history' || (scheduled && props.pollingMode !== 'activity')
      ? Promise.resolve(null)
      : api<Record<string, any>>(`/jobs/metrics?${metricsParams.toString()}`).catch(() => null);
    const [jobResponses, metrics] = await Promise.all([Promise.all(requests), metricsRequest]);
    if (generation !== requestGeneration) return;
    jobs.value = jobResponses.flatMap((response) => response.items || [])
      .sort((a, b) => Date.parse(String(b.created_at || '')) - Date.parse(String(a.created_at || '')))
      .slice(0, 30);
    monitorMetrics.value = metrics;
    lastRefreshed.value = new Date();
    if (selected.value) selected.value = jobs.value.find((job) => job.id === selected.value?.id) || selected.value;
    if (hasLoaded) {
      const byId = new Map(jobs.value.map((job) => [String(job.id), job]));
      const terminal = new Set(['succeeded', 'failed', 'cancelled']);
      const finished = [...previousActive].filter((id) => terminal.has(String(byId.get(id)?.status || '')));
      const missing = [...previousActive].filter((id) => !byId.has(id));
      for (const id of previousActive) {
        if (byId.has(id)) pendingTerminalChecks.delete(id);
        else pendingTerminalChecks.add(id);
      }
      if (finished.length) window.dispatchEvent(new CustomEvent('tme3:job-finished', { detail: { jobIds: finished } }));
      checkDisappearedJobs([...new Set([...missing, ...pendingTerminalChecks])]);
    }
    loaded.value = true;
    hasLoaded = true;
  } catch (cause) {
    if (generation === requestGeneration) error.value = cause instanceof Error ? cause.message : 'Tidak dapat memuat job.';
  } finally {
    if (generation === requestGeneration) {
      loading.value = false;
      schedulePolling();
    }
  }
}

function checkDisappearedJobs(jobIds: string[]) {
  for (const id of jobIds) {
    if (terminalChecks.has(id)) continue;
    terminalChecks.add(id);
    void api<Job>(`/jobs/${encodeURIComponent(id)}`)
      .then((job) => {
        if (mounted.value && ['succeeded', 'failed', 'cancelled'].includes(job.status)) {
          pendingTerminalChecks.delete(id);
          window.dispatchEvent(new CustomEvent('tme3:job-finished', { detail: { jobIds: [id] } }));
        } else if (mounted.value) pendingTerminalChecks.add(id);
      })
      .catch(() => { if (mounted.value) pendingTerminalChecks.add(id); })
      .finally(() => terminalChecks.delete(id));
  }
}

async function openDetails(job: Job, tab: 'summary' | 'events' | 'log' | 'raw' = 'summary') {
  const wasOpen = detailOpen.value;
  if (!wasOpen) detailReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const generation = ++detailRequestGeneration;
  selected.value = job;
  detailTab.value = tab;
  detailOpen.value = true;
  detailLoading.value = true;
  events.value = [];
  logSnapshot.value = null;
  eventLoadError.value = '';
  logLoadError.value = '';
  detailFeedback.value = null;
  if (!wasOpen) {
    await nextTick();
    detailCloseButton.value?.focus();
  }
  try {
    const jobId = encodeURIComponent(job.id);
    const [jobResult, eventResult, logResult] = await Promise.allSettled([
      api<Job>(`/jobs/${jobId}`),
      api<{ items?: JobEvent[] }>(`/jobs/${jobId}/events?after_sequence=0`),
      api<Record<string, any>>(`/jobs/${jobId}/log-snapshot`)
    ]);
    if (generation !== detailRequestGeneration) return;
    if (jobResult.status === 'rejected') throw jobResult.reason;
    selected.value = jobResult.value;
    if (eventResult.status === 'fulfilled') events.value = eventResult.value.items || [];
    else eventLoadError.value = eventResult.reason instanceof Error ? eventResult.reason.message : 'Event job tidak dapat dimuat.';
    if (logResult.status === 'fulfilled') logSnapshot.value = logResult.value;
    else logLoadError.value = logResult.reason instanceof Error ? logResult.reason.message : 'Snapshot log tidak dapat dimuat.';
  } catch (cause) {
    if (generation === detailRequestGeneration) error.value = cause instanceof Error ? cause.message : 'Detail job tidak dapat dimuat.';
  } finally {
    if (generation === detailRequestGeneration) detailLoading.value = false;
  }
}

async function closeDetails() {
  ++detailRequestGeneration;
  detailLoading.value = false;
  detailOpen.value = false;
  const target = detailReturnFocus;
  detailReturnFocus = null;
  await nextTick();
  if (target?.isConnected) target.focus();
  else monitorRegion.value?.focus();
}

function openConfirm(target: 'all' | 'one', job?: Job) {
  if (job) selected.value = job;
  confirmReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  confirmTarget.value = target;
  void nextTick(() => confirmCancelButton.value?.focus());
}

async function closeConfirm() {
  confirmTarget.value = null;
  const target = confirmReturnFocus;
  confirmReturnFocus = null;
  await nextTick();
  const fallback = detailOpen.value ? detailDialog.value : null;
  if (target?.isConnected) target.focus();
  else if (fallback) fallback.focus();
  else monitorRegion.value?.focus();
}

function handleDialogKeydown(event: KeyboardEvent, kind: 'detail' | 'confirm') {
  const dialog = kind === 'confirm' ? confirmDialog.value : detailDialog.value;
  if (!dialog) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    if (kind === 'confirm') void closeConfirm();
    else void closeDetails();
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = [...dialog.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true');
  if (!focusable.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
}

async function terminate() {
  try {
    if (confirmTarget.value === 'all') {
      const params = new URLSearchParams();
      if (props.scope === 'global') params.set('scope', 'global');
      else {
        params.set('scope', 'current');
        const profile = props.profile || session.current.actor?.profile;
        if (profile) params.set('profile', profile);
      }
      if (props.kind) params.set('kind', props.kind);
      if (props.quickMode) {
        params.set('kind', 'export');
        params.set('quick_mode', 'true');
      }
      const suffix = params.toString();
      const response = await post<Record<string, any>>(`/jobs/terminate-active${suffix ? `?${suffix}` : ''}`);
      const accepted = Number(response?.cancel_requested || 0);
      const queued = Number(response?.cancelled_queued || 0);
      const unknown = Number(response?.not_confirmed || 0);
      notice.value = `${accepted} permintaan diterima, ${queued} job antrean dibatalkan${unknown ? `, ${unknown} belum dikonfirmasi worker` : ''}.`;
    } else if (selected.value) {
      await post(`/jobs/${encodeURIComponent(selected.value.id)}/cancel`);
      notice.value = 'Permintaan berhenti diterima; menunggu konfirmasi worker.';
    }
    await closeConfirm();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Job gagal dihentikan.';
    await closeConfirm();
  }
}

async function performJobAction(job: Job, action: 'retry' | 'reconcile' | 'pause' | 'resume') {
  if (action === 'retry') {
    const confirmation = job.kind === 'storage_upload'
      ? 'Retry hanya mengirim file yang dipastikan belum diterima Telegram. File dengan hasil ambigu tidak ikut dikirim. Lanjutkan?'
      : job.kind === 'chat_send'
        ? 'Retry hanya mengirim file yang dipastikan gagal sebelum terkirim. File ambigu tidak akan diulang. Lanjutkan?'
        : job.status === 'succeeded' ? 'Jalankan job ini lagi dari awal?' : null;
    if (confirmation && !window.confirm(confirmation)) return;
  }
  actionBusy.value = { ...actionBusy.value, [job.id]: true };
  try {
    if (action === 'retry') {
      const path = job.kind === 'tts' ? `/tts/jobs/${encodeURIComponent(job.id)}/retry`
        : job.kind === 'chat_send' ? `/chat-send/jobs/${encodeURIComponent(job.id)}/retry`
          : `/jobs/${encodeURIComponent(job.id)}/retry`;
      await post(path);
      notice.value = 'Retry masuk antrean.';
    } else {
      await post(`/jobs/${encodeURIComponent(job.id)}/${action}`);
      notice.value = action === 'reconcile' ? 'Rekonsiliasi masuk antrean.' : action === 'pause' ? 'Job akan dijeda.' : 'Job masuk kembali ke antrean.';
    }
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Aksi job gagal.';
  } finally {
    const next = { ...actionBusy.value };
    delete next[job.id];
    actionBusy.value = next;
  }
}

function formatClock(date: Date | null) {
  return date?.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) || '—';
}
function kindLabel(job: Partial<Job>) {
  if (job.kind === 'tts') return 'TTS';
  if (job.kind === 'storage_reconcile') return 'Storage reconcile';
  if (job.kind === 'storage_rclone_manage') return `Rclone ${job.payload?.action || 'manage'}`;
  return String(job.kind || 'job').replaceAll('_', ' ');
}
function jobTitle(job: Job) {
  if (job.kind === 'tts') {
    const title = job.payload?.title;
    return typeof title === 'string' && title.trim() ? title.trim() : 'Judul tidak tersedia';
  }
  const file = String(job.progress?.active_file || job.progress?.item?.name || job.progress?.current_json_name || '');
  return file.split(/[\\/]/).filter(Boolean).at(-1) || kindLabel(job);
}
function jobError(job: Job) {
  const code = job.error?.reason_code || job.error?.code;
  return typeof code === 'string' && /^[A-Z0-9_]{2,64}$/.test(code) ? code : 'Periksa detail job';
}
function safeJobMessage(job: Job) {
  return operatorTdlLogText(jobMessage(job));
}
function itemMetrics(job: Job) {
  const progress = normalizeJobProgress(job);
  const transfer = progress.transfer;
  const speed = typeof transfer.speed_text === 'string' ? transfer.speed_text : transfer.speed_bps ? `${formatBytes(transfer.speed_bps)}/dtk` : '';
  const eta = transfer.eta_seconds !== undefined ? formatDuration(transfer.eta_seconds) : '';
  const current = progress.item.name || progress.batch.name || progress.message;
  const safeCurrent = operatorTdlLogText(String(current || '').split(/[\\/]/).filter(Boolean).at(-1) || '');
  const bytes = progress.transfer.bytes_current !== undefined
    ? `${formatBytes(progress.transfer.bytes_current)}${progress.transfer.bytes_total !== undefined ? ` / ${formatBytes(progress.transfer.bytes_total)}` : progress.item.size_bytes !== undefined ? ` / ${formatBytes(progress.item.size_bytes)}` : ''}`
    : '';
  return [safeCurrent, bytes, speed, eta].filter(Boolean).join(' · ');
}
function batchMetrics(job: Job) {
  const overall = normalizeJobProgress(job).overall;
  const filesCurrent = overall.files_current ?? (overall.unit === 'files' ? overall.current : undefined);
  const filesTotal = overall.files_total ?? (overall.unit === 'files' ? overall.total : undefined);
  const files = filesTotal !== undefined ? `Batch ${filesCurrent ?? 0}/${filesTotal} file` : '';
  const bytes = overall.bytes_total !== undefined ? `${formatBytes(overall.bytes_current || 0)} / ${formatBytes(overall.bytes_total)} batch` : '';
  return [files, bytes].filter(Boolean).join(' · ');
}
function activeMetricItems(job: Job): Array<{ profile?: string; name: string; label: string; metrics: string; percent?: number }> {
  return normalizeJobProgress(job).activeItems.map((item, index) => {
    const name = operatorTdlLogText(String(item.name || item.file || `File ${index + 1}`).split(/[\\/]/).filter(Boolean).at(-1) || `File ${index + 1}`);
    const speed = item.speed_text || (item.speed_bps ? `${formatBytes(item.speed_bps)}/dtk` : '');
    const eta = item.eta_seconds !== undefined ? `ETA ${formatDuration(item.eta_seconds)}` : '';
    const bytes = item.size_bytes !== undefined ? `${formatBytes(item.bytes_current || 0)} / ${formatBytes(item.size_bytes)}` : 'Ukuran belum diketahui';
    return { profile: typeof item.profile === 'string' ? item.profile : undefined, percent: typeof item.percent === 'number' ? item.percent : undefined, name, label: [item.profile, name].filter(Boolean).join(' · '), metrics: [bytes, speed, eta].filter(Boolean).join(' · ') };
  });
}
function cancelAccepted(job: Job) {
  return job.progress?.cancel_request?.status === 'accepted' && ['dispatched', 'running', 'paused'].includes(job.status);
}
function storageStatusLabel(status: unknown) {
  const labels: Record<string, string> = {
    succeeded: 'Berhasil', failed: 'Gagal', pending: 'Menunggu', sending: 'Mengirim', skipped: 'Dilewati · target sudah ada',
    needs_reconciliation: 'Perlu verifikasi', cancelled: 'Dibatalkan', succeeded_unverified: 'Terkirim · belum terverifikasi'
  };
  return labels[String(status || 'unknown')] || 'Status tercatat';
}
function cleanupStatusLabel(status: unknown) {
  const labels: Record<string, string> = {
    deleted: 'Dihapus', not_requested: 'Tidak diminta', retained_ambiguous: 'Sumber disimpan · hasil belum pasti',
    retained_upload_failed: 'Sumber disimpan · upload gagal', retained_existing_target: 'Sumber disimpan · target sudah ada',
    skipped_source_changed: 'Dilewati · sumber berubah', cleanup_failed: 'Gagal menghapus', retained_unverified: 'Sumber disimpan · belum terverifikasi'
  };
  return labels[String(status || '')] || 'Sumber dipertahankan';
}
function fileResultTitle(item: Record<string, any>, index: number, kind: string) {
  if (kind === 'storage_reconcile') return item.name || `File ${index + 1}`;
  const raw = item.name || item.path || `File ${index + 1}`;
  return kind === 'storage_upload' ? String(raw).split(/[\\/]/).filter(Boolean).at(-1) || `File ${index + 1}` : raw;
}
function fileResultMessage(item: Record<string, any>, kind: string) {
  if (kind === 'storage_reconcile') return '';
  if (kind === 'storage_upload') {
    const code = item.error_code || item.reason_code;
    return typeof code === 'string' && /^[A-Z0-9_]{2,64}$/.test(code) ? code : '';
  }
  return item.error || item.reason || '';
}
function downloadLinkLabel(status: unknown) {
  return ({ succeeded: 'Link siap', failed: 'Link gagal dibuat', not_created: 'Link tidak dibuat', not_requested: 'Tanpa link publik' } as Record<string, string>)[String(status || '')] || '';
}
function eventDescription(event: JobEvent) {
  const batch = event.progress?.batch;
  const item = event.progress?.item;
  const detail = [batch?.index ? `JSON ${batch.index}/${batch.total || '?'}` : '', item?.index ? `File ${item.index}/${item.total || '?'}` : '', event.progress?.message, event.error?.message, event.result?.status].filter(Boolean).join(' · ');
  return operatorTdlLogText(`#${event.sequence ?? '?'} ${event.event_type || 'event'} · ${textValue(detail, 'Event tercatat')}`);
}
function eventCommand(event: JobEvent) {
  const command = event.result?.command;
  return operatorTdlLogText(Array.isArray(command) ? command.map(String).join(' ') : 'Command tidak tersedia');
}
function isCommandEvent(event: JobEvent) {
  return event.event_type === 'command.started' || event.event_type === 'command.completed';
}
function commandOutput(event: JobEvent) {
  return Array.isArray(event.result?.output_tail)
    ? event.result.output_tail.filter((line: unknown) => typeof line === 'string').map((line: string) => operatorTdlLogText(line)).join('\n')
    : '';
}
function resultSummary(job: Job) {
  const result = job.result?.value || job.result;
  if (!result || typeof result !== 'object') return [];
  return Object.entries(result).filter(([key, value]) => key !== 'items' && key !== 'report' && value !== null && typeof value !== 'object').slice(0, 12);
}
function backupVerificationReport(job: Job | null) {
  const result = job?.result?.value || job?.result || {};
  const report = result?.report;
  return job?.kind === 'backup_verify' && report && typeof report === 'object' ? report as Record<string, unknown> : null;
}
function downloadBackupVerificationReport(job: Job) {
  const report = backupVerificationReport(job);
  if (!report) return;
  const safePart = (value: unknown) => String(value || '').replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80) || 'unknown';
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(report, null, 2)}\n`], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `backup-verification-${safePart(report.worker)}-${safePart(report.profile)}-${safePart(report.run_id)}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function canRetry(job: Job) {
  if (!props.retryable || !['failed', 'cancelled', 'succeeded'].includes(job.status)) return false;
  if (['export', 'tts'].includes(job.kind)) return true;
  return ['storage_upload', 'chat_send'].includes(job.kind) && job.retryable === true && job.status !== 'succeeded';
}
function hasAmbiguousStorageFiles(job: Job) {
  if (job.kind !== 'storage_upload' || job.payload?.provider === 'rclone' || !['failed', 'cancelled'].includes(job.status)) return false;
  const items = job.result?.value?.items || job.result?.items;
  return Array.isArray(items) && items.some((item: Record<string, unknown>) => item?.status === 'needs_reconciliation');
}
function canPause(job: Job) {
  return job.kind === 'tts' || (props.quickMode && job.payload?.quick_mode === true);
}
async function copyDetailText(value: string, successMessage: string, failureMessage: string) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard tidak tersedia');
    await navigator.clipboard.writeText(value);
    detailFeedback.value = { kind: 'success', message: successMessage };
  } catch {
    detailFeedback.value = { kind: 'error', message: failureMessage };
  }
}
async function copyLog() {
  await copyDetailText(displayedLogLines.value.join('\n'), 'Log disalin.', 'Log tidak dapat disalin. Periksa izin clipboard browser.');
}
async function copyRawDetails() {
  await copyDetailText(rawDetailsText.value, 'JSON job disalin.', 'JSON job tidak dapat disalin. Periksa izin clipboard browser.');
}
function onVisibilityChange() {
  if (document.visibilityState !== 'visible') stopPolling();
  else if (props.view !== 'history' && (props.pollingMode === 'activity' || activeJobs.value.length)) void load();
}
function onMutation() { void load(); }
function onContextChange() { requestGeneration += 1; pendingTerminalChecks.clear(); jobs.value = []; monitorMetrics.value = null; selected.value = null; if (detailOpen.value) void closeDetails(); void load(); }
function onJobFinished() { if (props.view === 'history') void load(); }

watch(() => [props.kind, props.worker, props.profile, props.scope, props.status, props.quickMode, props.view, props.pollingMode], () => { pendingTerminalChecks.clear(); statusFilter.value = 'all'; kindFilter.value = 'all'; void load(); });
onMounted(() => {
  mounted.value = true;
  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('tme3:data-mutated', onMutation);
  window.addEventListener('tme3:context-changed', onContextChange);
  window.addEventListener('tme3:job-finished', onJobFinished);
  void load();
});
onUnmounted(() => {
  mounted.value = false;
  requestGeneration += 1;
  stopPolling();
  document.removeEventListener('visibilitychange', onVisibilityChange);
  window.removeEventListener('tme3:data-mutated', onMutation);
  window.removeEventListener('tme3:context-changed', onContextChange);
  window.removeEventListener('tme3:job-finished', onJobFinished);
});
</script>

<template>
  <section ref="monitorRegion" class="panel job-monitor" aria-label="Monitor job" tabindex="-1">
    <header class="job-monitor-header">
      <div><p class="eyebrow">{{ view === 'history' ? 'HISTORY' : 'JOB MONITOR' }}</p><h2>{{ title }}</h2></div>
      <div class="monitor-actions">
        <span v-if="isActivity" class="status-pill status-neutral">Live · 2,5 dtk aktif / 10 dtk idle</span>
        <span v-else-if="activeJobs.length" class="status-pill status-running">Progress otomatis · job aktif</span>
        <span v-else class="muted monitor-cadence">Refresh manual</span>
        <span v-if="lastRefreshed" class="muted monitor-updated">{{ formatClock(lastRefreshed) }}</span>
        <button v-if="view !== 'history' && !worker && !(scope === 'global' && profile)" class="button button-danger" aria-label="Terminate semua job aktif" :disabled="activeJobs.length === 0" @click="openConfirm('all')">Hentikan semua</button>
        <span v-else-if="view !== 'history' && worker" class="muted monitor-cadence">Gunakan Stop per job untuk membatasi ke worker ini</span>
        <span v-else-if="view !== 'history' && scope === 'global' && profile" class="muted monitor-cadence">Gunakan Stop per job untuk membatasi ke profil ini</span>
        <button class="button button-secondary" aria-label="Refresh daftar job" :disabled="loading" @click="load()">{{ loading ? 'Memuat…' : 'Refresh' }}</button>
      </div>
    </header>

    <div v-if="error" class="notice notice-error" role="alert">{{ error }}</div>
    <div v-else-if="notice" class="notice notice-success" role="status">{{ notice }}</div>

    <section v-if="view !== 'history' && monitorMetrics" class="metrics-grid" aria-label="Metrik monitor">
      <article class="metric-card"><span class="metric-label">Aktif · dispatch / running</span><strong>{{ monitorMetrics.active_jobs || 0 }}</strong></article>
      <article class="metric-card"><span class="metric-label">Antrean</span><strong>{{ monitorMetrics.queued_jobs || 0 }}</strong></article>
      <article class="metric-card"><span class="metric-label">Rata-rata waktu tunggu · 24 jam</span><strong>{{ monitorMetrics.average_queue_wait_seconds == null ? 'Belum ada data' : formatDuration(monitorMetrics.average_queue_wait_seconds) }}</strong></article>
      <article class="metric-card"><span class="metric-label">Latensi event worker</span><strong>{{ monitorMetrics.event_latency?.average_ms == null ? 'Belum ada data' : `${Math.round(monitorMetrics.event_latency.average_ms)} ms` }}</strong></article>
    </section>
    <div v-if="monitorMetrics?.workers?.length" class="worker-metrics" aria-label="Status worker">
      <span v-for="worker in monitorMetrics.workers" :key="worker.worker" class="status-pill" :class="worker.status === 'stale' ? 'status-warning' : worker.status === 'disabled' ? 'status-neutral' : 'status-ready'">
        {{ worker.worker }} · {{ worker.status }} · {{ worker.active_jobs || 0 }} aktif · {{ worker.queued_jobs || 0 }} antre
      </span>
    </div>

    <div class="job-filters">
      <label><span>Status</span><select aria-label="Filter status" v-model="statusFilter"><option value="all">Semua status</option><option value="active">Aktif / antre</option><option value="succeeded">Selesai</option><option value="failed">Gagal</option><option value="cancelled">Dibatalkan</option></select></label>
      <label><span>Jenis job</span><select aria-label="Filter jenis" v-model="kindFilter"><option value="all">Semua jenis</option><option v-for="kind in kinds" :key="kind" :value="kind">{{ kindLabel({ kind }) }}</option></select></label>
      <span class="muted filter-count">{{ filteredJobs.length }} job · maks. 30 terbaru</span>
    </div>

    <div v-if="!loaded" class="empty-state" role="status">Memuat job…</div>
    <div v-else-if="!filteredJobs.length" class="empty-state">{{ statusFilter === 'active' ? 'Tidak ada job aktif atau antre.' : 'Belum ada job yang cocok dengan filter.' }}</div>
    <template v-else>
      <div class="activity-table-wrap">
        <table class="activity-table">
          <thead><tr><th>Job</th><th>Status</th><th>Worker</th><th>Progress</th><th>Diperbarui</th><th><span class="sr-only">Aksi</span></th></tr></thead>
          <tbody>
            <tr v-for="job in filteredJobs" :key="job.id">
              <td><strong>{{ jobTitle(job) }}</strong><small>#{{ job.id.slice(0, 8) }} · {{ kindLabel(job) }}</small></td>
              <td><span class="status-pill" :class="`status-${job.status}`">{{ job.status }}</span></td>
              <td>{{ job.worker || '—' }}</td>
              <td class="progress-cell"><template v-if="isActive(job)"><span>{{ itemMetrics(job) }}</span><small v-if="batchMetrics(job)" class="batch-metrics">{{ batchMetrics(job) }}</small><small v-if="cancelAccepted(job)" class="cancel-accepted" role="status">Permintaan berhenti diterima; menunggu konfirmasi worker</small><div v-for="item in activeMetricItems(job)" :key="`${item.profile || ''}-${item.name}`" class="active-metric-row"><strong>{{ item.label }}</strong><small>{{ item.metrics || (item.percent === undefined ? 'Berjalan' : `${item.percent.toFixed(1)}%`) }}</small></div><div v-if="normalizeJobProgress(job).overall.percent !== undefined" class="mini-progress"><i :style="{ width: `${normalizeJobProgress(job).overall.percent}%` }"></i></div></template><span v-else-if="job.status === 'failed'" class="failure-code">{{ jobError(job) }}</span><span v-else>{{ safeJobMessage(job) }}</span></td>
              <td>{{ formatDate(job.updated_at || job.created_at) }}</td>
              <td class="row-actions"><button class="button button-secondary button-small" :aria-label="`Detail job ${job.id}`" @click="openDetails(job)">Detail</button><button v-if="isActive(job)" class="button button-danger button-small" :aria-label="`Hentikan job ${job.id}`" @click="openConfirm('one', job)">Stop</button><button v-if="isActive(job) && canPause(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, job.status === 'paused' ? 'resume' : 'pause')">{{ job.status === 'paused' ? 'Lanjutkan' : 'Jeda' }}</button><button v-if="hasAmbiguousStorageFiles(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, 'reconcile')">Rekonsiliasi</button><button v-if="canRetry(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, 'retry')">{{ ['storage_upload','chat_send'].includes(job.kind) ? 'Retry file aman' : job.status === 'succeeded' ? 'Jalankan lagi' : 'Retry' }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="activity-cards">
        <article v-for="job in filteredJobs" :key="job.id" class="activity-card">
          <div class="activity-card-heading"><strong>{{ jobTitle(job) }}</strong><span class="status-pill" :class="`status-${job.status}`">{{ job.status }}</span></div>
          <p class="muted">{{ kindLabel(job) }} · {{ job.worker || '—' }} · #{{ job.id.slice(0, 8) }}</p>
          <p class="activity-card-progress">{{ isActive(job) ? itemMetrics(job) : job.status === 'failed' ? jobError(job) : safeJobMessage(job) }}</p>
          <small v-if="isActive(job) && batchMetrics(job)" class="batch-metrics">{{ batchMetrics(job) }}</small>
          <small v-if="isActive(job) && cancelAccepted(job)" class="cancel-accepted" role="status">Permintaan berhenti diterima; menunggu konfirmasi worker</small>
          <div v-if="isActive(job) && activeMetricItems(job).length" class="active-metric-list"><article v-for="item in activeMetricItems(job)" :key="`${item.profile || ''}-${item.name}`"><strong>{{ item.label }}</strong><span>{{ item.metrics || (item.percent === undefined ? 'Berjalan' : `${item.percent.toFixed(1)}%`) }}</span></article></div>
          <div class="row-actions"><button class="button button-secondary button-small" :aria-label="`Detail job ${job.id}`" @click="openDetails(job)">Detail</button><button v-if="isActive(job)" class="button button-danger button-small" :aria-label="`Hentikan job ${job.id}`" @click="openConfirm('one', job)">Stop</button><button v-if="isActive(job) && canPause(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, job.status === 'paused' ? 'resume' : 'pause')">{{ job.status === 'paused' ? 'Lanjutkan' : 'Jeda' }}</button><button v-if="hasAmbiguousStorageFiles(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, 'reconcile')">Rekonsiliasi</button><button v-if="canRetry(job)" class="button button-secondary button-small" :disabled="actionBusy[job.id]" @click="performJobAction(job, 'retry')">Retry</button></div>
        </article>
      </div>
    </template>
  </section>

  <div v-if="detailOpen && selected" class="modal-backdrop" @click.self="closeDetails">
    <section ref="detailDialog" class="modal-card job-detail-modal" role="dialog" :aria-modal="confirmTarget ? undefined : 'true'" :aria-hidden="confirmTarget ? 'true' : undefined" :inert="confirmTarget ? '' : null" tabindex="-1" :aria-label="`Detail job ${selected.id}`" @keydown="handleDialogKeydown($event, 'detail')">
      <header class="modal-heading"><div><p class="eyebrow">JOB · {{ selected.id.slice(0, 12) }}</p><h2>{{ jobTitle(selected) }}</h2></div><button ref="detailCloseButton" class="icon-button" aria-label="Tutup detail" @click="closeDetails">×</button></header>
      <nav class="detail-tabs" aria-label="Tab detail"><button v-for="tab in (['summary', 'events', 'log', 'raw'] as const)" :key="tab" :class="{ active: detailTab === tab }" :aria-pressed="detailTab === tab" @click="detailTab = tab">{{ tab === 'summary' ? 'Ringkasan' : tab === 'events' ? 'Event' : tab === 'log' ? 'Log' : 'JSON mentah' }}</button><button class="button button-secondary button-small" :disabled="detailLoading" @click="openDetails(selected, detailTab)">Refresh detail</button></nav>
      <div v-if="detailLoading" class="empty-state">Memuat detail…</div>
      <div v-else-if="detailTab === 'summary'" class="detail-body">
        <div class="detail-summary"><span class="status-pill" :class="`status-${selected.status}`">{{ selected.status }}</span><span>{{ kindLabel(selected) }}</span><span>{{ selected.worker || '—' }}</span><span>{{ formatDate(selected.started_at || selected.created_at) }}</span><span v-if="cancelAccepted(selected)" class="cancel-accepted" role="status">Permintaan berhenti diterima; menunggu konfirmasi worker</span></div>
        <p class="detail-message">{{ safeJobMessage(selected) }}</p>
        <div v-if="detailProgress && isActive(selected)" class="detail-progress"><div><strong>{{ phaseLabel(detailProgress.phase) }}</strong><span>{{ detailProgress.overall.percent === undefined ? 'Sedang berjalan' : `${detailProgress.overall.percent.toFixed(1)}%` }}</span></div><div class="mini-progress"><i :style="{ width: `${detailProgress.overall.percent || 0}%` }"></i></div><p>{{ itemMetrics(selected) }}</p><p v-if="batchMetrics(selected)">{{ batchMetrics(selected) }}</p></div>
        <div v-if="detailProgress?.activeItems.length" class="active-item-list"><article v-for="(item, index) in detailProgress.activeItems" :key="`${item.profile || ''}-${item.name || index}`"><strong>{{ item.name || 'File aktif' }}</strong><span>{{ item.profile || 'Profil tidak diketahui' }} · {{ item.percent === undefined ? 'Berjalan' : `${item.percent.toFixed(1)}%` }}</span><small>{{ item.speed_text || (item.speed_bps ? `${formatBytes(item.speed_bps)}/dtk` : '') }}{{ item.eta_seconds !== undefined ? ` · ETA ${formatDuration(item.eta_seconds)}` : '' }}</small></article></div>
        <div class="result-grid"><article v-for="([key, value]) in resultSummary(selected)" :key="key"><small>{{ key.replaceAll('_', ' ') }}</small><strong>{{ textValue(value) }}</strong></article></div>
        <button v-if="backupVerificationReport(selected)" class="button button-secondary" aria-label="Unduh JSON verifikasi" @click="downloadBackupVerificationReport(selected)">Unduh JSON verifikasi</button>
        <p v-if="selected.error" class="notice notice-error">{{ jobError(selected) }}</p>
        <section v-if="selected.kind === 'storage_download' && (selected.result?.value?.items || selected.result?.items)?.length" class="file-results" aria-label="Hasil download per file"><h3>Hasil download per file</h3><p class="muted">{{ selected.result?.value?.succeeded || selected.result?.succeeded || 0 }} berhasil · {{ selected.result?.value?.failed || selected.result?.failed || 0 }} gagal</p><article v-for="(item, index) in (selected.result?.value?.items || selected.result?.items)" :key="`${item.relative_path || item.name || index}:${index}`"><strong>{{ item.name || `File ${Number(index) + 1}` }}</strong><span>{{ item.download_status === 'succeeded' ? 'Download berhasil' : item.download_status === 'cancelled' ? 'Dibatalkan' : 'Download gagal' }} · {{ downloadLinkLabel(item.link_status) }}</span><small v-if="item.relative_path && item.relative_path !== item.name">{{ item.relative_path }}</small><a v-if="item.public_url" :href="item.public_url" target="_blank" rel="noopener noreferrer">{{ item.public_url }}</a><small v-if="item.error">{{ item.error }}</small></article></section>
        <section v-if="selected.kind !== 'storage_download' && (selected.result?.value?.items || selected.result?.items)?.length" class="file-results"><h3>Hasil per file</h3><article v-for="(item, index) in (selected.result?.value?.items || selected.result?.items)" :key="`${item.name || item.path || index}:${index}`"><strong>{{ fileResultTitle(item, Number(index) + 1, selected.kind) }}</strong><span>{{ ['storage_upload', 'storage_reconcile'].includes(selected.kind) ? storageStatusLabel(item.status || item.upload_status || item.download_status) : item.status || item.upload_status || item.download_status || '—' }}<template v-if="item.profile"> · {{ item.profile }}</template><template v-if="item.upload_status"> · Upload: {{ storageStatusLabel(item.upload_status) }}</template><template v-if="item.cleanup_status"> · sumber: {{ cleanupStatusLabel(item.cleanup_status) }}</template><template v-if="selected.kind === 'storage_reconcile'"> · caption cocok: {{ item.match_count || 0 }}<template v-if="item.retryable"> · aman untuk Retry</template></template></span><small v-if="fileResultMessage(item, selected.kind)">{{ fileResultMessage(item, selected.kind) }}</small></article></section>
      </div>
      <div v-else-if="detailTab === 'events'" class="detail-body event-list"><p v-if="eventLoadError" class="notice notice-error" role="alert">{{ eventLoadError }}</p><article v-for="event in [...events].sort((a, b) => Number(b.sequence || 0) - Number(a.sequence || 0))" :key="event.sequence"><div><strong>#{{ event.sequence }} · {{ event.event_type }}</strong><span class="status-pill" :class="`status-${event.status}`">{{ event.status }}</span></div><p>{{ eventDescription(event) }}</p><template v-if="isCommandEvent(event)"><p class="command-line">$ {{ eventCommand(event) }}</p><p v-if="event.event_type === 'command.started'" class="muted">Command dikirim, menunggu hasil…</p><template v-else><pre v-if="commandOutput(event)" class="command-output">{{ commandOutput(event) }}</pre><small class="muted">exit {{ event.result?.returncode ?? '?' }} · {{ event.result?.duration_seconds ?? 0 }} dtk<template v-if="event.result?.output_truncated"> · output lama dipangkas</template></small></template></template><small>{{ formatDate(event.created_at) }}</small></article><p v-if="!events.length && !eventLoadError" class="empty-state">Belum ada event.</p></div>
      <div v-else-if="detailTab === 'log'" class="detail-body log-body"><div class="log-toolbar"><span>{{ displayedLogLines.length }} baris</span><button class="button button-secondary button-small" @click="copyLog">Salin log</button></div><p v-if="detailFeedback" class="notice" :class="detailFeedback.kind === 'error' ? 'notice-error' : 'notice-success'" :role="detailFeedback.kind === 'error' ? 'alert' : 'status'">{{ detailFeedback.message }}</p><p v-if="logLoadError" class="notice notice-error" role="alert">{{ logLoadError }}</p><pre>{{ displayedLogLines.join('\n') || (logLoadError ? '' : 'Snapshot log belum tersedia.') }}</pre></div>
      <div v-else class="detail-body raw-body"><div class="log-toolbar"><span>Payload job dan event</span><button class="button button-secondary button-small" @click="copyRawDetails">Salin JSON</button></div><p v-if="detailFeedback" class="notice" :class="detailFeedback.kind === 'error' ? 'notice-error' : 'notice-success'" :role="detailFeedback.kind === 'error' ? 'alert' : 'status'">{{ detailFeedback.message }}</p><pre>{{ rawDetailsText }}</pre></div>
      <footer class="modal-actions"><button v-if="isActive(selected)" class="button button-danger" @click="openConfirm('one', selected)">Hentikan job</button><button class="button button-secondary" @click="closeDetails">Tutup</button></footer>
    </section>
  </div>
  <div v-if="confirmTarget" class="modal-backdrop confirm-backdrop" @click.self="closeConfirm"><section ref="confirmDialog" class="modal-card confirm-card" role="dialog" aria-modal="true" aria-labelledby="confirm-title" tabindex="-1" @keydown="handleDialogKeydown($event, 'confirm')"><h2 id="confirm-title">{{ confirmTarget === 'all' ? 'Hentikan semua job aktif?' : 'Hentikan job ini?' }}</h2><p>Permintaan pembatalan dikirim ke worker. Job mungkin memerlukan waktu untuk menyelesaikan dan melaporkan status terakhir.</p><footer class="modal-actions"><button ref="confirmCancelButton" class="button button-secondary" @click="closeConfirm">Batal</button><button class="button button-danger" aria-label="Konfirmasi hentikan job" @click="terminate">Konfirmasi stop</button></footer></section></div>
</template>

<style scoped>
.job-monitor{overflow:hidden}.job-monitor-header{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;padding:1rem 1.15rem;border-bottom:1px solid var(--line)}.job-monitor-header h2{margin:.25rem 0 0;font-size:1.1rem}.monitor-actions,.worker-metrics,.job-filters,.row-actions{display:flex;align-items:center;flex-wrap:wrap;gap:.55rem}.monitor-actions{justify-content:flex-end}.monitor-updated,.monitor-cadence{font-size:.75rem}.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;padding:.8rem 1rem;border-bottom:1px solid var(--line)}.metrics-grid .metric-card{padding:.65rem .75rem}.metrics-grid strong{display:block;margin-top:.35rem;font-size:1rem}.worker-metrics{padding:.65rem 1rem;border-bottom:1px solid var(--line)}.job-filters{padding:.75rem 1rem;align-items:end;border-bottom:1px solid var(--line)}.job-filters label{display:grid;gap:.25rem;font-size:.72rem;color:var(--muted)}.job-filters select{min-width:9rem}.filter-count{margin-left:auto;font-size:.75rem}.activity-table-wrap{overflow:auto}.activity-table{width:100%;border-collapse:collapse;text-align:left}.activity-table th{padding:.6rem .75rem;color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;background:var(--panel-soft)}.activity-table td{padding:.7rem .75rem;border-top:1px solid var(--line);font-size:.78rem;vertical-align:middle}.activity-table td:first-child{min-width:12rem}.activity-table td:first-child strong,.activity-table td:first-child small{display:block}.activity-table td:first-child small{margin-top:.2rem;color:var(--muted);font-size:.68rem}.progress-cell{max-width:21rem}.progress-cell>span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:22rem}.batch-metrics{display:block;margin-top:.2rem;color:var(--muted);font-size:.68rem;font-variant-numeric:tabular-nums}.cancel-accepted{display:inline-flex;margin-top:.25rem;color:var(--warning);font-size:.7rem}.failure-code{color:var(--danger)}.mini-progress{height:.3rem;margin-top:.4rem;border-radius:99px;background:var(--line);overflow:hidden}.mini-progress i{display:block;height:100%;background:var(--brand);border-radius:inherit;transition:width .2s ease}.button-small{padding:.34rem .52rem;font-size:.72rem}.button-danger{border-color:color-mix(in srgb,var(--danger) 35%,var(--line));background:color-mix(in srgb,var(--danger) 10%,var(--panel));color:var(--danger)}.button-danger:hover{border-color:var(--danger);background:color-mix(in srgb,var(--danger) 17%,var(--panel))}.activity-cards{display:none}.empty-state{padding:2.4rem 1rem;text-align:center;color:var(--muted)}.notice{margin:.75rem 1rem;padding:.7rem .85rem;border-radius:.65rem;font-size:.82rem}.notice-error{color:var(--danger);background:color-mix(in srgb,var(--danger) 10%,transparent)}.notice-success{color:var(--success);background:color-mix(in srgb,var(--success) 10%,transparent)}.modal-backdrop{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:1rem;background:rgba(3,8,18,.72);backdrop-filter:blur(5px);animation:fade-in .16s ease-out}.modal-card{display:flex;flex-direction:column;max-height:min(88dvh,54rem);width:min(58rem,100%);overflow:hidden;border:1px solid var(--line);border-radius:1rem;background:var(--panel);box-shadow:0 24px 80px rgba(0,0,0,.4);animation:modal-in .2s ease-out}.modal-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;padding:1rem 1.2rem;border-bottom:1px solid var(--line)}.modal-heading h2{margin:.25rem 0 0;font-size:1.15rem}.detail-tabs{display:flex;align-items:center;gap:.4rem;padding:.6rem 1rem;border-bottom:1px solid var(--line)}.detail-tabs button:not(.button){padding:.45rem .65rem;color:var(--muted);border-radius:.5rem}.detail-tabs button.active{color:var(--ink);background:var(--panel-soft)}.detail-tabs .button{margin-left:auto}.detail-body{overflow:auto;padding:1rem 1.2rem}.detail-summary{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;font-size:.78rem;color:var(--muted)}.detail-message{margin:1rem 0;padding:.75rem;border-radius:.65rem;background:var(--panel-soft)}.detail-progress{padding:.8rem;border:1px solid var(--line);border-radius:.7rem}.detail-progress>div:first-child{display:flex;justify-content:space-between;gap:1rem;font-size:.8rem}.detail-progress p{font-size:.75rem;color:var(--muted)}.active-item-list,.file-results,.event-list{display:grid;gap:.5rem;margin-top:.7rem}.active-item-list article,.file-results article,.event-list article{display:grid;gap:.25rem;padding:.7rem;border:1px solid var(--line);border-radius:.65rem}.active-item-list article span,.active-item-list article small,.file-results article span,.file-results article small,.event-list article p,.event-list article small{color:var(--muted);font-size:.74rem}.result-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.5rem;margin-top:.8rem}.result-grid article{display:grid;gap:.3rem;padding:.65rem;border:1px solid var(--line);border-radius:.65rem}.result-grid small{color:var(--muted);text-transform:capitalize}.result-grid strong{overflow-wrap:anywhere;font-size:.78rem}.file-results h3{font-size:.85rem}.event-list article>div{display:flex;justify-content:space-between;gap:1rem;align-items:center}.event-list article p{margin:.25rem 0}.log-body{background:#09111d;color:#d9fbe7}.log-toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem}.log-body pre{max-height:55dvh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font: .74rem/1.6 ui-monospace,monospace}.modal-actions{display:flex;justify-content:flex-end;gap:.5rem;padding:.8rem 1rem;border-top:1px solid var(--line)}.confirm-backdrop{z-index:60}.confirm-card{width:min(28rem,100%);padding:1.2rem}.confirm-card h2{margin:0;font-size:1.05rem}.confirm-card p{color:var(--muted);font-size:.88rem;line-height:1.5}.confirm-card .modal-actions{padding:1rem 0 0;border-top:0}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@keyframes fade-in{from{opacity:0}to{opacity:1}}@keyframes modal-in{from{opacity:0;transform:translateY(8px) scale(.99)}to{opacity:1;transform:translateY(0) scale(1)}}
.activity-card{--surface-soft:var(--panel-soft)}
.command-line{margin:.5rem 0;overflow-wrap:anywhere;font: .72rem/1.55 ui-monospace,monospace;color:var(--ink)}
.command-output{max-height:12rem;overflow:auto;margin:.45rem 0;padding:.65rem;border-radius:.55rem;background:#09111d;color:#d9fbe7;white-space:pre-wrap;overflow-wrap:anywhere;font:.7rem/1.5 ui-monospace,monospace}
.raw-body{background:#09111d;color:#d9fbe7}.raw-body pre{max-height:55dvh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:.72rem/1.55 ui-monospace,monospace}
@media(max-width:800px){.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.activity-table-wrap{display:none}.activity-cards{display:grid;gap:.6rem;padding:.7rem}.activity-card{padding:.75rem;border:1px solid var(--line);border-radius:.75rem;background:var(--surface-soft)}.activity-card-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:.6rem}.activity-card-heading strong{overflow-wrap:anywhere}.activity-card p{font-size:.75rem}.activity-card-progress{overflow-wrap:anywhere}.job-monitor-header{flex-direction:column}.monitor-actions{justify-content:flex-start}.filter-count{margin-left:0}.result-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(prefers-reduced-motion:reduce){.modal-backdrop,.modal-card{animation:none}.mini-progress i{transition:none}}
</style>
