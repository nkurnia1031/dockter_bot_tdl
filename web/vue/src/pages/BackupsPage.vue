<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, put } from '../lib/api';
import { formatDate } from '../../../src/lib/presentation';
import { normalizeLocalProfileCatalog, profileOptionLabel, profileOptionsForWorker, type LocalProfileOption } from '../../../src/lib/profile-catalog';
import { tdlLaneLabel } from '../../../src/lib/tdl-lanes';

type Worker = { name: string; enabled?: boolean };
type TdlSession = { name: string; ready: boolean; code: string; identity_matches_metadata: boolean };
type TdlDiagnostics = { worker: string; profile: string; checked_at: string; ready: boolean; identity_match: boolean; reason_codes: string[]; sessions: TdlSession[] };
type BackupRun = { run_id: string; node_name: string; started_at?: string; completed_at?: string; status: string; error?: string };
type BackupData = Record<string, any> & { items?: BackupRun[] };
type Job = Record<string, any>;

const data = ref<BackupData>({ items: [] });
const workers = ref<Worker[]>([]);
const profiles = ref<LocalProfileOption[]>([]);
const diagnosticWorker = ref('');
const diagnosticProfile = ref('');
const diagnostics = ref<TdlDiagnostics | null>(null);
const diagnosticFailure = ref('');
const diagnosticMessage = ref('');
const choicesFailure = ref('');
const diagnosing = ref(false);
const verifyRunId = ref('');
const verificationJob = ref<Job | null>(null);
const verificationSubmitting = ref(false);
const verificationRefreshing = ref(false);
const verificationFailure = ref('');
const verificationMessage = ref('');
const message = ref('');
const error = ref('');
const loading = ref(false);
const pending = ref(false);
const saving = ref(false);
let verificationTimer: ReturnType<typeof setInterval> | undefined;

const diagnosticWorkers = computed(() => workers.value.filter((worker) => profiles.value.some((profile) => profile.workers.includes(worker.name))));
const diagnosticProfiles = computed(() => profileOptionsForWorker(profiles.value, diagnosticWorker.value));
const runsForSelectedWorker = computed(() => (data.value.items || []).filter((item) => item.node_name === diagnosticWorker.value && item.status === 'complete'));
const verificationReport = computed<any | null>(() => verificationJob.value?.result?.value?.report || verificationJob.value?.result?.report || null);
const draft = ref<Record<string, any>>({ enabled: true, schedule: '03:00', timezone: 'Asia/Jakarta', retention: 7, volume_size: '45m', channel: '', storage_trash_retention_days: 30, job_stall_timeout_seconds: 600, job_cancel_grace_seconds: 30 });
const enabledDiagnosticWorker = computed(() => workers.value.find((item) => item.name === diagnosticWorker.value));

watch(runsForSelectedWorker, (runs) => {
  if (!runs.some((item) => item.run_id === verifyRunId.value)) verifyRunId.value = runs[0]?.run_id || '';
});

