<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, remove } from '../lib/api';
import { session } from '../session';
import { normalizeTdlChatRef } from '../../../src/lib/chatRef';
import { normalizeRuntimeReadiness, runtimeReadinessFor } from '../../../src/lib/profile-catalog';

type Source = { chat_ref: string; label?: string; last_id?: number };
type Label = { label: string };
type ExportJob = { id: string; status: string; progress?: Record<string, any>; result?: { value?: Record<string, any> }; error?: { message?: string } | null };
type ExportNotice = { job: ExportJob };

const sources = ref<Source[]>([]);
const labels = ref<Label[]>([]);
const chatRef = ref('');
const startId = ref('1');
const overwriteStartId = ref(false);
const quickMode = ref(false);
const saveNumericSource = ref(false);
const label = ref('');
const selected = ref('');
const message = ref('');
const submitting = ref(false);
const exportCooldown = ref(false);
const notices = ref<ExportNotice[]>([]);
const targetProfile = ref('');
const targetWorker = ref('');
const readiness = ref(normalizeRuntimeReadiness(null));
const loading = ref(false);
const sourcesError = ref('');
const activeStatuses = ['queued', 'dispatched', 'running'];
const activeNotice = computed(() => notices.value.some((item) => activeStatuses.includes(item.job.status)));
const readinessRuntime = computed(() => quickMode.value ? 'quick_mode' : 'export');
const readinessResult = computed(() => runtimeReadinessFor(readiness.value, targetProfile.value || null, targetWorker.value, readinessRuntime.value));
const readinessLabel = computed(() => readinessResult.value.status === 'ready'
  ? `Scan terakhir: ${quickMode.value ? 'Quick Mode' : 'Export'} siap`
  : readinessResult.value.status === 'not_ready' || readinessResult.value.status === 'offline'
    ? `Scan terakhir: ${quickMode.value ? 'Quick Mode' : 'Export'} belum siap`
    : readinessResult.value.status === 'disabled' ? 'Worker nonaktif untuk job baru' : 'Belum pernah di-scan');
const workers = computed(() => session.workers.filter((item) => item.enabled !== false));
const isNumeric = (value: string) => /^-?\d+$/.test(value.trim());
let sourceGeneration = 0;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let cooldownTimer: ReturnType<typeof setTimeout> | undefined;
let mounted = false;

function isExportJob(value: unknown): value is ExportJob {
  if (!value || typeof value !== 'object') return false;
  const job = value as Partial<ExportJob>;
  return typeof job.id === 'string' && Boolean(job.id) && typeof job.status === 'string';
}

function persistNotices() {
  try { sessionStorage.setItem('tme3-export-notices', JSON.stringify(notices.value.map(({ job }) => job.id))); } catch { /* Session storage may be unavailable. */ }
}

function remember(job: ExportJob) {
  const existing = notices.value.find((item) => item.job.id === job.id);
  if (existing) existing.job = job;
  else notices.value = [{ job }, ...notices.value].slice(0, 4);
  persistNotices();
}

function dismiss(jobId: string) {
  notices.value = notices.value.filter(({ job }) => job.id !== jobId);
  persistNotices();
  schedulePoll();
}

function resultValue(job: ExportJob) { return job.result?.value || {}; }
function completionText(job: ExportJob) {
  const value = resultValue(job);
  const messages = value.message_count ?? value.exported_count ?? 0;
  if (value.artifact_deleted) return `${messages} pesan · 0 media · JSON dihapus otomatis`;
  const mediaText = typeof value.media_count === 'number' ? `${value.media_count} media` : value.has_media ? 'media tersedia' : '0 media';
  const counts = [typeof value.photo_count === 'number' ? `${value.photo_count} foto` : '', typeof value.video_count === 'number' ? `${value.video_count} video` : ''].filter(Boolean);
  return `${messages} pesan · ${mediaText}${counts.length ? ` · ${counts.join(' · ')}` : ''}`;
}
function quickCompletionDetails(value: Record<string, any>) {
  if (!value.quick_mode) return '';
  const parts = ['Quick Mode'];
  if (Array.isArray(value.archive_names) && value.archive_names.length) parts.push(`${value.archive_names.length} arsip`);
  if (value.thumbnail_name) parts.push(`thumbnail ${value.thumbnail_name}`);
  if (value.thumbnail_uploaded_as_photo) parts.push('thumbnail sebagai foto');
  if (value.storage_folder) parts.push(String(value.storage_folder));
  if (value.rclone_uploaded_count) parts.push(`${value.rclone_uploaded_count} arsip ke ${value.rclone_destination || 'Google Drive'}`);
  return parts.join(' / ');
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer);
  if (!mounted || !activeNotice.value || document.visibilityState !== 'visible') return;
  pollTimer = setTimeout(() => { void pollNotices(); }, 1000);
}

