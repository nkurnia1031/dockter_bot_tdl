<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { api } from '../lib/api';

type Job = { id: string; kind: string; worker: string; status: string; progress?: Record<string, unknown>; error?: Record<string, unknown>; created_at?: string; updated_at?: string; finished_at?: string };
type WorkerMetric = { worker: string; status: string; active_jobs?: number; last_seen_age_seconds?: number | null; enabled?: boolean };
type WorkerReadiness = { name: string; status: 'success' | 'failed' | 'disabled'; checked_at?: string; reason_code?: string };
type ReadinessCell = { worker: string; runtime: string; status: string; profile?: string | null };

const loading = ref(false);
const loaded = ref(false);
const error = ref('');
const partialWarning = ref('');
const summary = ref<Record<string, any>>({});
const activeJobs = ref<Job[]>([]);
const failedJobs = ref<Job[]>([]);
const workers = ref<WorkerMetric[]>([]);
const workerReadiness = ref<WorkerReadiness[]>([]);
const readiness = ref<ReadinessCell[]>([]);
const lastUpdated = ref<Date | null>(null);

const visibleRuntimeCells = computed(() => readiness.value);
const displayedWorkers = computed(() => {
  const byName = new Map(workers.value.map((worker) => [worker.worker, worker]));
  for (const worker of workerReadiness.value) {
    if (!byName.has(worker.name)) byName.set(worker.name, { worker: worker.name, status: 'unknown' });
  }
  return [...byName.values()];
});
const serviceLabels: Record<string, string> = {
  resolver: 'Resolver', tts_helper: 'TTS runtime', quick_mode_runtime: 'Quick Mode', rclone_storage: 'Rclone'
};

function jobTitle(job: Job): string {
  const name = typeof job.progress?.active_file === 'string' ? job.progress.active_file : '';
  const safeName = name.split(/[\\/]/).filter(Boolean).at(-1) || '';
  return safeName || job.kind.replaceAll('_', ' ');
}

function failureLabel(job: Job): string {
  const code = job.error?.code || job.error?.reason_code;
  return typeof code === 'string' && /^[A-Z0-9_]{2,64}$/.test(code) ? code : 'Periksa detail job';
}

function workerReadinessLabel(worker: WorkerMetric): string {
  if (worker.enabled === false) return 'Nonaktif';
  const snapshot = workerReadiness.value.find((item) => item.name === worker.worker);
  if (!snapshot) return 'Belum discan';
  if (snapshot.status === 'disabled') return 'Nonaktif';
  return snapshot.status === 'success' ? 'Siap' : 'Belum siap';
}

function workerReadinessClass(worker: WorkerMetric): string {
  const label = workerReadinessLabel(worker);
  return label === 'Siap' ? 'status-ready' : label === 'Belum siap' ? 'status-failed' : 'status-neutral';
}

function workerActivityLabel(worker: WorkerMetric): string {
  return ({
    busy: 'Job berjalan', stale: 'Heartbeat terlambat', paused: 'Job dijeda',
    queued: 'Job mengantre', idle: 'Antrean kosong', disabled: 'Admission nonaktif'
  } as Record<string, string>)[worker.status] || 'Aktivitas belum diketahui';
}

function displayTime(value?: string): string {
  if (!value) return 'Waktu tidak tersedia';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'short' });
}

function runtimeStatusLabel(status: string): string {
  return ({ ready: 'siap', failed: 'gagal', not_ready: 'belum siap', missing: 'belum ada', disabled: 'nonaktif', unknown: 'belum discan' } as Record<string, string>)[status]
    || status.replaceAll('_', ' ');
}

function runtimeCellClass(status: string): string {
  if (status === 'ready') return 'status-ready';
  if (['failed', 'not_ready'].includes(status)) return 'status-failed';
  if (status === 'disabled') return 'status-neutral';
  return 'status-warning';
}

