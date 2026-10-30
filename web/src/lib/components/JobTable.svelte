<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal, Toast } from 'flowbite-svelte';
  import { AlertTriangle, ClipboardList, Copy, Download, FileText, RefreshCw, SquareTerminal, XCircle } from '@lucide/svelte';
  import { api, post } from '$lib/api';
  import { formatBytes, formatDate, jobMessage, resultEntries, textValue } from '$lib/presentation';
  import { formatDuration, normalizeJobProgress, phaseLabel } from '$lib/job-progress';
  import { operatorTdlLogText } from '$lib/tdl-lanes';
  import JobProgressCard from './JobProgressCard.svelte';

  type Job = Record<string, any>;
  type JobEvent = Record<string, any>;
  type PollingMode = 'active' | 'activity';
  let { kind = '', title = 'Aktivitas terbaru', worker = '', profile = '', scope = 'current', status = '', quickMode = false, retryable = false, view = 'all', pollingMode = 'active' }: { kind?: string; title?: string; worker?: string; profile?: string; scope?: 'current'|'global'; status?: string; quickMode?: boolean; retryable?: boolean; view?: 'all'|'active'|'history'; pollingMode?: PollingMode } = $props();
  let jobs = $state<Job[]>([]);
  let monitorMetrics = $state<Record<string, any> | null>(null);
  let error = $state('');
  let selected = $state<Job | null>(null);
  let events = $state<JobEvent[]>([]);
  let reportOpen = $state(false);
  let logOpen = $state(false);
  let confirmOpen = $state(false);
  let confirmTarget = $state<'one'|'all'>('one');
  let detailTab = $state<'summary'|'milestones'|'raw'>('summary');
  let loadingEvents = $state(false);
  let liveLog = $state<Record<string, any> | null>(null);
  let toastOpen = $state(false);
  let toastMessage = $state('');
  let retrying = $state<Record<string, boolean>>({});
  let reconciling = $state<Record<string, boolean>>({});
  let jobActionPending = $state<Record<string, boolean>>({});
  let lastRefreshed = $state<Date | null>(null);
  let mounted = false;
  let loadGeneration = 0;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let hasLoaded = false;

  const activeStates = ['queued', 'dispatched', 'running', 'paused'];
  const active = (job: Job) => activeStates.includes(job.status);
  const activeJobs = $derived(jobs.filter(active).sort((left, right) => {
    // Progress updates change updated_at, which must not move cards on each
    // poll. Keep active jobs in FIFO creation order with a deterministic tie-break.
    const leftCreatedAt = Date.parse(String(left.created_at || ''));
    const rightCreatedAt = Date.parse(String(right.created_at || ''));
    if (Number.isFinite(leftCreatedAt) && Number.isFinite(rightCreatedAt) && leftCreatedAt !== rightCreatedAt) {
      return leftCreatedAt - rightCreatedAt;
    }
    if (Number.isFinite(leftCreatedAt) !== Number.isFinite(rightCreatedAt)) {
      return Number.isFinite(leftCreatedAt) ? -1 : 1;
    }
    return String(left.id || '').localeCompare(String(right.id || ''));
  }));
  const historyJobs = $derived(jobs.filter((job) => !active(job)));
  const newestFirst = (items: JobEvent[]) => [...items].sort((left, right) => Number(right.sequence || 0) - Number(left.sequence || 0));
  const operatorEvent = (event: JobEvent): JobEvent => {
    const result = event.result && typeof event.result === 'object'
      ? { ...event.result }
      : event.result;
    if (Array.isArray(result?.command)) result.command = result.command.map(operatorTdlLogText);
    if (Array.isArray(result?.output_tail)) result.output_tail = result.output_tail.map(operatorTdlLogText);
    return {
      ...event,
      result,
      progress: event.progress && typeof event.progress === 'object'
        ? { ...event.progress, message: operatorTdlLogText(String(event.progress.message || '')) }
        : event.progress,
      error: event.error && typeof event.error === 'object'
        ? { ...event.error, message: operatorTdlLogText(String(event.error.message || '')) }
        : event.error
    };
  };
  const milestones = $derived(newestFirst(events.filter((event) => !['log.snapshot', 'progress.snapshot'].includes(event.event_type))).map(operatorEvent));
  const latestSnapshot = $derived(newestFirst(events.filter((event) => event.event_type === 'log.snapshot' && Array.isArray(event.result?.log?.lines)))[0]);
  const liveLogLines = $derived(liveLog?.log?.lines);
  const rawLogLines = $derived(Array.isArray(liveLogLines) && liveLogLines.length ? liveLogLines : latestSnapshot?.result?.log?.lines || []);
  const logLines = $derived(
    (liveLog?.log?.order || latestSnapshot?.result?.log?.order) === 'newest_first'
      ? rawLogLines
      : [...rawLogLines].reverse()
  );
  const selectedProgress = $derived(selected ? normalizeJobProgress(selected) : null);

  function formatClock(d: Date | null): string {
    if (!d) return '-';
    return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function ttsTitle(job: Job): string {
    const title = job.payload?.title;
    return typeof title === 'string' && title.trim() ? title.trim() : 'Judul tidak tersedia';
  }

  function workerStatusLabel(status: string): string {
    return ({ busy: 'sibuk', stale: 'heartbeat terlambat', paused: 'dijeda', queued: 'antre', idle: 'idle', disabled: 'nonaktif' } as Record<string, string>)[status] || status;
  }

  function storageStatusLabel(status: string): string {
    return ({
      succeeded: 'Berhasil', failed: 'Gagal', pending: 'Menunggu', sending: 'Mengirim',
      needs_reconciliation: 'Perlu verifikasi', deleted: 'Dihapus',
      retained_conflict: 'Disimpan · target bentrok', retained_ambiguous: 'Disimpan · hasil belum pasti',
      retained_upload_failed: 'Disimpan · upload gagal', retained_unverified: 'Disimpan · belum terverifikasi',
      skipped_source_changed: 'Dilewati · sumber berubah', cleanup_failed: 'Gagal menghapus',
      retained_unsafe_path: 'Disimpan · path tidak aman'
    } as Record<string, string>)[status] || status;
  }

  function stopPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    pollTimer = undefined;
  }

  function schedulePolling() {
    stopPolling();
    if (!mounted || view === 'history') return;
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
    const delay = pollingMode === 'activity'
      ? activeJobs.length ? 2500 : 10_000
      : activeJobs.length ? 2500 : undefined;
    if (delay === undefined) return;
    pollTimer = setTimeout(() => { void load({ scheduled: true }); }, delay);
  }

  async function load({ scheduled = false }: { scheduled?: boolean } = {}) {
    if (!scheduled) stopPolling();
    const request = ++loadGeneration;
    const previousActiveIds = new Set(jobs.filter(active).map((job) => String(job.id)));
    try {
      const params = new URLSearchParams({ limit: '30', scope });
      if (profile) params.set('profile', profile);
      if (worker) params.set('worker', worker);
      if (view === 'active') {
        params.set('status', 'queued,dispatched,running,paused');
      } else if (view === 'history') {
        params.set('status', status || 'succeeded,failed,cancelled');
      } else if (status) {
        params.set('status', status);
      }
      if (quickMode) params.set('quick_mode', 'true');
      const kinds = kind === 'storage_upload' ? ['storage_upload', 'storage_reconcile'] : kind ? [kind] : [''];
      const jobRequests = kinds.map((selectedKind) => {
        const selectedParams = new URLSearchParams(params);
        if (selectedKind) selectedParams.set('kind', selectedKind);
        return api<{items:Job[]}>(`/jobs?${selectedParams.toString()}`);
      });
      const metricsParams = new URLSearchParams({ scope });
      if (profile) metricsParams.set('profile', profile);
      if (worker) metricsParams.set('worker', worker);
      const shouldRefreshMetrics = view !== 'history' && (!scheduled || pollingMode === 'activity');
      const [jobResponses, nextMetrics] = await Promise.all([
        Promise.all(jobRequests),
        !shouldRefreshMetrics
          ? Promise.resolve(undefined)
          : api<Record<string, any>>(`/jobs/metrics?${metricsParams.toString()}`).catch(() => null)
      ]);
      const next = jobResponses.flatMap((response) => response.items || [])
        .sort((left, right) => Date.parse(String(right.created_at || '')) - Date.parse(String(left.created_at || '')))
        .slice(0, 30);
      if (request !== loadGeneration) return;
      jobs = next;
      if (nextMetrics !== undefined) monitorMetrics = nextMetrics;
      lastRefreshed = new Date();
      if (selected) selected = next.find((job) => job.id === selected?.id) || selected;
      if (view === 'active' && hasLoaded) {
        const currentActiveIds = new Set(next.filter(active).map((job) => String(job.id)));
        const finished = [...previousActiveIds].filter((id) => !currentActiveIds.has(id));
        if (finished.length && typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('tme3:job-finished', { detail: { jobIds: finished } }));
        }
      }
      hasLoaded = true;
      error = '';
      schedulePolling();
    } catch (cause) {
      if (request !== loadGeneration) return;
      error = cause instanceof Error ? cause.message : 'Tidak dapat memuat job.';
      schedulePolling();
    }
  }
  async function loadEvents() {
    if (!selected) return;
    const jobId = selected.id;
    loadingEvents = true;
    try {
      const [job, eventResponse, snapshot] = await Promise.all([
        api<Job>(`/jobs/${jobId}`),
        api<{items:JobEvent[]}>(`/jobs/${jobId}/events?after_sequence=0`),
        api<Record<string, any>>(`/jobs/${jobId}/log-snapshot`).catch(() => null)
      ]);
      if (selected?.id !== jobId) return;
      selected = job;
      events = eventResponse.items || [];
      liveLog = snapshot;
    }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Tidak dapat memuat event.'; }
    finally { loadingEvents = false; }
  }
  async function openReport(job: Job) { selected = job; events = []; liveLog = null; detailTab = 'summary'; reportOpen = true; await loadEvents(); }
  async function openLog(job: Job) { selected = job; events = []; liveLog = null; logOpen = true; await loadEvents(); }
  function requestTerminate(target: 'one'|'all', job?: Job) { if (job) selected = job; confirmTarget = target; confirmOpen = true; }
  function hasAmbiguousStorageFiles(job: Job): boolean {
    if (job.payload?.provider === 'rclone') return false;
    const items = job.result?.value?.items || job.result?.items;
    return Array.isArray(items) && items.some((item) => item?.status === 'needs_reconciliation');
  }
  async function terminate() {
    try {
      if (confirmTarget === 'all') {
        const params = new URLSearchParams();
        if (scope === 'global') params.set('scope', 'global');
        if (kind) params.set('kind', kind);
        if (quickMode) { params.set('kind', 'export'); params.set('quick_mode', 'true'); }
        const query = params.toString();
        await post(`/jobs/terminate-active${query ? `?${query}` : ''}`);
      }
      else if (selected) await post(`/jobs/${selected.id}/cancel`);
      toastMessage = confirmTarget === 'all' ? 'Terminate dikirim ke semua job aktif.' : 'Terminate dikirim ke job.';
      toastOpen = true; confirmOpen = false; await load();
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Job gagal dihentikan.'; }
  }
  async function retry(job: Job) {
    const quick = Boolean(job.payload?.quick_mode);
    const tts = job.kind === 'tts';
    const storage = job.kind === 'storage_upload';
    const confirmation = storage
      ? 'Retry hanya mengirim file yang dipastikan belum diterima Telegram. File dengan hasil ambigu tidak ikut dikirim. Lanjutkan?'
      : tts ? 'Kirim ulang audio TTS ke chat tujuan?' : quick ? 'Jalankan ulang Quick Mode dari export awal?' : 'Jalankan ulang export dari awal?';
    if ((storage || job.status === 'succeeded') && !window.confirm(confirmation)) return;
    retrying = { ...retrying, [job.id]: true };
    try {
      await post(tts ? `/tts/jobs/${encodeURIComponent(job.id)}/retry` : `/jobs/${encodeURIComponent(job.id)}/retry`);
      toastMessage = job.status === 'succeeded'
        ? (storage ? 'Retry upload Storage masuk antrean.' : tts ? 'Kirim ulang TTS masuk antrean.' : quick ? 'Quick Mode baru masuk antrean.' : 'Export baru masuk antrean.')
        : (storage ? 'Retry upload Storage masuk antrean.' : tts ? 'Retry TTS masuk antrean.' : quick ? 'Retry Quick Mode masuk antrean.' : 'Retry export masuk antrean.');
      toastOpen = true;
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Retry job gagal dibuat.';
    } finally {
      const next = { ...retrying };
      delete next[job.id];
      retrying = next;
    }
  }
  async function reconcile(job: Job) {
    reconciling = { ...reconciling, [job.id]: true };
    try {
      await post(`/jobs/${encodeURIComponent(job.id)}/reconcile`);
      toastMessage = 'Rekonsiliasi caption Storage masuk antrean.';
      toastOpen = true;
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Rekonsiliasi Storage gagal dibuat.';
    } finally {
      const next = { ...reconciling };
      delete next[job.id];
      reconciling = next;
    }
  }
  async function togglePause(job: Job) {
    jobActionPending = { ...jobActionPending, [job.id]: true };
    try {
      await post(`/jobs/${encodeURIComponent(job.id)}/${job.status === 'paused' ? 'resume' : 'pause'}`);
      toastMessage = job.status === 'paused' ? 'Job masuk kembali ke antrean.' : job.kind === 'tts' ? 'TTS akan dijeda setelah batch aktif selesai.' : 'Job Quick Mode dijeda.';
      toastOpen = true;
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Kontrol pause/resume gagal.';
    } finally {
      const next = { ...jobActionPending };
      delete next[job.id];
      jobActionPending = next;
    }
  }
  async function copy(value: string) { await navigator.clipboard?.writeText(value); toastMessage = 'Disalin ke clipboard.'; toastOpen = true; }
  function backupVerificationReport(job: Job | null) {
    const result = job?.result?.value || job?.result || {};
    const report = result?.report;
    return job?.kind === 'backup_verify' && report && typeof report === 'object' ? report : null;
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
  const eventLine = (event: JobEvent) => {
    const batch = event.progress?.batch;
    const item = event.progress?.item;
    const position = batch?.index ? `JSON ${batch.index}/${batch.total || '?'} ${batch.name || ''}` : '';
    const media = item?.index ? `File ${item.index}/${item.total || '?'} ${item.name || ''}` : '';
    const detail = [position, media, event.progress?.message || event.error?.message || event.result?.status].filter(Boolean).join(' · ');
    return operatorTdlLogText(`#${event.sequence} [${event.status}] ${event.event_type}: ${textValue(detail, 'Event tercatat')}`);
  };
  const informativeEvents = $derived(newestFirst(events.filter((event) =>
    event.event_type.startsWith('download.')
    || event.event_type === 'artifact.missing'
    || (!logLines.length && !['log.snapshot', 'progress.snapshot'].includes(event.event_type))
  )).map(eventLine));
  const displayLogLines = $derived([
    ...informativeEvents,
    ...(informativeEvents.length && logLines.length ? ['──────── raw worker output ────────'] : []),
    ...logLines.map(operatorTdlLogText)
  ]);
  onMount(() => {
    mounted = true;
    const refresh = () => { if (view !== 'history') load(); };
    const jobFinished = () => { if (view === 'history') load(); };
    const contextRefresh = () => {
      loadGeneration += 1;
      jobs = [];
      monitorMetrics = null;
      selected = null;
      events = [];
      liveLog = null;
      reportOpen = false;
      logOpen = false;
      void load();
    };
    const visibilityChanged = () => {
      if (document.visibilityState !== 'visible') {
        stopPolling();
        return;
      }
      if (pollingMode === 'activity' || activeJobs.length) void load();
    };
    window.addEventListener('tme3:data-mutated', refresh);
    window.addEventListener('tme3:context-changed', contextRefresh);
    window.addEventListener('tme3:job-finished', jobFinished);
    document.addEventListener('visibilitychange', visibilityChanged);
    void load();
    return () => {
      mounted = false;
      stopPolling();
      window.removeEventListener('tme3:data-mutated', refresh);
      window.removeEventListener('tme3:context-changed', contextRefresh);
      window.removeEventListener('tme3:job-finished', jobFinished);
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  });
</script>

<section class="card mt-7 overflow-hidden">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-4 sm:px-5">
    <div><p class="eyebrow">{view === 'history' ? 'HISTORY' : 'JOB MONITOR'}</p><h2 class="mt-1 text-lg font-extrabold">{title}</h2></div>
    <div class="flex flex-wrap items-center gap-2">
      {#if view === 'history'}
        <span class="muted text-xs">Refresh manual atau saat job selesai</span>
      {:else if pollingMode === 'activity'}
        <span class="badge running">Live · 2,5 dtk aktif / 10 dtk idle</span>
      {:else if activeJobs.length}
        <span class="badge running">Progress otomatis · job aktif</span>
      {:else}
        <span class="muted text-xs">Refresh manual</span>
      {/if}
      {#if lastRefreshed}
        <span class="muted text-xs">Terakhir diperbarui: {formatClock(lastRefreshed)}</span>
      {/if}
      {#if view !== 'history'}<button class="button danger" onclick={() => requestTerminate('all')}><XCircle size={16}/>Terminate semua aktif</button>{/if}
      <button class="button secondary" onclick={() => { void load(); }} aria-label={view === 'active' ? 'Refresh monitor' : 'Refresh daftar job'}><RefreshCw size={16}/>Refresh</button>
    </div>
  </div>
  {#if error}<p class="m-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}

  {#if view !== 'history' && monitorMetrics}
    <div class="border-b border-[var(--line)] px-4 py-3 sm:px-5">
      <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] px-3 py-2"><small class="muted">Aktif · dispatch / running</small><b class="mt-1 block text-sm">{monitorMetrics.active_jobs || 0} job</b></div>
        <div class="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] px-3 py-2"><small class="muted">Antrean</small><b class="mt-1 block text-sm">{monitorMetrics.queued_jobs || 0} job</b></div>
        <div class="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] px-3 py-2"><small class="muted">Rata-rata waktu tunggu · 24 jam</small><b class="mt-1 block text-sm">{monitorMetrics.average_queue_wait_seconds != null ? formatDuration(monitorMetrics.average_queue_wait_seconds) : 'Belum ada data'}</b></div>
        <div class="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] px-3 py-2"><small class="muted">Latensi event worker</small><b class="mt-1 block text-sm">{monitorMetrics.event_latency?.average_ms != null ? `${Math.round(monitorMetrics.event_latency.average_ms)} ms · ${monitorMetrics.event_latency.count} event` : 'Belum ada data'}</b></div>
      </div>
      {#if monitorMetrics.workers?.length}
        <div class="mt-2 flex flex-wrap gap-2" aria-label="Status worker">
          {#each monitorMetrics.workers as item (item.worker)}
            <span class={`rounded-full border px-2.5 py-1 text-xs font-semibold ${item.status === 'stale' ? 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200' : item.status === 'disabled' ? 'border-slate-300 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300' : 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'}`} title={item.last_seen_at ? `Event terakhir ${item.last_seen_age_seconds ?? '?'} detik lalu` : 'Belum ada event worker'}>
              {item.worker} · {workerStatusLabel(item.status)} · {item.active_jobs} aktif · {item.queued_jobs} antre
            </span>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  {#if view !== 'history' && activeJobs.length}
    <div class="border-b border-[var(--line)] bg-[var(--brand-soft)]/20 p-4 sm:p-5">
      <div class="mb-3 flex items-center justify-between"><h3 class="font-extrabold">Sedang berjalan</h3><span class="badge running">{activeJobs.length} aktif / antre</span></div>
      <div class="space-y-2.5">
        {#each activeJobs as job (job.id)}
          <JobProgressCard job={job} onReport={() => openReport(job)} onLog={() => openLog(job)} onTerminate={() => requestTerminate('one', job)} onPauseToggle={(job.kind === 'tts' || (quickMode && job.payload?.quick_mode)) ? () => togglePause(job) : undefined} actionPending={Boolean(jobActionPending[job.id])}/>
        {/each}
      </div>
    </div>
  {/if}

  {#if view !== 'active' && historyJobs.length}<div class="px-4 pt-4 sm:px-5"><h3 class="text-sm font-extrabold">History terbaru</h3></div>{/if}
  <div class="divide-y divide-[var(--line)] px-4 sm:px-5">
    {#each (view === 'active' ? [] : historyJobs) as job (job.id)}
      {@const stageId = job.payload?.quick_retry?.stage_job_id || (job.payload?.quick_mode ? job.id : null)}
      <article class="grid gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div class="min-w-0">
          {#if job.kind === 'tts'}
            <h3 class="mb-1 break-words text-base font-bold leading-snug text-slate-900 dark:text-slate-100" style="overflow-wrap:anywhere" title={ttsTitle(job)}>{ttsTitle(job)}</h3>
          {/if}
          <div class="flex flex-wrap items-center gap-2">
            {#if job.id}
              <span class="font-mono text-xs font-semibold text-slate-500" title="Job ID: {job.id}">#{job.id.slice(0, 8)}</span>
            {/if}
            <b class="capitalize">{job.kind === 'tts' ? 'TTS' : job.kind === 'storage_reconcile' ? 'Storage reconcile' : job.kind.replaceAll('_',' ')}</b>
            {#if job.payload?.quick_mode}<span class="badge running">Quick Mode</span>{/if}
            {#if stageId}
              <span class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300" title="Staging folder: {stageId}">📁 {String(stageId).slice(0, 8)}</span>
            {/if}
            <span class={`badge ${job.status}`}>{job.status}</span>
            <span class="muted text-xs">{job.worker || '-'}</span>
          </div>
          <p class="muted mt-1 truncate text-sm">{jobMessage(job)}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <small class="muted mr-auto whitespace-nowrap lg:mr-0">{formatDate(job.updated_at)}</small>
          <button class="button secondary" onclick={() => openReport(job)}><FileText size={15}/>Report</button>
          <button class="button secondary" onclick={() => openLog(job)}><SquareTerminal size={15}/>Log</button>
          {#if job.kind === 'storage_upload' && ['failed','cancelled'].includes(job.status) && hasAmbiguousStorageFiles(job)}
            <button class="button secondary" onclick={() => reconcile(job)} disabled={reconciling[job.id]}><RefreshCw size={15} class={reconciling[job.id] ? 'animate-spin' : ''}/>Rekonsiliasi</button>
          {/if}
          {#if retryable && ['export','tts'].includes(job.kind) && ['failed','cancelled','succeeded'].includes(job.status)}
            <button class="button secondary" onclick={() => retry(job)} disabled={retrying[job.id]}><RefreshCw size={15} class={retrying[job.id] ? 'animate-spin' : ''}/>{job.status === 'succeeded' ? 'Jalankan lagi' : 'Retry'}</button>
          {/if}
          {#if retryable && job.kind === 'storage_upload' && job.retryable && ['failed','cancelled'].includes(job.status)}
            <button class="button secondary" onclick={() => retry(job)} disabled={retrying[job.id]}><RefreshCw size={15} class={retrying[job.id] ? 'animate-spin' : ''}/>Retry file aman</button>
          {/if}
        </div>
      </article>
    {/each}
    {#if !historyJobs.length && !activeJobs.length}<div class="py-14 text-center"><ClipboardList class="mx-auto mb-2 text-violet-500"/><b>{view === 'active' ? 'Tidak ada job yang sedang berjalan atau antri.' : 'Belum ada job.'}</b></div>{/if}
  </div>
</section>

<Modal bind:open={reportOpen} title={selected ? `Detail ${selected.kind.replaceAll('_',' ')}` : 'Detail job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex max-h-[78dvh] min-h-0 flex-col">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] bg-[var(--brand-soft)] px-4 py-3"><div><div class="flex flex-wrap gap-2"><span class={`badge ${selected.status}`}>{selected.status}</span><span class="muted text-sm">{selected.profile} · {selected.worker}</span>{#if selected.kind==='storage_upload'}<span class="badge">{selected.payload?.provider || 'telegram'}</span><span class="muted text-sm">{selected.payload?.provider==='rclone'?`Tujuan rclone: ${selected.payload?.rclone_destination || 'root'}${selected.payload?.rclone_path?`/${selected.payload.rclone_path}`:''}`:`Tujuan Telegram: ${selected.payload?.destination_folder_path || 'My Drive'}`}</span><span class="muted text-sm">{selected.payload?.transfer_mode || 'copy'}</span>{/if}</div><p class="mt-2 font-mono text-xs">{selected.id}</p></div>{#if backupVerificationReport(selected)}<button class="button secondary" onclick={() => downloadBackupVerificationReport(selected!)}><Download size={15}/>Unduh JSON verifikasi</button>{/if}</div>
    <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      <div class="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-[var(--brand-soft)] p-1">
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'summary' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'summary'}>Ringkasan</button>
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'milestones' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'milestones'}>Milestone</button>
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'raw' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'raw'}>Raw JSON</button>
      </div>
      {#if detailTab === 'summary'}
        {@const utilityResult = selected.result?.value || selected.result || {}}
        {#if selected.kind === 'utility' && selected.payload?.utility === 'extract' && Array.isArray(utilityResult.archive_results)}
          <section class="record-card mb-4">
            <h3 class="font-bold">Hasil Extract per arsip</h3>
            <p class="muted mt-1 text-sm">{utilityResult.summary?.archives_succeeded || 0} berhasil · {utilityResult.summary?.archives_failed || 0} gagal</p>
            <div class="mt-2 space-y-2">
              {#each utilityResult.archive_results as item, index (`${item.folder || ''}:${item.path || item.name || index}`)}
                <article class="rounded-lg border border-[var(--line)] p-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <b class="break-all text-sm">{item.name || `Arsip ${index + 1}`}</b>
                    <span class={`badge ${item.status === 'succeeded' ? 'succeeded' : 'failed'}`}>{item.status === 'succeeded' ? 'Berhasil' : 'Gagal'}</span>
                    <span class="muted text-xs">{item.pass === 'retry' ? 'Retry pool' : 'Password awal'} · {item.attempt_count || 0} percobaan</span>
                    {#if item.cleanup_status === 'failed'}<span class="text-xs font-semibold text-amber-700">Hasil diekstrak, arsip sumber belum terhapus</span>{/if}
                  </div>
                  {#if item.error}<p class="mt-1 break-words text-sm text-rose-700">{item.error}</p>{/if}
                </article>
              {/each}
            </div>
          </section>
        {/if}
        {#if selected.kind === 'utility' && selected.payload?.utility === 'flatten' && selected.payload?.flatten_action === 'preview' && Array.isArray(utilityResult.details)}
          <section class="record-card mb-4">
            <h3 class="font-bold">Preview Flatten tersimpan</h3>
            <p class="muted mt-1 text-sm">{utilityResult.summary?.moves || 0} pindah · {utilityResult.summary?.deleted || 0} hapus · {utilityResult.summary?.skipped || 0} dilewati</p>
            {#each utilityResult.details as detail}
              <article class="mt-3 rounded-lg border border-[var(--line)] p-3">
                <h4 class="break-all font-mono text-xs font-bold">{detail.folder}</h4>
                {#each detail.flatten_preview?.passes || [] as pass}
                  <p class="muted mt-2 text-xs font-semibold">Putaran {pass.index}</p>
                  <ul class="mt-1 space-y-1 text-sm">
                    {#each pass.actions || [] as action, index (`${pass.index}:${index}`)}
                      <li>{action.type === 'delete_empty' ? `Hapus folder kosong: ${action.folder}` : action.type === 'move' ? `Pindah ${action.source} → ${action.destination}${action.collision ? ' · nama bentrok, diberi prefix' : ''}` : `Lewati ${action.folder} (${action.item_count} item)`}</li>
                    {/each}
                  </ul>
                {/each}
              </article>
            {/each}
          </section>
        {/if}
        {#if selected.kind === 'storage_upload' && Array.isArray(selected.result?.value?.items || selected.result?.items)}
          {@const storageItems = selected.result?.value?.items || selected.result?.items || []}
          <section class="record-card mb-4">
            <h3 class="font-bold">Hasil per file</h3>
            <div class="mt-2 space-y-2">
              {#each storageItems as item, index (item.path || index)}
                <article class="rounded-lg border border-[var(--line)] p-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <b class="break-all text-sm">{item.name || item.path || `File ${index + 1}`}</b>
                    <span class={`badge ${item.status === 'succeeded' ? 'succeeded' : item.status === 'needs_reconciliation' || item.status === 'failed' ? 'failed' : 'queued'}`}>{storageStatusLabel(item.status || 'unknown')}</span>
                    {#if item.upload_status}<span class="muted text-xs">Upload: {storageStatusLabel(item.upload_status)}</span>{/if}
                    {#if item.cleanup_status && item.cleanup_status!=='not_requested'}<span class={`text-xs font-semibold ${item.cleanup_status==='deleted'?'text-emerald-700':'text-amber-700'}`}>Sumber: {storageStatusLabel(item.cleanup_status)}</span>{/if}
                    {#if item.profile}<span class="muted text-xs">Upload {item.profile}</span>{/if}
                    <span class="muted text-xs">Percobaan {item.attempt || 0}</span>
                    {#if item.retryable}<span class="text-xs font-semibold text-amber-700">Bisa diulang dengan aman</span>{/if}
                  </div>
                  {#if item.error}<p class="mt-1 break-words text-sm text-rose-700">{item.error}</p>{/if}
                  {#if item.attempts?.length}
                    <details class="mt-2">
                      <summary class="muted cursor-pointer text-xs">Riwayat percobaan ({item.attempts.length})</summary>
                      <ul class="mt-1 space-y-1 text-xs">
                        {#each item.attempts as attempt}
                          <li>{attempt.attempt} · {attempt.profile || 'tanpa lane'} · {attempt.status}{#if attempt.error_code} · {attempt.error_code}{/if}</li>
                        {/each}
                      </ul>
                    </details>
                  {/if}
                </article>
              {/each}
            </div>
          </section>
        {/if}
        {#if selected.kind === 'storage_reconcile' && Array.isArray(selected.result?.value?.items || selected.result?.items)}
          {@const reconciliationItems = selected.result?.value?.items || selected.result?.items || []}
          <section class="record-card mb-4">
            <h3 class="font-bold">Hasil rekonsiliasi caption</h3>
            <p class="muted mt-1 text-sm">Job sumber: #{String(selected.payload?.source_job_id || '').slice(0, 8)} · tidak menampilkan caption atau path lokal.</p>
            <div class="mt-2 space-y-2">
              {#each reconciliationItems as item, index (item.index ?? index)}
                <article class="rounded-lg border border-[var(--line)] p-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <b class="break-all text-sm">{item.name || `File ${index + 1}`}</b>
                    <span class={`badge ${item.status === 'succeeded' ? 'succeeded' : item.status === 'needs_reconciliation' ? 'failed' : 'queued'}`}>{item.status || 'unknown'}</span>
                    {#if item.profile}<span class="muted text-xs">Upload {item.profile}</span>{/if}
                    <span class="muted text-xs">Caption cocok: {item.match_count || 0}</span>
                    {#if item.retryable}<span class="text-xs font-semibold text-amber-700">Aman untuk Retry</span>{/if}
                  </div>
                  {#if item.error}<p class="mt-1 break-words text-sm text-rose-700">{item.error}</p>{/if}
                </article>
              {/each}
            </div>
          </section>
        {/if}
        {#if active(selected) && selectedProgress}
          <div class="mb-4 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-3.5 sm:p-4">
            <div class="mb-2 flex justify-between gap-2 text-xs">
              <b>Progress ({phaseLabel(selectedProgress.phase)})</b>
              <span class="font-mono">{selectedProgress.overall.current ?? 0}{selectedProgress.overall.total ? ` / ${selectedProgress.overall.total}` : ''} ({selectedProgress.overall.percent !== undefined ? `${selectedProgress.overall.percent.toFixed(1)}%` : selectedProgress.item.percent !== undefined ? `${selectedProgress.item.percent.toFixed(1)}%` : '...'})</span>
            </div>
            <div class={`progress-track !h-2.5 ${selectedProgress.indeterminate ? 'indeterminate' : ''}`}>
              <div class="progress-fill" style={`width:${selectedProgress.overall.percent ?? selectedProgress.item.percent ?? 0}%`}></div>
            </div>
          </div>
        {/if}
        <div class="grid gap-3 sm:grid-cols-2"><div class="record-card sm:col-span-2"><p class="muted text-xs font-bold uppercase">Pesan akhir</p><p class="mt-1 font-semibold">{jobMessage(selected)}</p></div><div class="record-card"><p class="muted text-xs font-bold uppercase">Mulai</p><p class="mt-1 break-words text-sm font-semibold">{formatDate(selected.started_at || selected.created_at)}</p></div><div class="record-card"><p class="muted text-xs font-bold uppercase">Selesai</p><p class="mt-1 break-words text-sm font-semibold">{selected.finished_at ? formatDate(selected.finished_at) : 'Masih berjalan'}</p></div>{#if selected.export_start_id || selected.export_end_id}<div class="record-card"><p class="muted text-xs font-bold uppercase">Rentang message ID</p><p class="mt-1 break-words text-sm font-semibold">{selected.export_start_id || '?'} – {selected.export_end_id || '?'}</p></div>{/if}{#if selected.progress?.staging_path && !selected.progress?.staging_cleaned}<div class="record-card border-amber-200 bg-amber-50 sm:col-span-2 dark:border-amber-900 dark:bg-amber-950"><p class="muted text-xs font-bold uppercase">Staging untuk diagnosis/retry</p><p class="mt-1 break-all font-mono text-xs font-semibold">{selected.progress.staging_path}</p></div>{/if}{#each resultEntries(selected.result?.value || selected.result) as [key,value]}<div class="record-card"><p class="muted text-xs font-bold uppercase">{key.replaceAll('_',' ')}</p><p class="mt-1 break-words text-sm font-semibold">{value}</p></div>{/each}{#if selected.error}<div class="record-card border-rose-200 bg-rose-50 sm:col-span-2 dark:border-rose-900 dark:bg-rose-950"><b class="text-rose-600">Error</b><p class="mt-1 break-words text-sm">{textValue(selected.error?.message || selected.error)}</p></div>{/if}</div>
      {:else if detailTab === 'milestones'}
        <div class="space-y-2">{#each milestones as event}<article class="record-card"><div class="flex flex-wrap justify-between gap-2"><div><span class={`badge ${event.status}`}>{event.status}</span><b class="ml-2 text-sm">{event.event_type.replaceAll('_',' ')}</b></div><small class="muted">#{event.sequence} · {formatDate(event.created_at)}</small></div>{#if event.event_type === 'command.started' || event.event_type === 'command.completed'}<p class="mt-2 break-all font-mono text-xs">$ {(event.result?.command || []).join(' ')}</p>{#if event.event_type === 'command.started'}<p class="muted mt-2 text-sm">Command dikirim, menunggu hasil...</p>{:else}{#if event.result?.output_tail?.length}<pre class="terminal mt-2 max-h-48 overflow-auto whitespace-pre-wrap p-3 text-xs">{event.result.output_tail.join('\n')}</pre>{/if}<p class="muted mt-2 text-xs">exit {event.result?.returncode ?? '?'} · {event.result?.duration_seconds ?? 0}s{event.result?.output_truncated ? ' · output lama dipangkas' : ''}</p>{/if}{:else}<p class="muted mt-2 text-sm">{event.progress?.message || event.error?.message || event.result?.status || 'Milestone tercatat.'}</p>{/if}</article>{:else}<p class="muted py-8 text-center">Belum ada milestone.</p>{/each}</div>
      {:else}
        <div class="mb-2 flex justify-end"><button class="button secondary" onclick={() => copy(JSON.stringify({job:selected,events}, null, 2))}><Copy size={14}/>Salin</button></div><pre class="terminal max-h-[48dvh] overflow-auto p-4 text-xs">{JSON.stringify({job:selected,events}, null, 2)}</pre>
      {/if}
    </div>
    {#if active(selected)}<div class="shrink-0 border-t border-[var(--line)] p-3 text-right"><button class="button danger" onclick={() => requestTerminate('one', selected!)}><XCircle size={15}/>Terminate job</button></div>{/if}
  </div>{/if}
</Modal>

<Modal bind:open={logOpen} title={selected ? `Log ${selected.id.slice(0,12)}` : 'Log job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex h-[78dvh] min-h-0 flex-col bg-[#080d19] text-slate-100">
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-4 py-3"><div><b>{displayLogLines.length} baris</b>{#if liveLog?.log?.truncated || latestSnapshot?.result?.log?.truncated}<span class="ml-2 text-xs text-amber-300">log lama dipangkas · terbaru di atas</span>{/if}</div><div class="flex gap-2"><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={loadEvents} disabled={loadingEvents}><RefreshCw class={loadingEvents ? 'animate-spin' : ''} size={15}/>Refresh</button><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={() => copy(displayLogLines.join('\n'))}><Copy size={15}/>Copy</button></div></div>
    {#if selectedProgress}<div class="grid shrink-0 gap-2 border-b border-slate-700 bg-slate-900/80 p-3 text-xs sm:grid-cols-4">
      <div class="rounded-lg border border-slate-700 p-2"><span class="text-slate-400">JSON</span><b class="mt-1 block truncate text-white">{selectedProgress.batch.name || 'Menunggu JSON'}</b><span class="text-violet-300">{selectedProgress.batch.index ? `${selectedProgress.batch.index}/${selectedProgress.batch.total || '?'}` : '-'}</span></div>
      <div class="rounded-lg border border-slate-700 p-2"><span class="text-slate-400">File aktif</span><b class="mt-1 block truncate text-white">{selectedProgress.item.name || 'Menunggu media'}</b><span class="text-sky-300">{selectedProgress.item.index ? `${selectedProgress.item.index}/${selectedProgress.item.total || '?'}` : '-'}</span></div>
      <div class="rounded-lg border border-slate-700 p-2"><span class="text-slate-400">Speed</span><b class="mt-1 block text-white">{selectedProgress.transfer.speed_bps ? `${formatBytes(selectedProgress.transfer.speed_bps)}/dtk` : 'Menghitung...'}</b></div>
      <div class="rounded-lg border border-slate-700 p-2"><span class="text-slate-400">ETA</span><b class="mt-1 block text-white">{selectedProgress.transfer.eta_seconds !== undefined ? formatDuration(selectedProgress.transfer.eta_seconds) : 'Menghitung...'}</b></div>
    </div>{/if}
    <pre class="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-6 text-emerald-200">{displayLogLines.join('\n') || 'Snapshot log belum tersedia. Tekan Refresh untuk mencoba lagi.'}</pre>
  </div>{/if}
</Modal>

<Modal bind:open={confirmOpen} title={confirmTarget === 'all' ? 'Terminate semua job aktif?' : 'Terminate job ini?'} size="sm" permanent>
  <div class="flex gap-3"><AlertTriangle class="shrink-0 text-rose-600" size={23}/><p>Sinyal seperti Ctrl+C akan dikirim. Proses dapat membutuhkan beberapa saat untuk mengirim status terakhir.</p></div><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => confirmOpen = false}>Batal</button><button class="button danger" onclick={terminate}>Terminate</button></div>
</Modal>
<Toast bind:toastStatus={toastOpen} position="bottom-right" color="primary">{toastMessage}</Toast>
