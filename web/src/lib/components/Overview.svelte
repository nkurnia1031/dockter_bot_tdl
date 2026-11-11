<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import {
    ArrowUpRight, Clock3, Database, RefreshCw, Server, TriangleAlert
  } from '@lucide/svelte';

  type Job = {
    id: string;
    kind: string;
    worker: string;
    status: string;
    progress?: Record<string, unknown>;
    error?: Record<string, unknown>;
    created_at?: string;
    updated_at?: string;
    finished_at?: string;
  };
  type WorkerMetric = { worker: string; status: string; active_jobs?: number; enabled?: boolean };
  type WorkerReadiness = { name: string; status: 'success' | 'failed' | 'disabled'; checked_at?: string };
  type ReadinessCell = { worker: string; runtime: string; status: string; profile?: string | null };

  let loading = $state(false);
  let loaded = $state(false);
  let error = $state('');
  let partialWarning = $state('');
  let summary = $state<Record<string, unknown>>({});
  let activeJobs = $state<Job[]>([]);
  let failedJobs = $state<Job[]>([]);
  let workers = $state<WorkerMetric[]>([]);
  let workerReadiness = $state<WorkerReadiness[]>([]);
  let readiness = $state<ReadinessCell[]>([]);
  let lastUpdated = $state<Date | null>(null);

  const serviceLabels: Record<string, string> = {
    resolver: 'Resolver', tts_helper: 'TTS runtime', quick_mode_runtime: 'Quick Mode', rclone_storage: 'Rclone'
  };
  const jobCounts = $derived((summary.jobs as Record<string, unknown> | undefined) || {});
  const summaryProfile = $derived(typeof summary.profile === 'string' ? summary.profile : '—');
  const summaryWorker = $derived(typeof summary.worker === 'string' ? summary.worker : '—');
  const displayedWorkers = $derived.by(() => {
    const byName = new Map(workers.map((worker) => [worker.worker, worker]));
    for (const worker of workerReadiness) {
      if (!byName.has(worker.name)) byName.set(worker.name, { worker: worker.name, status: 'unknown' });
    }
    return [...byName.values()];
  });

  function jobTitle(job: Job): string {
    const name = typeof job.progress?.active_file === 'string' ? job.progress.active_file : '';
    return name.split(/[\\/]/).filter(Boolean).at(-1) || job.kind.replaceAll('_', ' ');
  }

  function failureLabel(job: Job): string {
    const code = job.error?.code || job.error?.reason_code;
    return typeof code === 'string' && /^[A-Z0-9_]{2,64}$/.test(code) ? code : 'Periksa detail job';
  }

  function workerReadinessLabel(worker: WorkerMetric): string {
    if (worker.enabled === false) return 'Nonaktif';
    const snapshot = workerReadiness.find((item) => item.name === worker.worker);
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
    loading = true;
    error = '';
    partialWarning = '';
    const results = await Promise.allSettled([
      api<Record<string, unknown>>('/dashboard/summary'),
      api<{ items: Job[] }>('/jobs?status=queued,dispatched,running,paused&limit=6'),
      api<{ items: Job[] }>('/jobs?status=failed&limit=5'),
      api<{ workers: WorkerMetric[] }>('/jobs/metrics?scope=current'),
      api<{ runtime_readiness?: { workers?: WorkerReadiness[]; cells?: ReadinessCell[] } }>('/profiles/local')
    ] as const);
    const problems = results.flatMap((result, index) => result.status === 'rejected' ? [`Bagian ${index + 1} gagal dimuat`] : []);
    if (results[0].status === 'fulfilled') summary = results[0].value;
    if (results[1].status === 'fulfilled') activeJobs = results[1].value.items || [];
    if (results[2].status === 'fulfilled') failedJobs = results[2].value.items || [];
    if (results[3].status === 'fulfilled') workers = results[3].value.workers || [];
    if (results[4].status === 'fulfilled') {
      workerReadiness = results[4].value.runtime_readiness?.workers || [];
      readiness = results[4].value.runtime_readiness?.cells || [];
    }
    error = problems.length === results.length ? 'Ringkasan belum dapat dimuat. Periksa koneksi backend, lalu muat ulang.' : '';
    if (problems.length > 0 && problems.length < results.length) partialWarning = `${problems.length} bagian ringkasan belum tersedia. Muat ulang untuk mencoba lagi.`;
    loaded = true;
    lastUpdated = new Date();
    loading = false;
  }

  onMount(() => { void refresh(); });
