<script lang="ts">
  import { formatBytes } from '$lib/presentation';
  import { formatDuration, normalizeJobProgress, phaseLabel } from '$lib/job-progress';
  import { ChevronDown, Clock3, FileText, Gauge, Pause, Play, SquareTerminal, Timer, XCircle } from '@lucide/svelte';

  let { job, onReport, onLog, onTerminate, onPauseToggle, actionPending = false }: {
    job: Record<string, any>;
    onReport: () => void;
    onLog: () => void;
    onTerminate: () => void;
    onPauseToggle?: () => void;
    actionPending?: boolean;
  } = $props();

  let expanded = $state(false);
  const progress = $derived(normalizeJobProgress(job));
  const overallPercent = $derived(progress.overall.percent);
  const itemPercent = $derived(progress.item.percent);
  const activePercent = $derived(overallPercent ?? itemPercent);
  const speed = $derived(progress.transfer.speed_bps ? `${formatBytes(progress.transfer.speed_bps)}/dtk` : progress.transfer.speed_text || 'Menghitung...');
  const headline = $derived(progress.batch.name || progress.item.name || progress.message);
  const elapsed = $derived(formatDuration(progress.elapsedSeconds ?? ((Date.now() - new Date(job.created_at).getTime()) / 1000)));
  const timing = $derived(job.progress?.timing || {});
  const observability = $derived(job.progress?.observability || {});
  const queueWaitSeconds = $derived(
    job.status === 'queued' && timing.queued_at
      ? Math.max(0, (Date.now() - Date.parse(timing.queued_at)) / 1000)
      : timing.queue_wait_seconds
  );
  const phaseElapsedSeconds = $derived(
    observability.phase_started_at && ['dispatched', 'running'].includes(job.status)
      ? Math.max(0, (Date.now() - Date.parse(observability.phase_started_at)) / 1000)
      : observability.phase_elapsed_seconds
  );
  const eventLatency = $derived(observability.event_latency?.average_ms);
  const stageId = $derived(job.payload?.quick_retry?.stage_job_id || (job.payload?.quick_mode ? job.id : null));
</script>