async function pollNotices() {
  const active = notices.value.filter(({ job }) => activeStatuses.includes(job.status));
  if (!active.length) return;
  const updated = await Promise.all(active.map(async ({ job }) => {
    try {
      const current = await api<unknown>(`/jobs/${encodeURIComponent(job.id)}`);
      return isExportJob(current) ? current : job;
    } catch { return job; }
  }));
  let finished = false;
  for (const job of updated) {
    const notice = notices.value.find((item) => item.job.id === job.id);
    if (!notice) continue;
    if (activeStatuses.includes(notice.job.status) && !activeStatuses.includes(job.status)) finished = true;
    notice.job = job;
  }
  persistNotices();
  if (finished) {
    await Promise.all([loadSources(), refreshReadiness()]);
  }
  schedulePoll();
}

async function loadSources(profile = targetProfile.value) {
  const request = ++sourceGeneration;
  loading.value = true;
  sourcesError.value = '';
  try {
    const sourcePath = profile ? `/sources?profile=${encodeURIComponent(profile)}` : '/sources';
    const [sourceResult, labelResult] = await Promise.all([
      api<{ items?: Source[] }>(sourcePath),
      api<{ items?: unknown[] }>('/labels')
    ]);
    if (request !== sourceGeneration) return;
    sources.value = sourceResult.items || [];
    labels.value = (labelResult.items || []).filter((item): item is Label => Boolean(item && typeof item === 'object' && typeof (item as Label).label === 'string'));
  } catch (cause) {
    if (request === sourceGeneration) sourcesError.value = cause instanceof Error ? cause.message : 'Daftar source export gagal dimuat.';
  } finally {
    if (request === sourceGeneration) loading.value = false;
  }
}

async function refreshReadiness() {
  try {
    const response = await api<{ runtime_readiness?: unknown }>('/profiles/local');
    readiness.value = normalizeRuntimeReadiness(response.runtime_readiness);
  } catch { /* Readiness is informational and does not block an export. */ }
}

function chooseSource(value: string) {
  selected.value = value;
  overwriteStartId.value = false;
  const source = sources.value.find((item) => item.chat_ref === value);
  if (source) {
    chatRef.value = source.chat_ref;
    startId.value = String(Number(source.last_id || 0) + 1);
    label.value = source.label || '';
    saveNumericSource.value = isNumeric(source.chat_ref);
  } else {
    chatRef.value = '';
    startId.value = '1';
    label.value = '';
    saveNumericSource.value = false;
  }
}

function updateChatRef(value: string) {
  chatRef.value = value;
  if (selected.value && normalizeTdlChatRef(selected.value) !== normalizeTdlChatRef(value)) {
    selected.value = '';
    overwriteStartId.value = false;
    startId.value = '1';
    saveNumericSource.value = false;
  }
}

function resetForm() {
  chatRef.value = '';
  startId.value = '1';
  overwriteStartId.value = false;
  quickMode.value = false;
  saveNumericSource.value = false;
  label.value = '';
  selected.value = '';
  message.value = '';
  if (cooldownTimer) clearTimeout(cooldownTimer);
  cooldownTimer = undefined;
  exportCooldown.value = false;
}