</script>

<main class="overview-page">
  <header class="page-heading">
    <div>
      <p class="eyebrow">MONITOR · CONTROL CENTER</p>
      <h1>Ringkasan operasional</h1>
      <p class="muted">Status job, worker, layanan, dan kegagalan terbaru.</p>
    </div>
    <div class="heading-actions">
      {#if lastUpdated}<span class="muted last-updated">Diperbarui {lastUpdated.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</span>{/if}
      <button class="button secondary" type="button" aria-label="Muat ulang ringkasan" disabled={loading} onclick={refresh}>
        <RefreshCw size={15}/>{loading ? 'Memuat…' : 'Muat ulang'}
      </button>
    </div>
  </header>

  {#if error}<div class="notice notice-error" role="alert">{error}</div>
  {:else if partialWarning}<div class="notice notice-warning" role="status">{partialWarning}</div>
  {:else if !loaded}<div class="notice" role="status">Mengambil status operasional…</div>{/if}

  <section class="summary-grid" aria-label="Ringkasan job dan target">
    <article class="metric-card metric-accent"><span class="metric-label">Job aktif</span><strong class="metric-value">{jobCounts.active ?? '—'}</strong><span class="metric-foot">Menunggu atau sedang berjalan</span></article>
    <article class="metric-card metric-danger"><span class="metric-label">Gagal terbaru</span><strong class="metric-value">{jobCounts.failed ?? '—'}</strong><span class="metric-foot">Job gagal belum diarsipkan</span></article>
    <article class="metric-card"><span class="metric-label">Profil aktif</span><strong class="metric-value metric-name">{summaryProfile}</strong><span class="metric-foot">Target default control plane</span></article>
    <article class="metric-card"><span class="metric-label">Worker target</span><strong class="metric-value metric-name">{summaryWorker}</strong><span class="metric-foot">Job baru mengikuti route profil</span></article>
  </section>

  <section class="overview-columns">
    <article class="panel">
      <header class="panel-heading"><div><p class="eyebrow">ANTREAN</p><h2>Job aktif</h2></div><span class="count-badge">{activeJobs.length}</span></header>
      {#if activeJobs.length}
        <div class="compact-list">
          {#each activeJobs as job (job.id)}
            <a class="compact-row" href="/activity/">
              <span class="state-dot state-{job.status}" aria-hidden="true"></span>
              <span class="row-main"><strong>{jobTitle(job)}</strong><span class="muted">{job.kind.replaceAll('_', ' ')} · {job.worker}</span></span>
              <span class="status-pill status-{job.status}">{job.status}</span>
            </a>
          {/each}
        </div>
      {:else}<div class="empty-state">{loaded ? 'Tidak ada job aktif.' : 'Memuat daftar job…'}</div>{/if}
      <a class="panel-link" href="/activity/">Lihat semua aktivitas <ArrowUpRight size={14}/></a>
    </article>

    <article class="panel">
      <header class="panel-heading"><div><p class="eyebrow">INFRASTRUKTUR</p><h2>Worker & layanan</h2></div><span class="count-badge">{displayedWorkers.length}</span></header>
      {#if displayedWorkers.length}
        <div class="compact-list">
          {#each displayedWorkers as worker (worker.worker)}
            <div class="worker-row">
              <span class="worker-glyph"><Server size={15}/></span>
              <span class="row-main"><strong>{worker.worker}</strong><span class="muted">{workerActivityLabel(worker)} · {worker.active_jobs || 0} job aktif</span></span>
              <span class="status-pill {workerReadinessClass(worker)}">{workerReadinessLabel(worker)}</span>
            </div>
          {/each}
          <div class="service-list" aria-label="Status runtime">
            {#each readiness as cell (`${cell.worker}-${cell.runtime}-${cell.profile || ''}`)}
              <span class="service-chip {runtimeCellClass(cell.status)}"><i aria-hidden="true"></i>{cell.worker} · {cell.profile ? `${cell.profile} · ` : ''}{serviceLabels[cell.runtime] || cell.runtime} {runtimeStatusLabel(cell.status)}</span>
            {/each}
            {#if readiness.length === 0 && loaded}<span class="muted service-empty">Belum ada runtime dari scan terakhir.</span>{/if}
          </div>
        </div>
      {:else}<div class="empty-state">{loaded ? 'Worker belum tersedia.' : 'Memuat status worker…'}</div>{/if}
    </article>
  </section>

  <section class="panel failure-panel">
    <header class="panel-heading"><div><p class="eyebrow">PERLU DILIHAT</p><h2>Kegagalan terbaru</h2></div><span class="count-badge count-danger"><TriangleAlert size={13}/>{failedJobs.length}</span></header>
    {#if failedJobs.length}
      <div class="failure-table" role="table" aria-label="Kegagalan terbaru">
        {#each failedJobs as job (job.id)}
          <a class="failure-row" href="/activity/" role="row">
            <span class="row-main"><strong>{jobTitle(job)}</strong><span class="muted">{job.kind.replaceAll('_', ' ')} · {job.worker}</span></span>
            <span class="failure-message">{failureLabel(job)}</span>
            <time class="muted">{displayTime(job.finished_at || job.updated_at || job.created_at)}</time>
          </a>
        {/each}
      </div>
    {:else}<div class="empty-state">{loaded ? 'Tidak ada kegagalan terbaru.' : 'Memuat riwayat…'}</div>{/if}
  </section>

  <footer class="overview-foot"><span><Clock3 size={13}/> Ringkasan diperbarui manual; tidak ada polling saat idle.</span><span><Database size={13}/> {loaded ? 'Status backend tersedia' : 'Memuat status backend'}</span></footer>
</main>

<style>
  .overview-page { display: grid; gap: 1rem; }
  .page-heading { display: flex; min-height: 52px; align-items: center; justify-content: space-between; gap: 1rem; }
  .page-heading h1 { margin: .25rem 0 0; }
  .page-heading p:not(.eyebrow) { margin: .4rem 0 0; font-size: .72rem; }
  .heading-actions { display: flex; align-items: center; gap: .7rem; }
  .last-updated { font-family: "SFMono-Regular", Consolas, monospace; font-size: .62rem; white-space: nowrap; }
  .notice { padding: .7rem .85rem; border: 1px solid var(--line); border-radius: 9px; background: var(--panel); color: var(--muted); font-size: .7rem; }
  .notice-error { border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); color: var(--danger); }
  .notice-warning { border-color: color-mix(in srgb, var(--warning) 30%, var(--line)); color: var(--warning); }
  .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .7rem; }
  .metric-card { position: relative; display: grid; min-height: 116px; align-content: start; gap: .38rem; overflow: hidden; padding: .85rem .9rem; border: 1px solid var(--line); border-radius: 12px; background: linear-gradient(145deg, var(--panel), color-mix(in srgb, var(--panel-soft) 70%, var(--panel))); }
  .metric-card::before { position: absolute; top: 0; bottom: 0; left: 0; width: 2px; background: var(--line-bright); content: ""; }
  .metric-accent::before { background: var(--brand); }
  .metric-danger::before { background: var(--danger); }
  .metric-label { color: var(--muted); font-family: "SFMono-Regular", Consolas, monospace; font-size: .61rem; letter-spacing: .06em; text-transform: uppercase; }
  .metric-value { color: var(--ink); font-size: 1.75rem; font-weight: 760; letter-spacing: -.055em; line-height: 1.1; }
  .metric-value.metric-name { overflow: hidden; font-size: 1.05rem; text-overflow: ellipsis; white-space: nowrap; }
  .metric-foot { color: var(--muted-dim); font-size: .61rem; }
  .overview-columns { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr); gap: .7rem; }
  .panel { min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); }
  .panel-heading { display: flex; min-height: 55px; align-items: center; justify-content: space-between; gap: .8rem; padding: .7rem .9rem; border-bottom: 1px solid var(--line); }
  .panel-heading .eyebrow { margin: 0 0 .16rem; font-size: .53rem; }
  .panel-heading h2 { margin: 0; font-size: .87rem; font-weight: 720; }
  .count-badge { display: inline-flex; min-width: 25px; height: 25px; align-items: center; justify-content: center; gap: .27rem; padding: 0 .42rem; border: 1px solid var(--line); border-radius: 99px; background: var(--panel-soft); color: var(--muted); font-family: "SFMono-Regular", Consolas, monospace; font-size: .6rem; }
  .count-danger { border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); color: var(--danger); }
  .compact-list { display: grid; }
  .compact-row, .worker-row { display: flex; min-width: 0; min-height: 56px; align-items: center; gap: .65rem; padding: .55rem .85rem; border-bottom: 1px solid color-mix(in srgb, var(--line) 75%, transparent); text-decoration: none; }
  .compact-row:hover { background: var(--panel-soft); }
  .row-main { display: grid; min-width: 0; flex: 1; gap: .16rem; }
  .row-main strong { overflow: hidden; color: var(--ink); font-size: .69rem; text-overflow: ellipsis; white-space: nowrap; }
  .row-main .muted { overflow: hidden; font-size: .59rem; text-overflow: ellipsis; white-space: nowrap; }
  .state-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: var(--warning); }
  .state-running, .state-dispatched { background: var(--brand); }
  .state-succeeded { background: var(--success); }
  .state-failed { background: var(--danger); }
  .state-paused { background: var(--warning); }
  .worker-glyph { display: grid; width: 28px; height: 28px; flex: 0 0 auto; place-items: center; border: 1px solid var(--line-bright); border-radius: 8px; background: var(--panel-soft); color: var(--brand); }
  .service-list { display: flex; flex-wrap: wrap; gap: .35rem; padding: .65rem .85rem .75rem; }
  .service-chip { display: inline-flex; align-items: center; gap: .32rem; padding: .25rem .4rem; border: 1px solid color-mix(in srgb, var(--success) 25%, var(--line)); border-radius: 99px; background: color-mix(in srgb, var(--success) 6%, var(--panel)); color: var(--success); font-size: .55rem; }
  .service-chip i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .service-chip.status-failed { border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); background: color-mix(in srgb, var(--danger) 7%, var(--panel)); color: var(--danger); }
  .service-chip.status-warning { border-color: color-mix(in srgb, var(--warning) 30%, var(--line)); background: color-mix(in srgb, var(--warning) 7%, var(--panel)); color: var(--warning); }
  .service-chip.status-neutral { border-color: var(--line); background: var(--panel-soft); color: var(--muted); }
  .service-empty { font-size: .62rem; }
  .panel-link { display: flex; align-items: center; justify-content: flex-end; gap: .3rem; padding: .5rem .85rem; color: var(--brand); font-size: .62rem; font-weight: 700; text-decoration: none; }
  .panel-link:hover { color: var(--ink); }
  .failure-panel { margin-top: 0; }
  .failure-row { display: grid; min-height: 52px; grid-template-columns: minmax(130px, .8fr) minmax(120px, 1fr) auto; align-items: center; gap: .75rem; padding: .48rem .85rem; border-bottom: 1px solid color-mix(in srgb, var(--line) 75%, transparent); text-decoration: none; }
  .failure-row:last-child { border-bottom: 0; }
  .failure-row:hover { background: var(--panel-soft); }
  .failure-message { overflow: hidden; color: var(--danger); font-family: "SFMono-Regular", Consolas, monospace; font-size: .58rem; text-overflow: ellipsis; white-space: nowrap; }
  .failure-row time { font-family: "SFMono-Regular", Consolas, monospace; font-size: .55rem; white-space: nowrap; }
  .overview-foot { display: flex; justify-content: space-between; gap: .6rem; color: var(--muted-dim); font-family: "SFMono-Regular", Consolas, monospace; font-size: .55rem; }
  .overview-foot span { display: inline-flex; align-items: center; gap: .3rem; }
  @media (max-width: 1050px) { .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 760px) {
    .overview-page { gap: .7rem; }
    .page-heading { align-items: flex-start; }
    .page-heading h1 { font-size: 1.42rem; }
    .heading-actions { flex-direction: column-reverse; align-items: flex-end; gap: .3rem; }
    .last-updated { display: none; }
    .summary-grid { gap: .45rem; }
    .metric-card { min-height: 92px; gap: .26rem; padding: .64rem; }
    .metric-value { font-size: 1.4rem; }
    .metric-value.metric-name { font-size: .86rem; }
    .metric-label, .metric-foot { font-size: .51rem; }
    .overview-columns { grid-template-columns: 1fr; gap: .65rem; }
    .failure-row { grid-template-columns: minmax(0, 1fr) auto; gap: .24rem .55rem; padding: .55rem .68rem; }
    .failure-row .row-main { grid-column: 1; }
    .failure-message { grid-column: 1; }
    .failure-row time { grid-column: 2; grid-row: 1 / span 2; }
    .overview-foot { flex-direction: column; }
  }
</style>
