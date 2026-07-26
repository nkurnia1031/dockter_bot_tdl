<script lang="ts">
  import { formatBytes } from '$lib/presentation';
  import { formatDuration, normalizeJobProgress, phaseLabel } from '$lib/job-progress';
  import { Clock3, FileText, Gauge, SquareTerminal, Timer, XCircle } from '@lucide/svelte';
  let { job, onReport, onLog, onTerminate }: {
    job: Record<string, any>;
    onReport: () => void;
    onLog: () => void;
    onTerminate: () => void;
  } = $props();
  const progress = $derived(normalizeJobProgress(job));
  const overallPercent = $derived(progress.overall.percent);
  const itemPercent = $derived(progress.item.percent);
  const speed = $derived(progress.transfer.speed_bps ? `${formatBytes(progress.transfer.speed_bps)}/dtk` : progress.transfer.speed_text || 'Menghitung...');
</script>

<article class="progress-card">
  <header class="flex flex-wrap items-start justify-between gap-3">
    <div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><span class="badge running">{phaseLabel(progress.phase)}</span><b class="capitalize">{job.kind.replaceAll('_',' ')}</b><span class="muted text-xs">{job.profile} / {job.worker}</span></div><h3 class="mt-2 truncate text-base font-extrabold">{progress.message}</h3></div>
    <div class="flex items-center gap-1 text-xs text-[var(--muted)]"><Clock3 size={14}/>{formatDuration(progress.elapsedSeconds ?? ((Date.now() - new Date(job.created_at).getTime()) / 1000))}</div>
  </header>

  <div class="mt-5">
    <div class="mb-2 flex justify-between gap-3 text-xs"><b>Progress keseluruhan</b><span class="muted">{progress.overall.current ?? 0}{progress.overall.total ? ` / ${progress.overall.total} ${progress.overall.unit || ''}` : ''}{overallPercent !== undefined ? ` / ${overallPercent.toFixed(1)}%` : ''}</span></div>
    <div class={`progress-track ${progress.indeterminate && overallPercent === undefined ? 'indeterminate' : ''}`}><div class="progress-fill" style={`width:${overallPercent ?? 0}%`}></div></div>
  </div>

  {#if progress.item.name}
    <div class="mt-4 rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] p-3">
      <div class="flex justify-between gap-3 text-sm"><b class="min-w-0 truncate">{progress.item.name}</b><span class="muted shrink-0">{progress.item.index ? `${progress.item.index}/${progress.item.total || '?'}` : ''}</span></div>
      <div class={`progress-track mt-3 !h-2 ${progress.indeterminate && itemPercent === undefined ? 'indeterminate' : ''}`}><div class="progress-fill" style={`width:${itemPercent ?? 0}%`}></div></div>
      <div class="muted mt-2 flex flex-wrap justify-between gap-2 text-xs"><span>{progress.item.size_bytes ? formatBytes(progress.item.size_bytes) : 'Ukuran tidak diketahui'}</span><span>{itemPercent !== undefined ? `${itemPercent.toFixed(1)}%` : 'Sedang diproses'}</span></div>
    </div>
  {/if}

  <div class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
    <div class="metric"><Gauge size={15}/><span><small>Speed</small><b>{speed}</b></span></div>
    <div class="metric"><Timer size={15}/><span><small>ETA</small><b>{progress.transfer.eta_seconds !== undefined ? formatDuration(progress.transfer.eta_seconds) : 'Menghitung...'}</b></span></div>
    <div class="metric success"><span><small>Berhasil</small><b>{progress.counters.succeeded}</b></span></div>
    <div class="metric failed"><span><small>Gagal</small><b>{progress.counters.failed}</b></span></div>
  </div>

  <footer class="mt-5 flex flex-wrap justify-end gap-2 border-t border-[var(--line)] pt-4">
    <button class="button secondary" onclick={onReport}><FileText size={15}/>Detail</button>
    <button class="button secondary" onclick={onLog}><SquareTerminal size={15}/>Log</button>
    <button class="button danger" onclick={onTerminate}><XCircle size={15}/>Terminate</button>
  </footer>
</article>

<style>
  .progress-card { border: 1px solid color-mix(in srgb, var(--brand) 30%, var(--line)); border-radius: 1rem; background: linear-gradient(145deg, var(--panel-strong), color-mix(in srgb, var(--brand-soft) 28%, var(--panel-strong))); padding: 1rem; box-shadow: var(--shadow); }
  .progress-track { position: relative; height: .65rem; overflow: hidden; border-radius: 999px; background: color-mix(in srgb, var(--brand) 12%, var(--line)); }
  .progress-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--brand), #29b9e8); transition: width .45s ease; }
  .progress-track.indeterminate .progress-fill { width: 36% !important; animation: indeterminate 1.35s ease-in-out infinite; }
  .metric { display: flex; min-width: 0; align-items: center; gap: .55rem; border: 1px solid var(--line); border-radius: .75rem; background: var(--panel-strong); padding: .65rem .7rem; color: var(--brand); }
  .metric span { min-width: 0; display: grid; }
  .metric small { color: var(--muted); font-size: .68rem; }
  .metric b { overflow: hidden; color: var(--ink); font-size: .78rem; text-overflow: ellipsis; white-space: nowrap; }
  .metric.success b { color: #07804a; }.metric.failed b { color: #c62550; }
  @keyframes indeterminate { from { transform: translateX(-110%); } to { transform: translateX(310%); } }
</style>
