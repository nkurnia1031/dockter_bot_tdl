<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, put, remove } from '../lib/api';
import { session } from '../session';
import { normalizeTdlChatRef } from '../../../src/lib/chatRef';
import { normalizeRuntimeReadiness, profileOptionLabel, runtimeReadinessFor } from '../../../src/lib/profile-catalog';

type Job = Record<string, any> & { id: string; status: string; worker?: string; profile?: string; payload?: Record<string, any>; result?: Record<string, any> };
type Stage = Record<string, any> & { stage_job_id: string; worker: string; profile?: string; backend_job?: Job };
type RcloneEntry = { name: string; path: string; is_dir: boolean; size?: number; updated_at?: string };
type RcloneResponse = { path: string; breadcrumbs: string[]; items: RcloneEntry[]; total: number; limit: number; offset: number };
type QuickLimit = { worker: string; max_concurrent: number; active: number; queued: number };

const sourceItems = ref<Record<string, any>[]>([]);
const labels = ref<{ label: string }[]>([]);
const chatRef = ref('');
const url = ref('');
const startId = ref('1');
const overwriteStartId = ref(false);
const saveNumericSource = ref(false);
const label = ref('');
const selectedSource = ref('');
const targetProfile = ref('');
const targetWorker = ref('');
const message = ref('');
const submitting = ref(false);
const cooldown = ref(false);
const readiness = ref(normalizeRuntimeReadiness(null));
const profileCatalog = ref(session.profileCatalog);
const rclonePath = ref('');
const rcloneCreate = ref(false);
const rcloneBrowserPath = ref('');
const rcloneBrowser = ref<RcloneResponse>({ path: '', breadcrumbs: [], items: [], total: 0, limit: 100, offset: 0 });
const rclonePickerOpen = ref(false);
const rcloneLoading = ref(false);
const rcloneError = ref('');
const rcloneNewFolder = ref('');
const sourceLoading = ref(false);
const statsLoading = ref(false);
const allJobs = ref<Job[]>([]);
const quickLimits = ref<QuickLimit[]>([]);
const quickLimitDrafts = ref<Record<string, string>>({});
const quickLimitSaving = ref<Record<string, boolean>>({});
const quickLimitsLoading = ref(false);
const staging = ref<Stage[]>([]);
const stagingErrors = ref<{ worker: string; error: string }[]>([]);
const stagingLoading = ref(false);
const stagingRequested = ref(false);
const stageAction = ref<string | null>(null);
const filterProfile = ref('');
const filterWorker = ref('');
const filterStatus = ref('');
const lastStatsRefreshed = ref<Date | null>(null);
const lastStagingRefreshed = ref<Date | null>(null);
const lastLimitsRefreshed = ref<Date | null>(null);
const activeStatuses = ['queued', 'dispatched', 'running', 'paused'];
const terminalStatuses = ['failed', 'cancelled', 'succeeded'];
const enabledWorkers = computed(() => session.workers.filter((item) => item.enabled !== false));
const quickReadiness = computed(() => runtimeReadinessFor(readiness.value, targetProfile.value || null, targetWorker.value, 'quick_mode'));
const rcloneReadiness = computed(() => runtimeReadinessFor(readiness.value, null, targetWorker.value, 'rclone_storage'));
const activeJobs = computed(() => allJobs.value.filter((job) => activeStatuses.includes(job.status)));
const stats = computed(() => ({
  queued: allJobs.value.filter((job) => ['queued', 'dispatched'].includes(job.status)).length,
  running: allJobs.value.filter((job) => job.status === 'running').length,
  paused: allJobs.value.filter((job) => job.status === 'paused').length,
  failed: allJobs.value.filter((job) => job.status === 'failed').length,
  cancelled: allJobs.value.filter((job) => job.status === 'cancelled').length,
  succeeded: allJobs.value.filter((job) => job.status === 'succeeded').length
}));
const filteredStaging = computed(() => staging.value.filter((item) =>
  !item.scan_missing
  && (!filterProfile.value || item.profile === filterProfile.value || item.backend_job?.profile === filterProfile.value)
  && (!filterWorker.value || item.worker === filterWorker.value)
  && (!filterStatus.value || item.backend_job?.status === filterStatus.value)
));
const selectedQuickTarget = computed(() => rcloneCreate.value
  ? `Subfolder baru: ${rclonePath.value || '—'}`
  : rclonePath.value ? `Folder terpilih: ${rclonePath.value}` : 'Root terkonfigurasi: root rclone_destination');
const readinessLabel = computed(() => quickReadiness.value.status === 'ready' ? 'Quick Mode siap'
  : quickReadiness.value.status === 'not_ready' || quickReadiness.value.status === 'offline' ? 'Quick Mode belum siap'
    : quickReadiness.value.status === 'disabled' ? 'Worker nonaktif untuk job baru' : 'Quick Mode belum discan');
let cooldownTimer: ReturnType<typeof setTimeout> | undefined;
let rcloneGeneration = 0;
let sourceGeneration = 0;
let disposed = false;