async function submit() {
  if (submitting.value || exportCooldown.value) return;
  message.value = '';
  const normalizedChatRef = normalizeTdlChatRef(chatRef.value);
  if (!normalizedChatRef) {
    message.value = 'Masukkan @username, username, ID numeric, link t.me publik, atau nomor telepon internasional.';
    return;
  }
  const manualStartId = Number(startId.value);
  if (overwriteStartId.value && (!Number.isInteger(manualStartId) || manualStartId < 1)) {
    message.value = 'Start ID manual harus berupa angka minimal 1.';
    return;
  }
  if (!targetProfile.value || !targetWorker.value) {
    message.value = 'Pilih profil dan worker target.';
    return;
  }
  const payload: Record<string, unknown> = {
    chat_ref: normalizedChatRef,
    label: label.value || undefined,
    use_url_message_id: overwriteStartId.value,
    profile: targetProfile.value,
    worker: targetWorker.value
  };
  if (isNumeric(normalizedChatRef)) payload.save_source = saveNumericSource.value;
  if (overwriteStartId.value) payload.start_id = manualStartId;
  if (quickMode.value) payload.quick_mode = true;
  submitting.value = true;
  try {
    const response = await post<unknown>('/exports', payload);
    if (!isExportJob(response)) throw new Error('Respons export dari backend tidak valid.');
    window.dispatchEvent(new CustomEvent('tme3:data-mutated', { detail: { path: '/exports' } }));
    remember(response);
    schedulePoll();
    exportCooldown.value = true;
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldownTimer = setTimeout(() => { exportCooldown.value = false; cooldownTimer = undefined; }, 500);
    void loadSources().catch(() => {});
  } catch (cause) {
    message.value = cause instanceof Error ? cause.message : 'Export gagal dibuat.';
  } finally { submitting.value = false; }
}

async function deleteSource(source: Source) {
  try {
    await remove(`/sources/${encodeURIComponent(source.chat_ref)}`);
    if (selected.value === source.chat_ref) chooseSource('');
    await loadSources();
  } catch (cause) {
    sourcesError.value = cause instanceof Error ? cause.message : 'Source gagal dihapus.';
  }
}

watch([targetProfile, targetWorker], () => {
  selected.value = '';
  chatRef.value = '';
  startId.value = '1';
  label.value = '';
  saveNumericSource.value = false;
  void loadSources();
});
watch(quickMode, () => { message.value = ''; });

onMounted(() => {
  mounted = true;
  targetProfile.value = session.selectedTargetProfile
    || session.current.actor?.profile
    || session.current.profiles[0]
    || '';
  targetWorker.value = workers.value.find((item) => item.name === session.current.actor?.worker_route)?.name
    || workers.value[0]?.name
    || '';
  void Promise.all([loadSources(), refreshReadiness()]);
  try {
    const saved = JSON.parse(sessionStorage.getItem('tme3-export-notices') || '[]');
    const ids = Array.isArray(saved) ? saved.filter((id): id is string => typeof id === 'string' && Boolean(id.trim())).slice(0, 4) : [];
    void Promise.all(ids.map((id) => api<unknown>(`/jobs/${encodeURIComponent(id)}`).catch(() => null)))
      .then((jobs) => { notices.value = jobs.flatMap((job) => isExportJob(job) ? [{ job }] : []); persistNotices(); schedulePoll(); });
  } catch { sessionStorage.removeItem('tme3-export-notices'); }
  window.addEventListener('tme3:job-finished', refreshReadiness);
});
onUnmounted(() => {
  mounted = false;
  if (pollTimer) clearTimeout(pollTimer);
  if (cooldownTimer) clearTimeout(cooldownTimer);
  window.removeEventListener('tme3:job-finished', refreshReadiness);
});
</script>