<article class="idm-row">
  <div class="p-3.5 sm:p-4">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <!-- Main Info & Progress Bar (IDM Style) -->
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          {#if job.id}
            <span class="font-mono text-xs font-semibold text-slate-500" title="Job ID: {job.id}">#{job.id.slice(0, 8)}</span>
          {/if}
          <span class={`badge ${job.status === 'paused' ? 'paused' : 'running'} shrink-0`}>{job.status === 'paused' ? 'Dijeda' : phaseLabel(progress.phase)}</span>
          {#if stageId}
            <span class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300" title="Staging folder: {stageId}">📁 {stageId.slice(0, 8)}</span>
          {/if}
          <b class="truncate text-sm font-extrabold text-[var(--ink)]">{headline}</b>
          {#if progress.batch.index}
            <span class="rounded bg-[var(--brand-soft)] px-1.5 py-0.5 text-xs font-bold text-[var(--brand)]">JSON {progress.batch.index}/{progress.batch.total || '?'}</span>
          {/if}
          {#if progress.item.index}
            <span class="rounded bg-sky-100 px-1.5 py-0.5 text-xs font-bold text-sky-800 dark:bg-sky-950 dark:text-sky-200">File {progress.item.index}/{progress.item.total || '?'}</span>
          {/if}
          <span class="muted hidden text-xs sm:inline">{job.profile} / {job.worker}</span>
        </div>

        <!-- Progress Bar, Percentage, Speed, ETA, Counters -->
        <div class="mt-2.5 flex flex-col gap-2 sm:flex-row sm:items-center">
          <div class="flex min-w-0 flex-1 items-center gap-2.5">
            <div class={`progress-track flex-1 !h-2.5 ${progress.indeterminate && activePercent === undefined ? 'indeterminate' : ''}`}>
              <div class="progress-fill" style={`width:${activePercent ?? 0}%`}></div>
            </div>
            <span class="w-12 shrink-0 text-right font-mono text-xs font-bold text-[var(--ink)]">
              {activePercent !== undefined ? `${activePercent.toFixed(1)}%` : '...'}
            </span>
          </div>

          <div class="flex flex-wrap items-center gap-3 text-xs font-semibold">
            <span class="flex items-center gap-1 text-[var(--muted)]" title="Kecepatan transfer">
              <Gauge size={13} class="text-[var(--brand)]"/>
              <b>{speed}</b>
            </span>
            <span class="flex items-center gap-1 text-[var(--muted)]" title="Estimasi waktu tersisa">
              <Timer size={13} class="text-[var(--brand)]"/>
              <b>{progress.transfer.eta_seconds !== undefined ? formatDuration(progress.transfer.eta_seconds) : 'Menghitung...'}</b>
            </span>
            <div class="flex items-center gap-1 font-mono text-[11px]">
              <span class="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300" title="Berhasil">
                ✓ <b>{progress.counters.succeeded}</b>
              </span>
              <span class="rounded bg-rose-100 px-1.5 py-0.5 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300" title="Gagal">
                ✕ <b>{progress.counters.failed}</b>
              </span>
            </div>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] font-semibold text-[var(--muted)]">
          {#if queueWaitSeconds !== undefined}<span>Antre {formatDuration(queueWaitSeconds)}</span>{/if}
          {#if phaseElapsedSeconds !== undefined && job.status !== 'queued'}<span>Fase ini {formatDuration(phaseElapsedSeconds)}</span>{/if}
          {#if eventLatency !== undefined}<span>Latensi event {Math.round(eventLatency)} ms</span>{/if}
        </div>
      </div>

      <!-- Compact Action Buttons -->
      <div class="flex shrink-0 items-center justify-between gap-2 border-t border-[var(--line)] pt-2 lg:border-t-0 lg:pt-0">
        <div class="flex items-center gap-1 text-xs text-[var(--muted)] lg:hidden">
          <Clock3 size={13}/>{elapsed}
        </div>
        <div class="flex items-center gap-2">
          {#if onPauseToggle}
            <button class={`button ${job.status === 'paused' ? '' : 'secondary'} !py-1.5 !px-3 text-xs`} onclick={onPauseToggle} disabled={actionPending || !['queued','dispatched','running','paused'].includes(job.status)} aria-label={job.status === 'paused' ? 'Lanjutkan job' : 'Jeda job'}>
              {#if job.status === 'paused'}<Play size={14}/><span>{actionPending ? 'Melanjutkan...' : 'Resume'}</span>{:else}<Pause size={14}/><span>{actionPending ? 'Menjeda...' : 'Pause'}</span>{/if}
            </button>
          {/if}
          <button class="button secondary !py-1.5 !px-3 text-xs" onclick={() => expanded = !expanded} aria-label="Toggle detail progress">
            <ChevronDown size={14} class={`transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}/>
            <span>{expanded ? 'Tutup' : 'Detail'}</span>
          </button>
          <button class="button secondary !py-1.5 !px-3 text-xs" onclick={onLog} aria-label="Buka log">
            <SquareTerminal size={14}/>
            <span>Log</span>
          </button>
          <button class="button danger !py-1.5 !px-3 text-xs" onclick={onTerminate} aria-label="Hentikan job">
            <XCircle size={14}/>
            <span>Stop</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Expandable Detail Drawer (Collapse) -->
  {#if expanded}
    <div class="border-t border-[var(--line)] bg-[var(--surface-soft)] p-4 sm:p-5">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <b class="text-xs font-extrabold uppercase tracking-wider text-[var(--muted)]">Detail Progress Job</b>
          {#if job.id}
            <span class="font-mono text-xs text-slate-500">#{job.id}</span>
          {/if}
          <span class="badge running">{job.kind.replaceAll('_',' ')}</span>
          {#if stageId}
            <span class="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">📁 Folder: {stageId}</span>
          {/if}
        </div>
        <div class="flex items-center gap-1 text-xs text-[var(--muted)]">
          <Clock3 size={13}/> Berjalan {elapsed}
        </div>
      </div>

      <!-- Overall Progress -->
      <div>
        <div class="mb-2 flex justify-between gap-3 text-xs">
          <b>Progress keseluruhan</b>
          <span class="muted font-mono">{progress.overall.current ?? 0}{progress.overall.total ? ` / ${progress.overall.total} ${progress.overall.unit || ''}` : ''}{overallPercent !== undefined ? ` (${overallPercent.toFixed(1)}%)` : ''}</span>
        </div>
        <div class={`progress-track ${progress.indeterminate && overallPercent === undefined ? 'indeterminate' : ''}`}>
          <div class="progress-fill" style={`width:${overallPercent ?? 0}%`}></div>
        </div>
      </div>

      <!-- Active File / Item Progress -->
      {#if progress.item.name}
        <div class="mt-4 rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3.5">
          <div class="flex justify-between gap-3 text-sm">
            <b class="min-w-0 truncate font-semibold">{progress.item.name}</b>
            <span class="muted shrink-0 text-xs">{progress.item.index ? `File ${progress.item.index}/${progress.item.total || '?'}` : ''}</span>
          </div>
          <div class={`progress-track mt-2.5 !h-2 ${progress.indeterminate && itemPercent === undefined ? 'indeterminate' : ''}`}>
            <div class="progress-fill" style={`width:${itemPercent ?? 0}%`}></div>
          </div>
          <div class="muted mt-2 flex flex-wrap justify-between gap-2 text-xs font-mono">
            <span>{progress.item.size_bytes ? formatBytes(progress.item.size_bytes) : 'Ukuran belum diketahui'}</span>
            <span>{itemPercent !== undefined ? `${itemPercent.toFixed(1)}%` : 'Sedang diproses'}</span>
          </div>
        </div>
      {/if}

      <!-- Detailed 5 Metrics -->
      <div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <div class="metric"><Gauge size={15}/><span><small>Speed</small><b>{speed}</b></span></div>
        <div class="metric"><Timer size={15}/><span><small>ETA</small><b>{progress.transfer.eta_seconds !== undefined ? formatDuration(progress.transfer.eta_seconds) : 'Menghitung...'}</b></span></div>
        <div class="metric success"><span><small>Berhasil</small><b>{progress.counters.succeeded}</b></span></div>
        <div class="metric failed"><span><small>Gagal</small><b>{progress.counters.failed}</b></span></div>
        <div class="metric"><span><small>Dilewati</small><b>{progress.counters.skipped}</b></span></div>
      </div>

      <div class="mt-4 grid gap-2 sm:grid-cols-3">
        <div class="rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3"><small class="muted block">Waktu tunggu antrean</small><b class="mt-1 block text-sm">{queueWaitSeconds !== undefined ? formatDuration(queueWaitSeconds) : 'Belum tersedia'}</b></div>
        <div class="rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3"><small class="muted block">Durasi fase aktif</small><b class="mt-1 block text-sm">{phaseElapsedSeconds !== undefined ? formatDuration(phaseElapsedSeconds) : 'Belum tersedia'}</b></div>
        <div class="rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3"><small class="muted block">Rata-rata latensi event</small><b class="mt-1 block text-sm">{eventLatency !== undefined ? `${Math.round(eventLatency)} ms` : 'Belum tersedia'}</b></div>
      </div>
      {#if Object.keys(observability.phase_durations_seconds || {}).length}
        <div class="mt-3 rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3">
          <b class="text-xs font-extrabold">Durasi per fase</b>
          <div class="mt-2 flex flex-wrap gap-2">
            {#each Object.entries(observability.phase_durations_seconds) as [phase, seconds]}
              <span class="rounded-full bg-[var(--surface-soft)] px-2.5 py-1 text-xs">{phaseLabel(phase)} · {formatDuration(seconds)}</span>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Staging path if present -->
      {#if job.progress?.staging_path && !job.progress?.staging_cleaned}
        <div class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs dark:border-amber-900 dark:bg-amber-950">
          <b class="text-amber-800 dark:text-amber-200">Staging diagnosis:</b>
          <code class="mt-1 block break-all font-mono">{job.progress.staging_path}</code>
        </div>
      {/if}

      <!-- Drawer Footer Actions -->
      <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--line)] pt-3 text-xs">
        <span class="muted font-mono">{job.id}</span>
        <div class="flex gap-2">
          <button class="button secondary !py-1 !px-2.5" onclick={onReport}>
            <FileText size={14}/> Buka Report Lengkap
          </button>
        </div>
      </div>
    </div>
  {/if}
</article>

<style>
  .idm-row {
    border: 1px solid color-mix(in srgb, var(--brand) 28%, var(--line));
    border-radius: 0.85rem;
    background: linear-gradient(145deg, var(--panel-strong), color-mix(in srgb, var(--brand-soft) 22%, var(--panel-strong)));
    box-shadow: var(--shadow-sm, 0 1px 2px 0 rgb(0 0 0 / 0.05));
    overflow: hidden;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }
  .idm-row:hover {
    border-color: color-mix(in srgb, var(--brand) 45%, var(--line));
  }
  .progress-track {
    position: relative;
    height: 0.65rem;
    overflow: hidden;
    border-radius: 999px;
    background: color-mix(in srgb, var(--brand) 12%, var(--line));
  }
  .progress-fill {
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, var(--brand), #29b9e8);
    transition: width 0.45s ease;
  }
  .progress-track.indeterminate .progress-fill {
    width: 36% !important;
    animation: indeterminate 1.35s ease-in-out infinite;
  }
  .metric {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 0.55rem;
    border: 1px solid var(--line);
    border-radius: 0.75rem;
    background: var(--panel-strong);
    padding: 0.65rem 0.7rem;
    color: var(--brand);
  }
  .metric span {
    min-width: 0;
    display: grid;
  }
  .metric small {
    color: var(--muted);
    font-size: 0.68rem;
  }
  .metric b {
    overflow: hidden;
    color: var(--ink);
    font-size: 0.78rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .metric.success b {
    color: #07804a;
  }
  .metric.failed b {
    color: #c62550;
  }
  @keyframes indeterminate {
    from {
      transform: translateX(-110%);
    }
    to {
      transform: translateX(310%);
    }
  }
</style>