function isNumeric(value: string) { return /^-?\d+$/.test(value.trim()); }
function formatClock(value: Date | null) { return value ? value.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'; }
function stageProfile(item: Stage) { return String(item.profile || item.backend_job?.profile || targetProfile.value || ''); }

function resumeAction(item: Stage): { phase: string; label: string } {
  if (item.orphan && !item.json_present && !item.actual_media_count && !item.archive_parts) return { phase: 'exporting', label: 'Import orphan' };
  if (item.archive_parts && item.thumbnail_present) return { phase: 'uploading', label: 'Upload' };
  if (item.json_present && item.expected_media_count && item.actual_media_count < item.expected_media_count) return { phase: 'downloading', label: 'Resume Download' };
  if (item.actual_media_count > 0 && !item.thumbnail_present) return { phase: 'thumbnailing', label: 'Thumbnail' };
  if (item.thumbnail_present && !item.archive_parts) return { phase: 'compressing', label: 'Compress' };
  return { phase: 'exporting', label: 'Re-Export' };
}

function activeJobForStage(item: Stage): Job | null {
  const match = activeJobs.value.find((job) => job.worker === item.worker && (
    String(job.payload?.quick_retry?.stage_job_id || job.result?.stage_job_id || job.id) === item.stage_job_id
    || (item.backend_job_id && job.id === item.backend_job_id)
  ));
  if (match) return match;
  return item.backend_job && activeStatuses.includes(item.backend_job.status) ? item.backend_job : null;
}

async function loadSources(profile = targetProfile.value) {
  const request = ++sourceGeneration;
  sourceLoading.value = true;
  try {
    const [sourceResponse, labelResponse] = await Promise.all([
      api<{ items?: Record<string, any>[] }>(profile ? `/sources?profile=${encodeURIComponent(profile)}` : '/sources'),
      api<{ items?: unknown[] }>('/labels')
    ]);
    if (disposed || request !== sourceGeneration) return;
    sourceItems.value = sourceResponse.items || [];
    labels.value = (labelResponse.items || []).filter((item): item is { label: string } => Boolean(item && typeof item === 'object' && typeof (item as { label?: unknown }).label === 'string'));
  } catch (cause) {
    if (request === sourceGeneration) message.value = cause instanceof Error ? cause.message : 'Source tidak dapat dimuat.';
  } finally { if (!disposed && request === sourceGeneration) sourceLoading.value = false; }
}

async function loadStats() {
  statsLoading.value = true;
  try {
    const response = await api<{ items?: Job[] }>('/jobs?limit=200&scope=global&kind=export&quick_mode=true&archived=false');
    allJobs.value = response.items || [];
    lastStatsRefreshed.value = new Date();
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Statistik Quick Mode tidak dapat dimuat.'; }
  finally { statsLoading.value = false; }
}

async function loadQuickLimits() {
  quickLimitsLoading.value = true;
  try {
    const response = await api<{ items?: QuickLimit[] }>('/quick-mode/limits');
    quickLimits.value = response.items || [];
    lastLimitsRefreshed.value = new Date();
    const drafts = { ...quickLimitDrafts.value };
    for (const item of quickLimits.value) if (drafts[item.worker] === undefined || !quickLimitSaving.value[item.worker]) drafts[item.worker] = String(item.max_concurrent);
    quickLimitDrafts.value = drafts;
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Batas Quick Mode tidak dapat dimuat.'; }
  finally { quickLimitsLoading.value = false; }
}

async function saveQuickLimit(workerName: string) {
  const value = Number(quickLimitDrafts.value[workerName]);
  if (!Number.isInteger(value) || value < 1 || value > 32) { message.value = 'Batas job per worker harus berupa angka 1 sampai 32.'; return; }
  quickLimitSaving.value = { ...quickLimitSaving.value, [workerName]: true };
  try {
    await put(`/quick-mode/limits/${encodeURIComponent(workerName)}`, { max_concurrent: value });
    message.value = `Batas worker ${workerName} disimpan.`;
    await Promise.all([loadQuickLimits(), loadStats()]);
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Batas Quick Mode gagal disimpan.'; }
  finally { const next = { ...quickLimitSaving.value }; delete next[workerName]; quickLimitSaving.value = next; }
}

async function loadStaging() {
  stagingRequested.value = true;
  stagingLoading.value = true;
  try {
    const response = await api<{ items?: Stage[]; errors?: { worker: string; error: string }[] }>('/quick-mode/staging');
    staging.value = response.items || [];
    stagingErrors.value = response.errors || [];
    lastStagingRefreshed.value = new Date();
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Scan staging Quick Mode gagal.'; }
  finally { stagingLoading.value = false; }
}

function stageSourcePayload() {
  const normalized = url.value.trim() ? null : normalizeTdlChatRef(chatRef.value);
  const source: { url?: string; chat_ref?: string; label?: string; start_id?: number; use_url_message_id?: boolean } = {
    ...(url.value.trim() ? { url: url.value.trim() } : normalized ? { chat_ref: normalized } : {}),
    ...(label.value.trim() ? { label: label.value.trim() } : {}),
    ...(overwriteStartId.value ? { start_id: Number(startId.value), use_url_message_id: true } : {})
  };
  return source;
}

async function recoverStage(item: Stage, resumePhase?: string) {
  const profile = stageProfile(item);
  const source = stageSourcePayload();
  if (!profile) { message.value = 'Pilih profile pada form Quick Mode sebelum mengimport folder ini.'; return; }
  if (!item.json_present && !item.actual_media_count && !item.archive_parts && !('url' in source) && !('chat_ref' in source)) {
    message.value = 'Folder ini tidak memiliki JSON. Isi URL atau chat ID untuk export ulang.';
    return;
  }
  const actionKey = `${item.worker}:${item.stage_job_id}`;
  stageAction.value = actionKey;
  try {
    await post('/quick-mode/recover', {
      worker: item.worker, stage_job_id: item.stage_job_id, profile,
      resume_phase: resumePhase,
      single_phase: Boolean(resumePhase && !['auto', 'exporting'].includes(resumePhase)),
      ...source
    });
    message.value = 'Folder Quick Mode dimasukkan kembali ke antrean.';
    await Promise.all([loadStaging(), loadStats()]);
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Recovery Quick Mode gagal.'; }
  finally { stageAction.value = null; }
}

async function cancelStage(item: Stage) {
  const jobId = item.backend_job_id || item.backend_job?.id || activeJobForStage(item)?.id;
  if (!jobId) return;
  const key = `${item.worker}:${item.stage_job_id}`;
  stageAction.value = key;
  try {
    await post(`/jobs/${encodeURIComponent(jobId)}/cancel`);
    message.value = 'Permintaan cancel dikirim ke worker.';
    await Promise.all([loadStats(), loadStaging()]);
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Cancel Quick Mode gagal.'; }
  finally { stageAction.value = null; }
}

async function deleteStage(item: Stage) {
  if (activeJobForStage(item)) { message.value = 'Folder staging tidak bisa dihapus selama job masih aktif atau mengantre.'; return; }
  const folderName = String(item.folder_name || item.stage_job_id);
  if (!window.confirm(`Hapus folder staging Quick Mode "${folderName}" di worker ${item.worker}?\n\nSemua isinya, termasuk quickmode.json, worker.log, media, archive, dan sesi .tdl, akan dihapus permanen. Riwayat job tetap disimpan.`)) return;
  const key = `${item.worker}:${item.stage_job_id}`;
  stageAction.value = key;
  try {
    const result = await remove<{ deleted?: boolean }>(`/quick-mode/staging/${encodeURIComponent(item.worker)}/${encodeURIComponent(item.stage_job_id)}`);
    message.value = result.deleted ? `Folder staging "${folderName}" berhasil dihapus.` : `Folder staging "${folderName}" sudah tidak ada.`;
    await loadStaging();
  } catch (cause) { message.value = cause instanceof Error ? cause.message : 'Folder staging Quick Mode gagal dihapus.'; }
  finally { stageAction.value = null; }
}

function chooseSource(value: string) {
  selectedSource.value = value;
  overwriteStartId.value = false;
  url.value = '';
  const found = sourceItems.value.find((item) => item.chat_ref === value);
  if (found) {
    chatRef.value = found.chat_ref;
    startId.value = String(Number(found.last_id || 0) + 1);
    label.value = found.label || '';
    saveNumericSource.value = isNumeric(found.chat_ref);
  } else { chatRef.value = ''; startId.value = '1'; label.value = ''; saveNumericSource.value = false; }
}

function updateChatRef(value: string) {
  chatRef.value = value;
  url.value = '';
  if (selectedSource.value && normalizeTdlChatRef(selectedSource.value) !== normalizeTdlChatRef(value)) {
    selectedSource.value = ''; overwriteStartId.value = false; startId.value = '1'; saveNumericSource.value = false;
  }
}
function updateUrl(value: string) { url.value = value; if (value.trim()) chatRef.value = ''; }
function resetForm() {
  chatRef.value = ''; url.value = ''; startId.value = '1'; overwriteStartId.value = false;
  saveNumericSource.value = false; label.value = ''; selectedSource.value = ''; message.value = '';
  if (cooldownTimer) clearTimeout(cooldownTimer);
  cooldownTimer = undefined; cooldown.value = false;
}
function beginCooldown() {
  if (cooldownTimer) clearTimeout(cooldownTimer);
  cooldown.value = true;
  cooldownTimer = setTimeout(() => { cooldown.value = false; cooldownTimer = undefined; }, 500);
}

function validRemotePath(path: string) {
  return !path.startsWith('/') && path.split('/').every((part) => !part || (part !== '.' && part !== '..' && !/[\\:\u0000-\u001f]/.test(part)));
}
async function loadRcloneFolder(path: string) {
  if (!targetWorker.value) { rcloneError.value = 'Pilih worker untuk membaca folder rclone.'; return; }
  if (!validRemotePath(path)) { rcloneError.value = 'Path folder rclone tidak valid.'; return; }
  const request = ++rcloneGeneration;
  rcloneBrowserPath.value = path;
  rcloneLoading.value = true;
  rcloneError.value = '';
  try {
    const params = new URLSearchParams({ worker: targetWorker.value, path, limit: '100', offset: '0', sort: 'name', order: 'asc' });
    const result = await api<RcloneResponse>(`/storage/rclone/browser?${params}`);
    if (request === rcloneGeneration && targetWorker.value === params.get('worker')) rcloneBrowser.value = result;
  } catch (cause) { if (request === rcloneGeneration) rcloneError.value = cause instanceof Error ? cause.message : 'Folder rclone tidak dapat dimuat.'; }
  finally { if (request === rcloneGeneration) rcloneLoading.value = false; }
}
function toggleRclonePicker() {
  rclonePickerOpen.value = !rclonePickerOpen.value;
  if (rclonePickerOpen.value) void loadRcloneFolder(rcloneBrowserPath.value);
}
function chooseRcloneFolder(path: string) {
  if (!validRemotePath(path)) return;
  rclonePath.value = path;
  rcloneCreate.value = false;
  rclonePickerOpen.value = false;
  rcloneNewFolder.value = '';
}
function chooseRcloneNewFolder() {
  const name = rcloneNewFolder.value.trim();
  if (!name || name === '.' || name === '..' || /[\\/:\u0000-\u001f]/.test(name)) { rcloneError.value = 'Nama subfolder tidak valid.'; return; }
  rclonePath.value = [rcloneBrowserPath.value, name].filter(Boolean).join('/');
  rcloneCreate.value = true;
  rclonePickerOpen.value = false;
  rcloneError.value = '';
}

async function submit() {
  if (submitting.value || cooldown.value) return;
  const normalizedChatRef = url.value.trim() ? null : normalizeTdlChatRef(chatRef.value);
  if (!url.value.trim() && !normalizedChatRef) { message.value = 'Masukkan @username, username, ID numeric, link t.me publik, nomor telepon internasional, atau URL export.'; return; }
  const manualStartId = Number(startId.value);
  if (overwriteStartId.value && (!Number.isInteger(manualStartId) || manualStartId < 1)) { message.value = 'Start ID manual harus berupa angka minimal 1.'; return; }
  if (!targetProfile.value || !targetWorker.value) { message.value = 'Pilih profile dan worker untuk job Quick Mode.'; return; }
  submitting.value = true;
  message.value = '';
  const payload: Record<string, unknown> = {
    ...(url.value.trim() ? { url: url.value.trim() } : { chat_ref: normalizedChatRef }),
    label: label.value || undefined, use_url_message_id: overwriteStartId.value,
    profile: targetProfile.value, worker: targetWorker.value, quick_mode: true,
    quick_rclone_path: rclonePath.value, quick_rclone_create: rcloneCreate.value
  };
  if (normalizedChatRef && isNumeric(normalizedChatRef)) payload.save_source = saveNumericSource.value;
  if (overwriteStartId.value) payload.start_id = manualStartId;
  try {
    await post('/exports', payload);
    window.dispatchEvent(new CustomEvent('tme3:data-mutated', { detail: { path: '/exports' } }));
    beginCooldown();
    message.value = 'Quick Mode berhasil masuk antrean.';
    await Promise.all([loadStats(), loadQuickLimits()]);
  } catch (cause) {
    message.value = cause instanceof Error ? cause.message : 'Quick Mode gagal dibuat.';
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldownTimer = undefined; cooldown.value = false;
  } finally { submitting.value = false; }
}

async function refreshReadiness() {
  try {
    const result = await api<{ profiles?: unknown[]; runtime_readiness?: unknown }>('/profiles/local');
    readiness.value = normalizeRuntimeReadiness(result.runtime_readiness);
    if (Array.isArray(result.profiles)) {
      profileCatalog.value = result.profiles as typeof session.profileCatalog;
      session.profileCatalog = profileCatalog.value;
    }
  } catch { /* Quick Mode submit is not gated by a stale scan. */ }
}
function onJobFinished() { void Promise.all([loadStats(), loadQuickLimits(), loadStaging(), refreshReadiness()]); }
watch(targetProfile, (next, previous) => { if (next && next !== previous) { sourceItems.value = []; selectedSource.value = ''; void loadSources(next); } });
watch(targetWorker, () => {
  rcloneGeneration++;
  rclonePath.value = ''; rcloneCreate.value = false; rcloneBrowserPath.value = '';
  rcloneBrowser.value = { path: '', breadcrumbs: [], items: [], total: 0, limit: 100, offset: 0 };
  rcloneError.value = '';
  if (rclonePickerOpen.value) void loadRcloneFolder('');
});
onMounted(() => {
  targetProfile.value = session.selectedTargetProfile || session.current.actor?.profile || session.current.profiles[0] || '';
  targetWorker.value = enabledWorkers.value.find((item) => item.name === session.current.actor?.worker_route)?.name || enabledWorkers.value[0]?.name || '';
  void Promise.all([loadSources(), loadStats(), loadQuickLimits(), refreshReadiness()]);
  window.addEventListener('tme3:job-finished', onJobFinished);
});
onUnmounted(() => { disposed = true; if (cooldownTimer) clearTimeout(cooldownTimer); window.removeEventListener('tme3:job-finished', onJobFinished); });
</script>

<template>
  <main class="page-stack quick-page">
    <header class="page-heading"><div><p class="eyebrow">PEMROSESAN · QUICK MODE MANAGER</p><h1>Pantau dan ulangi Quick Mode</h1><p class="muted">Satu antrean global untuk seluruh profile-worker yang dapat Anda akses.</p></div></header>

    <section class="panel limits-panel">
      <header class="panel-heading"><div><p class="eyebrow">WORKER CONCURRENCY</p><h2>Batas job Quick Mode bersamaan</h2><p class="muted">Batas berlaku untuk semua profile pada worker yang sama. Job resume masuk antrean FIFO.</p><small v-if="lastLimitsRefreshed" class="muted">Terakhir diperbarui: {{ formatClock(lastLimitsRefreshed) }}</small></div><button class="button button-secondary button-small" type="button" aria-label="Refresh batas Quick Mode" :disabled="quickLimitsLoading" @click="loadQuickLimits">{{ quickLimitsLoading ? 'Memuat…' : '↻ Refresh batas' }}</button></header>
      <div v-if="quickLimits.length" class="limit-grid"><article v-for="item in quickLimits" :key="item.worker" class="limit-row"><div><strong>{{ item.worker }}</strong><small class="muted">{{ item.active }} aktif dari batas {{ item.max_concurrent }} · {{ item.queued }} menunggu</small></div><div class="limit-control"><label>Maksimum aktif<input class="field" type="number" min="1" max="32" step="1" :value="quickLimitDrafts[item.worker] ?? item.max_concurrent" @input="quickLimitDrafts[item.worker] = ($event.target as HTMLInputElement).value"></label><button class="button button-secondary button-small" type="button" :disabled="quickLimitSaving[item.worker]" @click="saveQuickLimit(item.worker)">{{ quickLimitSaving[item.worker] ? 'Menyimpan…' : 'Simpan' }}</button></div></article></div>
      <p v-else class="empty-state">Belum ada worker yang terdaftar.</p>
    </section>

    <section class="stats-grid" aria-label="Statistik Quick Mode"><article v-for="(value, key) in stats" :key="key" class="panel stat-card"><small>{{ key }}</small><strong>{{ value }}</strong></article></section>

    <section class="panel quick-form-panel">
      <header class="panel-heading"><div><p class="eyebrow">JOB BARU</p><h2>Tambah Quick Mode</h2><p class="muted">Form ini selalu mengirim job dengan Quick Mode aktif.</p></div><span class="status-pill status-ready">Quick Mode aktif</span></header>
      <div class="quick-form">
        <div class="target-grid">
          <label>Profile target<select v-model="targetProfile" class="field" aria-label="Profile target"><option value="" disabled>Pilih profile</option><option v-for="profile in session.current.profiles" :key="profile" :value="profile">{{ profile }}</option></select></label>
          <label>Worker target<select v-model="targetWorker" class="field" aria-label="Worker target"><option value="" disabled>Pilih worker</option><option v-for="item in session.workers" :key="item.name" :value="item.name" :disabled="item.enabled === false">{{ item.name }}{{ item.enabled === false ? ' (nonaktif)' : '' }}</option></select></label>
        </div>
        <p class="notice readiness-notice" :class="quickReadiness.status === 'ready' ? 'notice-success' : 'notice-warning'" role="status"><strong>Scan terakhir: {{ readinessLabel }}</strong><span>{{ targetProfile || 'profile belum dipilih' }} · {{ targetWorker || 'worker belum dipilih' }}</span><small v-if="quickReadiness.reason_code">{{ quickReadiness.reason_code }}</small><small>Status scan hanya informasi; command aktual menentukan hasil job.</small></p>

        <section class="rclone-target" aria-label="Tujuan rclone Quick Mode"><div class="target-summary"><div><strong>Folder tujuan rclone</strong><p class="muted">{{ selectedQuickTarget }}</p><small v-if="rcloneReadiness.status !== 'ready'" class="muted">Status scan rclone: {{ rcloneReadiness.reason_code || rcloneReadiness.status }}. Akses diuji oleh browser worker.</small></div><button class="button button-secondary" type="button" :disabled="!targetWorker" @click="toggleRclonePicker">{{ rclonePickerOpen ? 'Tutup pemilih' : 'Pilih folder' }}</button></div>
          <div v-if="rclonePickerOpen" class="rclone-browser"><nav class="rclone-crumbs" aria-label="Folder rclone"><button class="button button-secondary button-small" type="button" @click="loadRcloneFolder('')">Root</button><template v-for="(crumb, index) in rcloneBrowserPath.split('/').filter(Boolean)" :key="`${crumb}:${index}`"><span aria-hidden="true">›</span><button class="button button-secondary button-small" type="button" @click="loadRcloneFolder(rcloneBrowserPath.split('/').filter(Boolean).slice(0, index + 1).join('/'))">{{ crumb }}</button></template></nav><div class="rclone-select-actions"><button class="button button-small" type="button" @click="chooseRcloneFolder(rcloneBrowserPath)">Gunakan folder ini</button><label>Nama subfolder baru<input v-model="rcloneNewFolder" class="field" placeholder="Nama subfolder baru"></label><button class="button button-secondary button-small" type="button" @click="chooseRcloneNewFolder">Buat tujuan baru</button></div><p v-if="rcloneError" class="notice notice-error" role="alert">{{ rcloneError }}</p><div v-if="rcloneLoading" class="empty-state" role="status">Memuat folder…</div><div v-else class="remote-folder-list"><article v-for="entry in rcloneBrowser.items.filter((item) => item.is_dir)" :key="entry.path"><button class="folder-open" type="button" @click="loadRcloneFolder(entry.path)">📁 {{ entry.name }}</button><button class="button button-secondary button-small" type="button" @click="chooseRcloneFolder(entry.path)">Pilih</button></article><p v-if="!rcloneBrowser.items.some((item) => item.is_dir)" class="empty-state">Tidak ada subfolder di lokasi ini.</p></div><small class="muted">Subfolder baru dibuat saat job mulai. Jika nama tujuan sudah ada, job berhenti sebelum upload.</small></div>
        </section>

        <div class="input-grid"><label>Pilih source tersimpan<select class="field" :value="selectedSource" :disabled="sourceLoading" @change="chooseSource(($event.target as HTMLSelectElement).value)"><option value="">Source baru…</option><option v-for="source in sourceItems" :key="source.chat_ref" :value="source.chat_ref">{{ source.label ? `${source.label} — ` : '' }}{{ source.chat_ref }} (berikutnya: {{ Number(source.last_id) + 1 }})</option></select></label><label>Referensi chat<input class="field" :value="chatRef" placeholder="@iyear · 123456789 · https://t.me/iyear · +1 123456789" @input="updateChatRef(($event.target as HTMLInputElement).value)"></label><label class="wide-field">URL Telegram manual <span class="muted">(opsional, mengesampingkan referensi chat)</span><input class="field" :value="url" placeholder="https://t.me/c/..." @input="updateUrl(($event.target as HTMLInputElement).value)"></label><label>Start message ID<input v-model="startId" class="field" type="number" min="1" :disabled="!overwriteStartId"></label><label>Label<input v-model="label" class="field" list="quick-mode-label-options" placeholder="Opsional"><datalist id="quick-mode-label-options"><option v-for="item in labels" :key="item.label" :value="item.label"></option></datalist></label></div>
        <label class="switch-option"><input v-model="overwriteStartId" type="checkbox" role="switch"><span><strong>Overwrite Start ID</strong><small>Gunakan Start ID manual untuk job ini.</small></span></label>
        <label v-if="isNumeric(chatRef)" class="switch-option"><input v-model="saveNumericSource" type="checkbox" role="switch"><span><strong>Simpan source numeric</strong><small>Simpan Last ID numeric source untuk penggunaan berikutnya.</small></span></label>
        <div v-if="labels.length" class="label-chips"><button v-for="item in labels" :key="item.label" class="chip-button" type="button" @click="label = item.label; message = ''">{{ item.label }}</button></div>
        <p v-if="message" class="notice" :class="message.includes('berhasil') ? 'notice-success' : 'notice-error'" role="status">{{ message }}</p>
        <div class="form-actions"><button class="button button-secondary" type="button" :disabled="submitting" @click="resetForm">Reset form</button><button class="button" type="button" :disabled="submitting || cooldown" @click="submit">{{ submitting ? 'Mengirim…' : cooldown ? 'Tunggu sebentar…' : 'Tambah Quick Mode' }}</button></div>
      </div>
    </section>

    <JobMonitor kind="export" title="Quick Mode berjalan dan antri" scope="global" :profile="filterProfile" :worker="filterWorker" :quick-mode="true" view="active" />

    <section class="panel filter-panel"><header class="panel-heading"><div><p class="eyebrow">HISTORY FILTER</p><h2>Filter history Quick Mode</h2></div><div class="inline-actions"><small v-if="lastStatsRefreshed" class="muted">Terakhir diperbarui: {{ formatClock(lastStatsRefreshed) }}</small><button class="button button-secondary button-small" type="button" aria-label="Refresh statistik Quick Mode" :disabled="statsLoading" @click="loadStats">{{ statsLoading ? 'Memuat…' : 'Refresh statistik' }}</button></div></header><div class="filter-grid"><label>Profile<select v-model="filterProfile" class="field"><option value="">Semua profile</option><option v-for="item in profileCatalog" :key="item.name" :value="item.name">{{ profileOptionLabel(item) }}</option></select></label><label>Worker<select v-model="filterWorker" class="field"><option value="">Semua worker</option><option v-for="item in session.workers" :key="item.name" :value="item.name">{{ item.name }}</option></select></label><label>Status<select v-model="filterStatus" class="field"><option value="">Semua status</option><option v-for="item in terminalStatuses" :key="item" :value="item">{{ item }}</option></select></label></div></section>

    <section class="panel staging-panel"><header class="panel-heading"><div><p class="eyebrow">PHYSICAL STAGING</p><h2>Folder Quick Mode di worker</h2><p class="muted">Scan workspace worker secara manual, termasuk folder orphan setelah restart worker.</p></div><div class="inline-actions"><small v-if="lastStagingRefreshed" class="muted">Terakhir discan: {{ formatClock(lastStagingRefreshed) }}</small><button class="button button-secondary button-small" type="button" aria-label="Refresh scan" :disabled="stagingLoading" @click="loadStaging">{{ stagingLoading ? 'Memindai…' : 'Refresh scan' }}</button></div></header>
      <div v-if="stagingErrors.length" class="staging-errors"><p v-for="item in stagingErrors" :key="item.worker" class="notice notice-warning">Worker {{ item.worker }} tidak dapat discan: {{ item.error }}</p></div>
      <p v-if="!stagingRequested && !stagingLoading" class="empty-state">Tekan <strong>Refresh scan</strong> untuk memuat folder staging.</p><p v-else-if="stagingRequested && !filteredStaging.length && !stagingLoading" class="empty-state">Belum ada folder staging Quick Mode.</p>
      <div class="stage-list"><article v-for="item in filteredStaging" :key="`${item.worker}:${item.stage_job_id}`" class="stage-card"><header><div><div class="stage-title"><small v-if="item.backend_job_id || item.backend_job?.id" class="mono">#{{ String(item.backend_job_id || item.backend_job?.id).slice(0, 8) }}</small><strong>{{ item.folder_name || item.stage_job_id }}</strong><span v-if="item.orphan" class="status-pill status-warning">Orphan</span><span class="status-pill status-neutral">{{ item.phase }}</span><span v-if="item.backend_job" class="status-pill" :class="`status-${item.backend_job.status}`">{{ item.backend_job.status }}</span></div><p class="muted stage-path">{{ item.worker }} · {{ stageProfile(item) || 'profile belum dipilih' }} · {{ item.staging_path }}</p></div><div class="stage-actions"><template v-if="activeJobForStage(item)"><span class="status-pill status-running">Sedang processing (#{{ activeJobForStage(item)?.id.slice(0, 8) }})</span><button class="button button-danger button-small" type="button" :disabled="stageAction === `${item.worker}:${item.stage_job_id}`" @click="cancelStage(item)">Cancel</button></template><template v-else><button class="button button-secondary button-small" type="button" :disabled="stageAction === `${item.worker}:${item.stage_job_id}`" @click="recoverStage(item, resumeAction(item).phase)">{{ resumeAction(item).label }}</button><button class="button button-danger button-small" type="button" aria-label="Hapus staging" :disabled="stageAction === `${item.worker}:${item.stage_job_id}`" @click="deleteStage(item)">Hapus</button></template></div></header>
        <div class="stage-facts"><span :class="item.json_present ? 'fact-ready' : ''">JSON {{ item.json_present ? 'ada' : 'tidak ada' }}</span><span :class="item.actual_media_count ? 'fact-ready' : ''">Media {{ item.actual_media_count }}/{{ item.expected_media_count || '?' }}</span><span :class="item.thumbnail_present ? 'fact-ready' : ''">PNG {{ item.thumbnail_present ? 'ada' : 'belum' }}</span><span :class="item.archive_parts ? 'fact-ready' : ''">Archive {{ item.archive_parts }}</span><span :class="item.tdl_export_present && item.tdl_download_present ? 'fact-ready' : ''">.tdl {{ item.tdl_export_present ? 'E' : '—' }} / {{ item.tdl_download_present ? 'D' : '—' }}</span><span :class="item.worker_log_present ? 'fact-ready' : ''">Log {{ item.worker_log_present ? `${Math.ceil((item.worker_log_bytes || 0) / 1024)} KB` : 'belum' }}</span></div>
        <div v-if="item.cleanup_verification" class="stage-verification" :class="item.cleanup_verification.status === 'verified' ? 'fact-ready' : 'fact-warning'"><strong>Crosscheck upload: {{ item.cleanup_verification.status }}</strong><span>Telegram {{ item.cleanup_verification.channel_found ?? 0 }}/{{ item.cleanup_verification.channel_expected ?? 0 }} · Google Drive {{ item.cleanup_verification.drive_found ?? 0 }}/{{ item.cleanup_verification.drive_expected ?? 0 }}</span><small v-if="item.cleanup_verification.reason">{{ item.cleanup_verification.reason }}</small></div>
        <p v-if="item.staging_cleaned" class="notice notice-success">Staging dibersihkan setelah archive dan thumbnail terverifikasi.</p><p v-if="item.last_error" class="notice notice-error">{{ item.last_error }}</p><small v-if="item.backend_job_id || item.backend_job?.id" class="muted">Job backend: {{ item.backend_job_id || item.backend_job?.id }} · storage: {{ item.storage_folder || '—' }}</small>
      </article></div>
    </section>

    <JobMonitor kind="export" title="History Quick Mode lintas worker" scope="global" :profile="filterProfile" :worker="filterWorker" :status="filterStatus" :quick-mode="true" retryable view="history" />
  </main>
</template>

<style scoped>
.limits-panel,.quick-form-panel,.filter-panel,.staging-panel{min-width:0}.limit-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem;padding:.75rem}.limit-row{display:flex;align-items:end;justify-content:space-between;gap:.7rem;padding:.65rem;border:1px solid var(--line);border-radius:9px;background:var(--panel-soft)}.limit-row>div:first-child{display:grid;gap:.2rem;font-size:.68rem}.limit-row small{font-size:.6rem}.limit-control{display:flex;align-items:end;gap:.45rem}.limit-control label,.target-grid label,.input-grid label,.filter-grid label{display:grid;gap:.35rem;font-size:.65rem;font-weight:750}.limit-control input{width:5rem}.stats-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:.55rem}.stat-card{display:grid;gap:.2rem;padding:.7rem .8rem}.stat-card small{text-transform:uppercase;color:var(--muted);font-size:.58rem;font-weight:800}.stat-card strong{font-size:1.3rem}.quick-form{display:grid;gap:.7rem;padding:.85rem}.target-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem}.readiness-notice{display:flex;flex-wrap:wrap;gap:.35rem .7rem}.readiness-notice small{width:100%}.notice-success{color:var(--success);border-color:color-mix(in srgb,var(--success) 35%,var(--line))}.notice-warning{color:var(--warning)}.rclone-target{display:grid;gap:.65rem;padding:.7rem;border:1px solid var(--line);border-radius:10px;background:var(--panel-soft)}.target-summary{display:flex;align-items:center;justify-content:space-between;gap:.7rem}.target-summary>div{display:grid;gap:.2rem;font-size:.68rem}.target-summary p,.target-summary small{margin:0;font-size:.6rem}.rclone-browser{display:grid;gap:.55rem;padding:.65rem;border:1px solid var(--line);border-radius:8px;background:var(--panel)}.rclone-crumbs,.rclone-select-actions{display:flex;align-items:end;flex-wrap:wrap;gap:.4rem}.rclone-select-actions label{display:grid;flex:1;min-width:12rem;gap:.3rem;font-size:.62rem;font-weight:700}.remote-folder-list{max-height:14rem;overflow:auto;border:1px solid var(--line);border-radius:8px}.remote-folder-list article{display:flex;justify-content:space-between;gap:.5rem;padding:.4rem .55rem;border-bottom:1px solid var(--line)}.folder-open{flex:1;min-width:0;text-align:left;font-size:.7rem;font-weight:700}.input-grid,.filter-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem}.wide-field{grid-column:1/-1}.switch-option{display:flex;align-items:flex-start;gap:.5rem;padding:.6rem .7rem;border:1px solid var(--line);border-radius:9px;background:var(--panel-soft)}.switch-option span{display:grid;gap:.18rem;font-size:.68rem}.switch-option small{color:var(--muted);font-size:.6rem;font-weight:400}.label-chips,.inline-actions,.form-actions,.stage-actions{display:flex;align-items:center;flex-wrap:wrap;gap:.4rem}.chip-button{border:1px solid var(--line);border-radius:99px;padding:.25rem .55rem;font-size:.62rem;font-weight:700}.form-actions{justify-content:flex-end}.filter-grid{padding:.7rem}.inline-actions{justify-content:flex-end}.empty-state{padding:1.2rem;text-align:center;color:var(--muted);font-size:.68rem}.staging-errors{display:grid;gap:.4rem;padding:.7rem .75rem 0}.staging-errors p{margin:0}.stage-list{display:grid;gap:.6rem;padding:.75rem}.stage-card{display:grid;gap:.5rem;padding:.7rem;border:1px solid var(--line);border-radius:10px;background:var(--panel-soft)}.stage-card header{display:flex;justify-content:space-between;align-items:flex-start;gap:.65rem}.stage-title{display:flex;align-items:center;flex-wrap:wrap;gap:.35rem;font-size:.68rem}.stage-path{margin:.25rem 0 0;overflow-wrap:anywhere;font-size:.59rem}.stage-actions{justify-content:flex-end}.stage-facts{display:flex;flex-wrap:wrap;gap:.3rem}.stage-facts span,.stage-verification{padding:.25rem .45rem;border:1px solid var(--line);border-radius:99px;font-size:.58rem;font-weight:700;color:var(--muted)}.stage-facts .fact-ready,.stage-verification.fact-ready{color:var(--success);border-color:color-mix(in srgb,var(--success) 35%,var(--line))}.stage-verification{display:grid;gap:.25rem;border-radius:8px}.fact-warning{color:var(--warning)}.mono{font-family:monospace;color:var(--muted)}.stage-card>.notice{margin:0;font-size:.62rem}
@media(max-width:950px){.stats-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.limit-grid{grid-template-columns:1fr}}
@media(max-width:650px){.target-grid,.input-grid,.filter-grid{grid-template-columns:1fr}.wide-field{grid-column:auto}.stage-card header{flex-direction:column}.stage-actions{justify-content:flex-start}.inline-actions{justify-content:flex-start}.limit-row{align-items:flex-start;flex-direction:column}.limit-control{width:100%}}
</style>