async function refresh() {
  loading.value = true;
  error.value = '';
  partialWarning.value = '';
  const requests = await Promise.allSettled([
    api<Record<string, any>>('/dashboard/summary'),
    api<{ items: Job[] }>('/jobs?status=queued,dispatched,running,paused&limit=6'),
    api<{ items: Job[] }>('/jobs?status=failed&limit=5'),
    api<{ workers: WorkerMetric[] }>('/jobs/metrics?scope=current'),
    api<{ runtime_readiness?: { workers?: WorkerReadiness[]; cells?: ReadinessCell[] } }>('/profiles/local')
  ]);
  const problems = requests.flatMap((result, index) => result.status === 'rejected' ? [`Ringkasan ${index + 1}: ${result.reason instanceof Error ? result.reason.message : 'gagal dimuat'}`] : []);
  if (requests[0].status === 'fulfilled') summary.value = requests[0].value;
  if (requests[1].status === 'fulfilled') activeJobs.value = requests[1].value.items || [];
  if (requests[2].status === 'fulfilled') failedJobs.value = requests[2].value.items || [];
  if (requests[3].status === 'fulfilled') workers.value = requests[3].value.workers || [];
  if (requests[4].status === 'fulfilled') {
    workerReadiness.value = requests[4].value.runtime_readiness?.workers || [];
    readiness.value = requests[4].value.runtime_readiness?.cells || [];
  }
  error.value = problems.length === requests.length ? 'Ringkasan belum dapat dimuat. Periksa koneksi backend, lalu muat ulang.' : '';
  if (problems.length > 0 && problems.length < requests.length) {
    partialWarning.value = `${problems.length} bagian ringkasan belum tersedia. Muat ulang untuk mencoba lagi.`;
  }
  loaded.value = true;
  lastUpdated.value = new Date();
  loading.value = false;
}

onMounted(() => { void refresh(); });
</script>