<template>
  <main class="page-stack export-page">
    <div class="export-notice-viewport" aria-live="polite" aria-atomic="false">
      <article v-for="noticeItem in notices" :key="noticeItem.job.id" class="panel export-notice" :class="`notice-${noticeItem.job.status}`" role="status">
        <div class="notice-content">
          <div class="notice-top"><strong>{{ noticeItem.job.status === 'succeeded' ? 'Export selesai' : noticeItem.job.status === 'failed' ? 'Export gagal' : 'Export masuk antrean' }}</strong><button class="icon-button" type="button" :aria-label="`Tutup notifikasi export ${noticeItem.job.id}`" @click="dismiss(noticeItem.job.id)">×</button></div>
          <p v-if="noticeItem.job.status === 'succeeded'">{{ completionText(noticeItem.job) }}</p>
          <p v-else-if="noticeItem.job.status === 'failed'" class="notice-error-text">{{ noticeItem.job.error?.message || 'Worker tidak dapat menyelesaikan export.' }}</p>
          <p v-else class="muted">{{ noticeItem.job.progress?.message || 'Menunggu worker yang dipilih.' }} · {{ noticeItem.job.id.slice(0, 12) }}</p>
          <p v-if="noticeItem.job.status === 'succeeded' && quickCompletionDetails(resultValue(noticeItem.job))" class="muted">{{ quickCompletionDetails(resultValue(noticeItem.job)) }}</p>
          <p v-if="noticeItem.job.status === 'succeeded'" class="muted">{{ resultValue(noticeItem.job).chat_ref || chatRef }}<template v-if="resultValue(noticeItem.job).requested_label"> · {{ resultValue(noticeItem.job).requested_label }}</template></p>
        </div>
      </article>
    </div>

    <header class="page-heading">
      <div><p class="eyebrow">PEMROSESAN · EXPORT</p><h1>Source &amp; pembuatan export</h1><p class="muted">Pilih source tersimpan atau masukkan username, ID, link t.me publik, atau nomor telepon.</p></div>
      <div class="target-controls">
        <label>Profile target<select v-model="targetProfile" class="field" aria-label="Profile target"><option value="" disabled>Pilih profile</option><option v-for="profile in session.current.profiles" :key="profile" :value="profile">{{ profile }}</option></select></label>
        <label>Worker target<select v-model="targetWorker" class="field" aria-label="Worker target"><option value="" disabled>Pilih worker</option><option v-for="item in session.workers" :key="item.name" :value="item.name" :disabled="item.enabled === false">{{ item.name }}{{ item.enabled === false ? ' (nonaktif)' : '' }}</option></select></label>
      </div>
    </header>

    <p class="notice readiness-notice" :class="{ 'notice-warning': readinessResult.status !== 'ready', 'notice-success': readinessResult.status === 'ready' }" role="status" aria-label="Kesiapan Export">
      <strong>{{ readinessLabel }}</strong><span>{{ targetProfile || 'profil belum dipilih' }} · {{ targetWorker || 'worker belum dipilih' }}</span><small v-if="readinessResult.reason_code">{{ readinessResult.reason_code }}</small><small>Status scan hanya informasi; command aktual menentukan hasil job.</small>
    </p>

    <section class="export-grid">
      <article class="panel">
        <header class="panel-heading"><div><p class="eyebrow">EXPORT</p><h2>Export baru</h2></div></header>
        <div class="export-form">
          <label>Pilih source tersimpan<select class="field" aria-label="Pilih source tersimpan" :value="selected" @change="chooseSource(($event.target as HTMLSelectElement).value)"><option value="">Source baru…</option><option v-for="source in sources" :key="source.chat_ref" :value="source.chat_ref">{{ source.label ? `${source.label} — ` : '' }}{{ source.chat_ref }} (berikutnya: {{ Number(source.last_id || 0) + 1 }})</option></select></label>
          <div class="export-input-grid">
            <label class="wide-field">Referensi chat<input class="field" maxlength="2048" :value="chatRef" placeholder="@iyear · 123456789 · https://t.me/iyear · +1 123456789" @input="updateChatRef(($event.target as HTMLInputElement).value)"></label>
            <label>Start message ID<input v-model="startId" class="field" type="number" min="1" :disabled="!overwriteStartId" aria-label="Start message ID"></label>
            <label>Label<input v-model="label" class="field" list="export-label-options" placeholder="Opsional"><datalist id="export-label-options"><option v-for="item in labels" :key="item.label" :value="item.label"></option></datalist></label>
          </div>
          <label class="switch-option"><input v-model="overwriteStartId" type="checkbox" role="switch"><span><strong>Overwrite Start ID</strong><small>Aktifkan hanya untuk export ini. Last ID backend tidak akan diturunkan.</small></span></label>
          <label class="switch-option quick-option"><input v-model="quickMode" type="checkbox" role="switch"><span><strong>Quick Mode Export</strong><small>Download, thumbnail, compress, dan upload otomatis ke ModeCepat/tahun.</small></span></label>
          <label v-if="isNumeric(chatRef)" class="switch-option numeric-option"><input v-model="saveNumericSource" type="checkbox" role="switch"><span><strong>Simpan source numeric</strong><small>Default mati agar ID sekali pakai tidak memenuhi daftar source.</small></span></label>
          <div v-if="labels.length" class="label-chips"><button v-for="item in labels" :key="item.label" class="chip-button" type="button" @click="label = item.label">{{ item.label }}</button></div>
          <p v-if="message" class="notice notice-error" role="alert">{{ message }}</p>
          <p v-if="sourcesError" class="notice notice-error" role="alert">{{ sourcesError }}</p>
          <div class="form-actions"><button class="button" type="button" :disabled="submitting || exportCooldown" @click="submit">{{ submitting ? 'Mengirim…' : exportCooldown ? 'Tunggu sebentar…' : 'Mulai export' }}</button><button class="button button-secondary" type="button" :disabled="submitting" @click="resetForm">Reset form</button></div>
        </div>
      </article>

      <article class="panel source-panel">
        <header class="panel-heading"><div><p class="eyebrow">KATALOG</p><h2>Source tersimpan</h2><p class="muted">Klik source untuk memakai Last ID berikutnya.</p></div><span class="status-pill status-neutral">{{ sources.length }} source</span></header>
        <p v-if="loading && !sources.length" class="empty-state" role="status">Memuat source…</p>
        <div v-else-if="sources.length" class="source-list"><article v-for="source in sources" :key="source.chat_ref" class="source-row"><button class="source-select" type="button" @click="chooseSource(source.chat_ref)"><strong>{{ source.chat_ref }}</strong><small class="muted">{{ source.label || 'Tanpa label' }} · Last ID {{ source.last_id || 0 }}</small></button><button class="icon-button" type="button" :aria-label="`Hapus ${source.chat_ref}`" @click="deleteSource(source)">×</button></article></div>
        <div v-else class="empty-state"><strong>Belum ada source.</strong><small>Export yang sukses akan menyimpan source ini.</small></div>
      </article>
    </section>

    <JobMonitor kind="export" title="Riwayat export" :retryable="true" />
  </main>