async function load() {
  loading.value = true; error.value = '';
  try {
    data.value = await api<BackupData>('/backups/status');
    draft.value = {
      enabled: data.value.enabled,
      schedule: data.value.schedule,
      timezone: data.value.timezone,
      retention: data.value.retention,
      volume_size: data.value.volume_size,
      channel: data.value.channel || '',
      storage_trash_retention_days: data.value.storage_trash_retention_days ?? 30,
      job_stall_timeout_seconds: data.value.job_stall_timeout_seconds ?? 600,
      job_cancel_grace_seconds: data.value.job_cancel_grace_seconds ?? 30
    };
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Status backup gagal dimuat.'; }
  finally { loading.value = false; }
}
async function run() {
  pending.value = true; error.value = ''; message.value = '';
  try { await post('/backups'); message.value = 'Backup gateway mulai dijalankan.'; await load(); window.dispatchEvent(new CustomEvent('tme3:data-mutated')); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Job backup gagal dibuat.'; }
  finally { pending.value = false; }
}
async function saveSettings() {
  saving.value = true; error.value = ''; message.value = '';
  try {
    await put('/backups/settings', { ...draft.value, retention: Number(draft.value.retention), storage_trash_retention_days: Number(draft.value.storage_trash_retention_days), job_stall_timeout_seconds: Number(draft.value.job_stall_timeout_seconds), job_cancel_grace_seconds: Number(draft.value.job_cancel_grace_seconds) });
    message.value = 'Pengaturan disimpan dan langsung berlaku.';
    await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Pengaturan backup gagal disimpan.'; }
  finally { saving.value = false; }
}
async function loadDiagnosticChoices() {
  choicesFailure.value = '';
  try {
    const [workerResult, profileResult] = await Promise.all([api<{ items?: Worker[] }>('/workers'), api<unknown>('/profiles/local')]);
    workers.value = workerResult.items || [];
    profiles.value = normalizeLocalProfileCatalog(profileResult);
    const choices = workers.value.filter((worker) => profiles.value.some((profile) => profile.workers.includes(worker.name)));
    if (!choices.some((worker) => worker.name === diagnosticWorker.value)) diagnosticWorker.value = choices[0]?.name || '';
    const options = profileOptionsForWorker(profiles.value, diagnosticWorker.value);
    if (!options.some((profile) => profile.name === diagnosticProfile.value)) diagnosticProfile.value = options[0]?.name || '';
  } catch (cause) { choicesFailure.value = cause instanceof Error ? cause.message : 'Daftar worker dan profil gagal dimuat.'; }
}
function changeDiagnosticWorker(value: string) {
  diagnosticWorker.value = value;
  if (!profileOptionsForWorker(profiles.value, value).some((profile) => profile.name === diagnosticProfile.value)) diagnosticProfile.value = profileOptionsForWorker(profiles.value, value)[0]?.name || '';
}
function changeDiagnosticProfile(value: string) {
  diagnosticProfile.value = value;
  const selected = profiles.value.find((profile) => profile.name === value);
  if (selected?.exclusive_worker) diagnosticWorker.value = selected.exclusive_worker;
  else if (selected && !selected.workers.includes(diagnosticWorker.value)) diagnosticWorker.value = selected.workers[0] || '';
}
async function createDiagnostics() {
  if (!diagnosticWorker.value || !diagnosticProfile.value) return;
  diagnosing.value = true; diagnostics.value = null; diagnosticFailure.value = ''; diagnosticMessage.value = '';
  try { diagnostics.value = await post<TdlDiagnostics>('/backups/tdl-diagnostics', { worker: diagnosticWorker.value, profile: diagnosticProfile.value }); diagnosticMessage.value = 'JSON diagnosis dibuat dari worker dan profil yang dipilih.'; }
  catch (cause) { diagnosticFailure.value = cause instanceof Error ? cause.message : 'Diagnosis TDL gagal dijalankan.'; }
  finally { diagnosing.value = false; }
}
function json(value: unknown) { return `${JSON.stringify(value, null, 2)}\n`; }
function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([json(value)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); URL.revokeObjectURL(url);
}
async function copyJson(value: unknown, label: string) {
  try {
    await navigator.clipboard.writeText(json(value));
    if (value === diagnostics.value) diagnosticMessage.value = `${label} disalin.`;
    else verificationMessage.value = `${label} disalin.`;
  } catch {
    if (value === diagnostics.value) diagnosticFailure.value = 'Clipboard tidak tersedia. Gunakan tombol Unduh JSON.';
    else verificationFailure.value = 'Clipboard tidak tersedia. Gunakan tombol Unduh JSON.';
  }
}
function stopVerificationPolling() { if (verificationTimer) clearInterval(verificationTimer); verificationTimer = undefined; }
async function refreshVerificationJob() {
  const id = String(verificationJob.value?.id || '');
  if (!id || verificationRefreshing.value) return;
  verificationRefreshing.value = true;
  try {
    verificationJob.value = await api<Job>(`/jobs/${encodeURIComponent(id)}`);
    if (['succeeded', 'failed', 'cancelled'].includes(String(verificationJob.value.status || ''))) stopVerificationPolling();
  } catch (cause) { verificationFailure.value = cause instanceof Error ? cause.message : 'Status verifikasi backup gagal dimuat.'; }
  finally { verificationRefreshing.value = false; }
}
async function verifyBackupFromChannel() {
  if (!diagnosticWorker.value || !diagnosticProfile.value || !verifyRunId.value) return;
  stopVerificationPolling(); verificationSubmitting.value = true; verificationJob.value = null; verificationFailure.value = ''; verificationMessage.value = '';
  try {
    verificationJob.value = await api<Job>('/backups/verify', { method: 'POST', headers: { 'Idempotency-Key': requestKey() }, body: JSON.stringify({ worker: diagnosticWorker.value, profile: diagnosticProfile.value, run_id: verifyRunId.value }) });
    verificationMessage.value = 'Job diterima. Worker akan mengambil part dari channel backup lalu memeriksa arsip dan sesi.';
    if (!['succeeded', 'failed', 'cancelled'].includes(String(verificationJob.value?.status || ''))) verificationTimer = setInterval(() => { void refreshVerificationJob(); }, 2500);
    window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
  } catch (cause) { verificationFailure.value = cause instanceof Error ? cause.message : 'Job verifikasi backup gagal dibuat.'; }
  finally { verificationSubmitting.value = false; }
}
function requestKey() { return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
const reportSummary = computed(() => {
  const report = verificationReport.value;
  if (report?.status !== 'verified') return 'Arsip gagal diverifikasi';
  if (report.canary_evidence_status === 'ready_for_operator_review') return 'Sesi TDL lolos; bukti siap ditinjau untuk canary.';
  if (report.canary_evidence_status === 'tdl_failed') return 'Arsip valid, tetapi sesi TDL pada worker/profil ini gagal. Belum aman untuk canary.';
  if (report.canary_evidence_status !== 'backup_failed') return 'Arsip lolos pemeriksaan file, tetapi profil belum dinyatakan siap untuk canary. Periksa diagnosis TDL dan status bukti pada JSON.';
  return '';
});
function sessionOutcome(item: any) {
  if (item.content_test === 'not_run') return 'belum diuji';
  if (item.content_test === 'failed') return 'isi tidak lengkap';
  if (item.tdl_test === 'passed') return 'TDL lolos';
  if (item.tdl_test === 'failed') return 'TDL gagal';
  return 'belum diuji';
}
onMounted(() => { void load(); void loadDiagnosticChoices(); });
onUnmounted(() => { stopVerificationPolling(); });
</script>

<template>
  <main class="page-stack backups-page">
    <header class="page-heading"><div><p class="eyebrow">PEMROSESAN</p><h1>Backup terenkripsi</h1><p class="muted">Backup gateway, riwayat arsip worker, jadwal, dan hasil upload channel.</p></div><button class="button button-secondary" :disabled="loading" @click="load">{{ loading ? 'Memuat…' : 'Refresh' }}</button></header>
    <p v-if="message" class="notice notice-info" role="status">{{ message }}</p><p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    <section class="panel"><div class="panel-heading"><div><h2>Konfigurasi aktif</h2><p class="muted">{{ data.schedule || '-' }} · {{ data.timezone || '-' }} · retensi {{ data.retention ?? '-' }} · volume {{ data.volume_size || '-' }}</p></div><button class="button button-primary" :disabled="pending || data.enabled === false" @click="run">{{ pending ? 'Memulai…' : 'Backup sekarang' }}</button></div>
      <details><summary>Ubah pengaturan backup dan operasi</summary><div class="settings-grid"><label class="check-line"><input v-model="draft.enabled" type="checkbox">Jadwal backup aktif</label><label>Jadwal harian<input v-model="draft.schedule" class="field" type="time"></label><label>Zona waktu<input v-model="draft.timezone" class="field"></label><label>Jumlah backup disimpan<input v-model="draft.retention" class="field" type="number" min="1" max="3650"></label><label>Ukuran setiap arsip<input v-model="draft.volume_size" class="field" placeholder="45m"></label><label>Tujuan channel backup Telegram<input v-model="draft.channel" class="field" placeholder="-100123456789 · @channel · https://t.me/channel"><small class="muted">Username atau link publik harus menunjuk channel yang dapat diakses bot. Nomor telepon tidak didukung.</small></label><label>Retensi Trash Storage (hari)<input v-model="draft.storage_trash_retention_days" class="field" type="number" min="1" max="3650"></label><label>Timeout job macet (detik)<input v-model="draft.job_stall_timeout_seconds" class="field" type="number" min="0" max="86400"></label><label>Masa tunggu cancel (detik)<input v-model="draft.job_cancel_grace_seconds" class="field" type="number" min="0" max="3600"></label></div><div class="panel-heading"><p class="muted">Password arsip tetap disimpan sebagai konfigurasi dan tidak ditampilkan.</p><button class="button button-primary" :disabled="saving" @click="saveSettings">{{ saving ? 'Menyimpan…' : 'Simpan pengaturan' }}</button></div></details>
    </section>
    <section class="panel" aria-labelledby="diagnostics-title"><div><h2 id="diagnostics-title">Diagnosis dan verifikasi backup worker</h2><p class="muted">Diagnosis TDL menguji lane Download dan Export tanpa mengubah sesi. Verifikasi mencocokkan ekspor channel berdasarkan worker, run, dan nama part.</p></div>
      <div class="form-grid"><label>Worker<select class="field" :value="diagnosticWorker" :disabled="diagnosing" @change="changeDiagnosticWorker(($event.target as HTMLSelectElement).value)"><option value="">Pilih worker</option><option v-for="item in diagnosticWorkers" :key="item.name" :value="item.name">{{ item.name }}{{ item.enabled === false ? ' (nonaktif)' : '' }}</option></select></label><label>Profil<select class="field" :value="diagnosticProfile" :disabled="diagnosing" @change="changeDiagnosticProfile(($event.target as HTMLSelectElement).value)"><option value="">Pilih profil</option><option v-for="item in diagnosticProfiles" :key="item.name" :value="item.name">{{ profileOptionLabel(item) }}</option></select></label><button class="button button-primary" :disabled="diagnosing || !diagnosticWorker || !diagnosticProfile" @click="createDiagnostics">{{ diagnosing ? 'Memeriksa sesi…' : 'Buat JSON diagnosis' }}</button></div>
      <p v-if="choicesFailure" class="notice notice-error" role="alert">{{ choicesFailure }} <button class="text-button" @click="loadDiagnosticChoices">Muat ulang pilihan</button></p><p v-if="diagnosticFailure" class="notice notice-error" role="alert">{{ diagnosticFailure }}</p><p v-if="diagnosticMessage" class="notice notice-info" role="status">{{ diagnosticMessage }}</p>
      <article v-if="diagnostics" class="report-card"><div class="panel-heading"><div><strong>{{ diagnostics.worker }} / {{ diagnostics.profile }} · {{ diagnostics.ready ? 'Kedua sesi lolos' : 'Ada sesi yang gagal' }}</strong><p class="muted">Diperiksa {{ diagnostics.checked_at }} · identitas {{ diagnostics.identity_match ? 'cocok' : 'tidak cocok' }}</p></div><div class="toolbar-actions"><button class="button button-secondary" @click="copyJson(diagnostics, 'JSON diagnosis')">Salin JSON</button><button class="button button-secondary" @click="downloadJson(diagnostics, 'tdl-diagnostics.json')">Unduh JSON</button></div></div><p v-if="diagnostics.reason_codes.length" class="notice notice-error">Alasan: {{ diagnostics.reason_codes.join(', ') }}</p><div class="session-grid"><article v-for="item in diagnostics.sessions" :key="item.name"><strong>{{ tdlLaneLabel(item.name) }} · {{ item.ready ? 'Siap' : 'Gagal' }}</strong><p>{{ item.code }} · identitas {{ item.identity_matches_metadata ? 'cocok' : 'tidak cocok' }}</p></article></div><details><summary>Lihat JSON</summary><pre>{{ json(diagnostics) }}</pre></details></article>
      <section class="subsection"><h3>Ekstrak dan uji sesi dari channel backup</h3><p class="muted">Worker mencocokkan node, run, dan nama part dari caption channel, mengunduh message ID yang cocok, lalu menguji arsip, manifest, identitas, serta sesi TDL. File di channel tidak dikirim ulang atau dihapus.</p><div class="form-grid"><label>Run backup lengkap untuk {{ diagnosticWorker || 'worker' }}<select v-model="verifyRunId" class="field" :disabled="verificationSubmitting || !runsForSelectedWorker.length"><option value="">Pilih run backup</option><option v-for="item in runsForSelectedWorker" :key="item.run_id" :value="item.run_id">{{ item.run_id }} · {{ formatDate(item.started_at) }}</option></select></label><button class="button button-primary" :disabled="verificationSubmitting || !diagnosticWorker || !diagnosticProfile || !verifyRunId || enabledDiagnosticWorker?.enabled === false" @click="verifyBackupFromChannel">{{ verificationSubmitting ? 'Mengirim job…' : 'Unduh dari channel & uji sesi' }}</button></div>
        <p v-if="!runsForSelectedWorker.length" class="muted">Belum ada run berstatus complete untuk worker ini.</p><p v-if="enabledDiagnosticWorker?.enabled === false" class="notice notice-warning" role="status">Worker nonaktif. Aktifkan worker sebelum menjalankan verifikasi.</p><p v-if="verificationFailure" class="notice notice-error" role="alert">{{ verificationFailure }}</p><p v-if="verificationMessage" class="notice notice-info" role="status">{{ verificationMessage }}</p>
        <article v-if="verificationJob" class="report-card"><div class="panel-heading"><div><strong>Job verifikasi · {{ verificationJob.worker }} / {{ verificationJob.profile }}</strong><code>{{ verificationJob.id }}</code></div><div class="toolbar-actions"><span class="badge" :class="verificationJob.status">{{ verificationJob.status }}</span><button class="button button-secondary" :disabled="verificationRefreshing" @click="refreshVerificationJob">{{ verificationRefreshing ? 'Memuat…' : 'Muat status' }}</button></div></div><p v-if="verificationJob.progress?.message" class="muted">{{ verificationJob.progress.message }}</p><p v-if="verificationJob.error?.message" class="notice notice-error">{{ verificationJob.error.message }}</p><p v-if="verificationJob.status === 'succeeded' && verificationReport?.status === 'failed'" class="notice notice-error">Job selesai dijalankan, tetapi ekstraksi atau pengujian isi gagal. Lihat kode alasan pada laporan JSON.</p>
          <section v-if="verificationReport" class="report-detail"><p v-if="reportSummary" class="notice" :class="verificationReport.status === 'verified' ? 'notice-success' : 'notice-error'">{{ reportSummary }}</p><div class="panel-heading"><div><strong>Arsip {{ verificationReport.status === 'verified' ? 'terverifikasi' : 'gagal diverifikasi' }}</strong><p class="muted">{{ verificationReport.worker }} / {{ verificationReport.profile }} · run {{ verificationReport.run_id }} · {{ verificationReport.part_count }} part</p></div><div class="toolbar-actions"><button class="button button-secondary" @click="copyJson(verificationReport, 'JSON hasil verifikasi')">Salin JSON</button><button class="button button-secondary" @click="downloadJson(verificationReport, `backup-verification-${verificationReport.worker}-${verificationReport.profile}-${verificationReport.run_id}.json`)">Unduh JSON</button></div></div><p v-if="verificationReport.reason_codes?.length" class="notice notice-error">Alasan: {{ verificationReport.reason_codes.join(', ') }}</p><div v-if="verificationReport.sessions?.length" class="session-grid"><article v-for="item in verificationReport.sessions" :key="item.name"><strong>Sesi {{ tdlLaneLabel(item.name) }} · {{ sessionOutcome(item) }}</strong><p>{{ item.content_test === 'not_run' ? 'Belum diekstrak' : item.content_test === 'failed' ? 'File sesi hasil ekstraksi tidak lengkap' : item.identity_match ? 'Identitas cocok' : item.tdl_test === 'passed' ? 'Identitas tidak cocok' : 'Isi sesi hasil ekstraksi' }}</p></article></div><p v-if="verificationReport.tdl_diagnostics" class="muted">Diagnosis TDL: {{ verificationReport.tdl_diagnostics.ready ? 'siap' : 'gagal' }} · identitas {{ verificationReport.tdl_diagnostics.identity_match ? 'cocok' : 'tidak cocok' }}</p><p v-if="verificationReport.checksum_validation && verificationReport.checksum_validation !== 'verified'" class="notice notice-warning">Checksum katalog {{ verificationReport.checksum_validation === 'partial' ? 'hanya tersedia untuk sebagian part' : 'tidak tersedia' }}. Isi sesi tetap diekstrak dan diuji dengan TDL.</p><details v-if="verificationReport.download?.matched_parts?.length"><summary>Lihat part dan message ID yang diunduh</summary><ul><li v-for="item in verificationReport.download.matched_parts" :key="item.message_id"><code>{{ item.name }}</code> · message ID <code>{{ item.message_id }}</code></li></ul></details><details><summary>Lihat JSON canary lengkap</summary><pre>{{ json(verificationReport) }}</pre></details></section>
        </article>
      </section>
      <div class="backup-table"><table><thead><tr><th>Node</th><th>Run ID lengkap</th><th>Status</th><th>Mulai</th><th>Selesai</th><th>Error</th></tr></thead><tbody><tr v-for="item in data.items || []" :key="item.run_id"><td>{{ item.node_name }}</td><td><code>{{ item.run_id || '-' }}</code></td><td><span class="badge" :class="item.status">{{ item.status }}</span></td><td>{{ formatDate(item.started_at) }}</td><td>{{ formatDate(item.completed_at) }}</td><td>{{ item.error || '-' }}</td></tr><tr v-if="!data.items?.length"><td colspan="6" class="empty-state">Belum ada riwayat backup.</td></tr></tbody></table></div>
    </section>
    <JobMonitor kind="backup_node" title="Job backup" view="all" />
    <JobMonitor kind="backup_verify" title="Job verifikasi arsip backup" view="history" />
  </main>
</template>

<style scoped>
.backups-page{max-width:94rem;margin:0 auto}.panel{display:grid;gap:.9rem;padding:1rem;border:1px solid var(--line);border-radius:1rem;background:var(--panel)}.panel h2,.panel h3{font-weight:800}.panel-heading{display:flex;align-items:center;justify-content:space-between;gap:.75rem}.panel-heading p{margin-top:.25rem}.muted{font-size:.76rem;color:var(--muted)}details{padding:.7rem;border:1px solid var(--line);border-radius:.7rem}summary{cursor:pointer;font-size:.8rem;font-weight:750}.settings-grid,.form-grid,.session-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.65rem}.settings-grid label,.form-grid label{display:grid;gap:.3rem;font-size:.73rem;font-weight:700}.settings-grid small{font-weight:400}.field{width:100%;padding:.55rem .65rem;border:1px solid var(--line);border-radius:.6rem;background:var(--panel-soft);color:var(--text)}.check-line{display:flex!important;align-items:center}.toolbar-actions{display:flex;align-items:center;flex-wrap:wrap;gap:.4rem}.button{padding:.48rem .65rem;border:1px solid var(--line);border-radius:.6rem;font-size:.74rem;font-weight:700}.button-primary{background:var(--accent);color:#071218}.button-secondary{background:var(--panel-soft)}.button:disabled{opacity:.5}.notice{padding:.65rem;border-radius:.6rem;font-size:.75rem}.notice-info{background:var(--panel-soft)}.notice-error{background:#3b121d;color:#fecaca}.notice-warning{background:#372a13;color:#fcd34d}.notice-success{background:#123526;color:#86efac}.text-button{text-decoration:underline}.report-card{display:grid;gap:.7rem;padding:.75rem;border:1px solid var(--line);border-radius:.75rem}.report-card code{font-size:.68rem;overflow-wrap:anywhere}.session-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.session-grid article{padding:.65rem;border-radius:.6rem;background:var(--panel-soft);font-size:.74rem}.session-grid p{margin-top:.3rem;color:var(--muted)}.subsection{display:grid;gap:.7rem;padding-top:.9rem;border-top:1px solid var(--line)}.report-detail{display:grid;gap:.7rem;padding:.75rem;background:var(--panel-soft);border-radius:.7rem}.backup-table{overflow:auto}.backup-table table{width:100%;min-width:54rem;text-align:left;font-size:.73rem;border-collapse:collapse}.backup-table th,.backup-table td{padding:.55rem;border-bottom:1px solid var(--line);vertical-align:top}.backup-table code{overflow-wrap:anywhere}.empty-state{text-align:center;padding:1.2rem;color:var(--muted)}@media(max-width:850px){.settings-grid,.form-grid,.session-grid{grid-template-columns:1fr}.panel-heading{align-items:flex-start;flex-wrap:wrap}}
</style>