<template>
  <main class="page-stack overview-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">MONITOR · CONTROL CENTER</p>
        <h1>Ringkasan operasional</h1>
        <p class="muted">Status job, worker, layanan, dan kegagalan terbaru.</p>
      </div>
      <div class="heading-actions">
        <span v-if="lastUpdated" class="muted last-updated">Diperbarui {{ lastUpdated.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) }}</span>
        <button class="button button-secondary" type="button" aria-label="Muat ulang ringkasan" :disabled="loading" @click="refresh">
          <span class="refresh-icon" :class="{ spinning: loading }" aria-hidden="true">↻</span>
          {{ loading ? 'Memuat…' : 'Muat ulang' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="notice notice-error" role="alert">{{ error }}</div>
    <div v-else-if="partialWarning" class="notice notice-warning" role="status">{{ partialWarning }}</div>
    <div v-else-if="!loaded" class="notice" role="status">Mengambil status operasional…</div>

    <section class="summary-grid" aria-label="Ringkasan job">
      <article class="metric-card metric-accent">
        <span class="metric-label">Job aktif</span>
        <strong class="metric-value">{{ summary.jobs?.active ?? '—' }}</strong>
        <span class="metric-foot">Menunggu atau sedang berjalan</span>
      </article>
      <article class="metric-card metric-danger">
        <span class="metric-label">Gagal terbaru</span>
        <strong class="metric-value">{{ summary.jobs?.failed ?? '—' }}</strong>
        <span class="metric-foot">Job gagal belum diarsipkan</span>
      </article>
      <article class="metric-card">
        <span class="metric-label">Profil aktif</span>
        <strong class="metric-value metric-name">{{ summary.profile || '—' }}</strong>
        <span class="metric-foot">Target default control plane</span>
      </article>
      <article class="metric-card">
        <span class="metric-label">Worker target</span>
        <strong class="metric-value metric-name">{{ summary.worker || '—' }}</strong>
        <span class="metric-foot">Job baru mengikuti route profil</span>
      </article>
    </section>

    <section class="overview-columns">
      <article class="panel">
        <header class="panel-heading"><div><p class="eyebrow">ANTREAN</p><h2>Job aktif</h2></div><span class="count-badge">{{ activeJobs.length }}</span></header>
        <div v-if="activeJobs.length" class="compact-list">
          <div v-for="job in activeJobs" :key="job.id" class="compact-row">
            <span class="state-dot" :class="`state-${job.status}`" aria-hidden="true"></span>
            <div class="row-main"><strong>{{ jobTitle(job) }}</strong><span class="muted">{{ job.kind.replaceAll('_', ' ') }} · {{ job.worker }}</span></div>
            <span class="status-pill" :class="`status-${job.status}`">{{ job.status }}</span>
          </div>
        </div>
        <div v-else class="empty-state">{{ loaded ? 'Tidak ada job aktif.' : 'Memuat daftar job…' }}</div>
      </article>

      <article class="panel">
        <header class="panel-heading"><div><p class="eyebrow">INFRASTRUKTUR</p><h2>Worker & layanan</h2></div><span class="count-badge">{{ displayedWorkers.length }}</span></header>
        <div v-if="displayedWorkers.length" class="compact-list">
          <div v-for="worker in displayedWorkers" :key="worker.worker" class="worker-row">
            <span class="worker-glyph" aria-hidden="true">W</span>
            <div class="row-main"><strong>{{ worker.worker }}</strong><span class="muted">{{ workerActivityLabel(worker) }} · {{ worker.active_jobs || 0 }} job aktif</span></div>
            <span class="status-pill" :class="workerReadinessClass(worker)">{{ workerReadinessLabel(worker) }}</span>
          </div>
          <div class="service-list" aria-label="Status runtime">
            <span v-for="cell in visibleRuntimeCells" :key="`${cell.worker}-${cell.runtime}-${cell.profile || ''}`" class="service-chip" :class="runtimeCellClass(cell.status)"><i aria-hidden="true"></i>{{ cell.worker }} · {{ cell.profile ? `${cell.profile} · ` : '' }}{{ serviceLabels[cell.runtime] || cell.runtime }} {{ runtimeStatusLabel(cell.status) }}</span>
            <span v-if="readiness.length === 0 && loaded" class="muted service-empty">Belum ada runtime dari scan terakhir.</span>
          </div>
        </div>
        <div v-else class="empty-state">{{ loaded ? 'Worker belum tersedia.' : 'Memuat status worker…' }}</div>
      </article>
    </section>

    <section class="panel">
      <header class="panel-heading"><div><p class="eyebrow">PERLU DILIHAT</p><h2>Kegagalan terbaru</h2></div><span class="count-badge count-danger">{{ failedJobs.length }}</span></header>
      <div v-if="failedJobs.length" class="failure-table" role="table" aria-label="Kegagalan terbaru">
        <div v-for="job in failedJobs" :key="job.id" class="failure-row" role="row">
          <div class="row-main"><strong>{{ jobTitle(job) }}</strong><span class="muted">{{ job.kind.replaceAll('_', ' ') }} · {{ job.worker }}</span></div>
          <span class="failure-message">{{ failureLabel(job) }}</span>
          <time class="muted">{{ displayTime(job.finished_at || job.updated_at || job.created_at) }}</time>
        </div>
      </div>
      <div v-else class="empty-state">{{ loaded ? 'Tidak ada kegagalan terbaru.' : 'Memuat riwayat…' }}</div>
    </section>

    <footer class="overview-foot muted">Ringkasan tidak melakukan polling. Gunakan Muat ulang untuk mengambil keadaan terbaru.</footer>
  </main>
</template>

<style scoped>
.service-chip.status-failed{border-color:color-mix(in srgb,var(--danger) 30%,var(--line));background:color-mix(in srgb,var(--danger) 7%,var(--panel));color:var(--danger)}
.service-chip.status-warning{border-color:color-mix(in srgb,var(--warning) 30%,var(--line));background:color-mix(in srgb,var(--warning) 7%,var(--panel));color:var(--warning)}
.service-chip.status-neutral{border-color:var(--line);background:var(--panel-soft);color:var(--muted)}
.service-chip.status-failed i,.service-chip.status-warning i,.service-chip.status-neutral i{background:currentColor}
</style>