</template>

<style scoped>
.target-controls{display:grid;grid-template-columns:repeat(2,minmax(9rem,1fr));gap:.55rem;min-width:min(100%,24rem)}
.target-controls label,.export-form>label,.export-input-grid label{display:grid;gap:.35rem;font-size:.67rem;font-weight:750}
.readiness-notice{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem .75rem}.readiness-notice small{width:100%}.notice-success{color:var(--success);border-color:color-mix(in srgb,var(--success) 35%,var(--line))}
.export-grid{display:grid;grid-template-columns:minmax(20rem,.9fr) minmax(18rem,1.1fr);gap:.85rem;align-items:start}.export-form{display:grid;gap:.75rem;padding:.85rem}.export-input-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem}.wide-field{grid-column:1/-1}
.switch-option{display:flex;align-items:flex-start;gap:.55rem;padding:.65rem .7rem;border:1px solid var(--line);border-radius:9px;background:var(--panel-soft)}.switch-option span{display:grid;gap:.2rem;font-size:.68rem}.switch-option small{color:var(--muted);font-size:.61rem;font-weight:400;line-height:1.4}.quick-option{border-color:color-mix(in srgb,var(--brand) 40%,var(--line))}.numeric-option{border-color:color-mix(in srgb,var(--warning) 40%,var(--line))}.label-chips,.form-actions{display:flex;flex-wrap:wrap;gap:.4rem}.chip-button{border:1px solid var(--line);border-radius:99px;padding:.28rem .55rem;font-size:.62rem;font-weight:700}.form-actions{justify-content:space-between;margin-top:.15rem}.source-list{max-height:25rem;overflow:auto}.source-row{display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:.7rem .85rem;border-bottom:1px solid var(--line)}.source-select{display:grid;min-width:0;gap:.2rem;text-align:left}.source-select strong,.source-select small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.source-select strong{font-size:.72rem}.source-select small{font-size:.62rem}.empty-state{display:grid;gap:.25rem;place-items:center;padding:2rem;text-align:center;color:var(--muted);font-size:.7rem}.export-notice-viewport{position:fixed;inset-inline-end:max(1rem,env(safe-area-inset-right));bottom:max(1rem,env(safe-area-inset-bottom));z-index:1000;display:grid;width:min(390px,calc(100vw - 2rem));gap:.5rem;max-height:calc(100dvh - 2rem);overflow:auto;pointer-events:none}.export-notice{pointer-events:auto;padding:.6rem .75rem;border-color:color-mix(in srgb,var(--brand) 35%,var(--line))}.notice-content{display:grid;gap:.3rem}.notice-content p{margin:0;font-size:.66rem}.notice-top{display:flex;align-items:center;justify-content:space-between;font-size:.72rem}.notice-error-text{color:var(--danger)}
@media(max-width:850px){.export-grid{grid-template-columns:1fr}.target-controls{width:100%;min-width:0}}
@media(max-width:560px){.target-controls,.export-input-grid{grid-template-columns:1fr}.wide-field{grid-column:auto}.form-actions>*{flex:1}}
</style>
