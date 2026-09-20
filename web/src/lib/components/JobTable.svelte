<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal, Toast } from 'flowbite-svelte';
  import { AlertTriangle, ClipboardList, Copy, FileText, RefreshCw, SquareTerminal, XCircle } from '@lucide/svelte';
  import { api, post } from '$lib/api';
  import { formatBytes, formatDate, jobMessage, resultEntries, textValue } from '$lib/presentation';
  import { formatDuration, normalizeJobProgress, phaseLabel } from '$lib/job-progress';
  import JobProgressCard from './JobProgressCard.svelte';

  type Job = Record<string, any>;
  type JobEvent = Record<string, any>;
  let { kind = '', title = 'Aktivitas terbaru', worker = '', profile = '', scope = 'current', status = '', quickMode = false, retryable = false }: { kind?: string; title?: string; worker?: string; profile?: string; scope?: 'current'|'global'; status?: string; quickMode?: boolean; retryable?: boolean } = $props();
  let jobs = $state<Job[]>([]);
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
  let timer: ReturnType<typeof setTimeout> | undefined;
  let mounted = false;
  let loadGeneration = 0;

  const activeStates = ['queued', 'dispatched', 'running'];
  const active = (job: Job) => activeStates.includes(job.status);
  const activeJobs = $derived(jobs.filter(active));
  const historyJobs = $derived(jobs.filter((job) => !active(job)));
  const milestones = $derived(events.filter((event) => !['log.snapshot', 'progress.snapshot'].includes(event.event_type)));
  const latestSnapshot = $derived([...events].reverse().find((event) => event.event_type === 'log.snapshot' && Array.isArray(event.result?.log?.lines)));
  const logLines = $derived(liveLog?.log?.lines || latestSnapshot?.result?.log?.lines || []);
  const selectedProgress = $derived(selected ? normalizeJobProgress(selected) : null);

  async function load() {
    const request = ++loadGeneration;
    try {
      const params = new URLSearchParams({ limit: '30', scope });
      if (kind) params.set('kind', kind);
      if (profile) params.set('profile', profile);
      if (worker) params.set('worker', worker);
      if (status) params.set('status', status);
      if (quickMode) params.set('quick_mode', 'true');
      const query = `/jobs?${params.toString()}`;
      const next = (await api<{items:Job[]}>(query)).items || [];
      if (request !== loadGeneration) return;
      jobs = next;
      if (selected) selected = next.find((job) => job.id === selected?.id) || selected;
      error = '';
    } catch (cause) {
      if (request !== loadGeneration) return;
      error = cause instanceof Error ? cause.message : 'Tidak dapat memuat job.';
    } finally {
      if (mounted && request === loadGeneration) schedule();
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
    if (job.status === 'succeeded' && !window.confirm(quick ? 'Jalankan ulang Quick Mode dari export awal?' : 'Jalankan ulang export dari awal?')) return;
    retrying = { ...retrying, [job.id]: true };
    try {
      await post(`/jobs/${encodeURIComponent(job.id)}/retry`);
      toastMessage = job.status === 'succeeded'
        ? (quick ? 'Quick Mode baru masuk antrean.' : 'Export baru masuk antrean.')
        : (quick ? 'Retry Quick Mode masuk antrean.' : 'Retry export masuk antrean.');
      toastOpen = true;
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Retry export gagal dibuat.';
    } finally {
      const next = { ...retrying };
      delete next[job.id];
      retrying = next;
    }
  }
  async function copy(value: string) { await navigator.clipboard?.writeText(value); toastMessage = 'Disalin ke clipboard.'; toastOpen = true; }
  const eventLine = (event: JobEvent) => {
    const batch = event.progress?.batch;
    const item = event.progress?.item;
    const position = batch?.index ? `JSON ${batch.index}/${batch.total || '?'} ${batch.name || ''}` : '';
    const media = item?.index ? `File ${item.index}/${item.total || '?'} ${item.name || ''}` : '';
    const detail = [position, media, event.progress?.message || event.error?.message || event.result?.status].filter(Boolean).join(' · ');
    return `#${event.sequence} [${event.status}] ${event.event_type}: ${textValue(detail, 'Event tercatat')}`;
  };
  const informativeEvents = $derived(events.filter((event) =>
    event.event_type.startsWith('download.')
    || event.event_type === 'artifact.missing'
    || (!logLines.length && !['log.snapshot', 'progress.snapshot'].includes(event.event_type))
  ).map(eventLine));
  const displayLogLines = $derived([
    ...informativeEvents,
    ...(informativeEvents.length && logLines.length ? ['──────── raw worker output ────────'] : []),
    ...logLines
  ]);
  function schedule() {
    if (timer) clearTimeout(timer);
    const running = jobs.filter(active);
    if (!running.length) return;
    timer = setTimeout(load, running.some((job) => job.status === 'running') ? 1000 : 3000);
  }
  onMount(() => {
    mounted = true;
    const refresh = () => load();
    const contextRefresh = () => {
      loadGeneration += 1;
      if (timer) clearTimeout(timer);
      jobs = [];
      selected = null;
      events = [];
      liveLog = null;
      reportOpen = false;
      logOpen = false;
      load();
    };
    window.addEventListener('tme3:data-mutated', refresh);
    window.addEventListener('tme3:context-changed', contextRefresh);
    load();
    return () => {
      mounted = false;
      if (timer) clearTimeout(timer);
      window.removeEventListener('tme3:data-mutated', refresh);
      window.removeEventListener('tme3:context-changed', contextRefresh);
    };
  });
</script>

<section class="card mt-7 overflow-hidden">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-4 sm:px-5">
    <div><p class="eyebrow">JOB MONITOR</p><h2 class="mt-1 text-lg font-extrabold">{title}</h2></div>
    <div class="flex flex-wrap gap-2"><button class="button danger" onclick={() => requestTerminate('all')}><XCircle size={16}/>Terminate semua aktif</button><button class="button secondary" onclick={load} aria-label="Refresh daftar job"><RefreshCw size={16}/>Refresh</button></div>
  </div>
  {#if error}<p class="m-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}

  {#if activeJobs.length}
    <div class="border-b border-[var(--line)] bg-[var(--brand-soft)]/20 p-4 sm:p-5">
      <div class="mb-3 flex items-center justify-between"><h3 class="font-extrabold">Sedang berjalan</h3><span class="badge running">{activeJobs.length} aktif</span></div>
      <div class="space-y-2.5">
        {#each activeJobs as job (job.id)}
          <JobProgressCard job={job} onReport={() => openReport(job)} onLog={() => openLog(job)} onTerminate={() => requestTerminate('one', job)}/>
        {/each}
      </div>
    </div>
  {/if}

  {#if historyJobs.length}<div class="px-4 pt-4 sm:px-5"><h3 class="text-sm font-extrabold">History terbaru</h3></div>{/if}
  <div class="divide-y divide-[var(--line)] px-4 sm:px-5">
    {#each historyJobs as job (job.id)}
      <article class="grid gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center"><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><b class="capitalize">{job.kind.replaceAll('_',' ')}</b>{#if job.payload?.quick_mode}<span class="badge running">Quick Mode</span>{/if}<span class={`badge ${job.status}`}>{job.status}</span><span class="muted text-xs">{job.worker || '-'}</span></div><p class="muted mt-1 truncate text-sm">{jobMessage(job)}</p></div><div class="flex flex-wrap items-center gap-2"><small class="muted mr-auto whitespace-nowrap lg:mr-0">{formatDate(job.updated_at)}</small><button class="button secondary" onclick={() => openReport(job)}><FileText size={15}/>Report</button><button class="button secondary" onclick={() => openLog(job)}><SquareTerminal size={15}/>Log</button>{#if retryable && job.kind === 'export' && ['failed','cancelled','succeeded'].includes(job.status)}<button class="button secondary" onclick={() => retry(job)} disabled={retrying[job.id]}><RefreshCw size={15} class={retrying[job.id] ? 'animate-spin' : ''}/>{job.status === 'succeeded' ? 'Jalankan lagi' : 'Retry'}</button>{/if}</div></article>
    {/each}
    {#if !historyJobs.length && !activeJobs.length}<div class="py-14 text-center"><ClipboardList class="mx-auto mb-2 text-violet-500"/><b>Belum ada job.</b></div>{/if}
  </div>
</section>

<Modal bind:open={reportOpen} title={selected ? `Detail ${selected.kind.replaceAll('_',' ')}` : 'Detail job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex max-h-[78dvh] min-h-0 flex-col">
    <div class="border-b border-[var(--line)] bg-[var(--brand-soft)] px-4 py-3"><div class="flex flex-wrap gap-2"><span class={`badge ${selected.status}`}>{selected.status}</span><span class="muted text-sm">{selected.profile} · {selected.worker}</span></div><p class="mt-2 font-mono text-xs">{selected.id}</p></div>
    <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      <div class="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-[var(--brand-soft)] p-1">
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'summary' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'summary'}>Ringkasan</button>
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'milestones' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'milestones'}>Milestone</button>
        <button class={`rounded-lg px-3 py-2 text-sm font-bold ${detailTab === 'raw' ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => detailTab = 'raw'}>Raw JSON</button>
      </div>
      {#if detailTab === 'summary'}
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
        <div class="space-y-2">{#each milestones as event}<article class="record-card"><div class="flex flex-wrap justify-between gap-2"><div><span class={`badge ${event.status}`}>{event.status}</span><b class="ml-2 text-sm">{event.event_type.replaceAll('_',' ')}</b></div><small class="muted">#{event.sequence} · {formatDate(event.created_at)}</small></div><p class="muted mt-2 text-sm">{event.progress?.message || event.error?.message || event.result?.status || 'Milestone tercatat.'}</p></article>{:else}<p class="muted py-8 text-center">Belum ada milestone.</p>{/each}</div>
      {:else}
        <div class="mb-2 flex justify-end"><button class="button secondary" onclick={() => copy(JSON.stringify({job:selected,events}, null, 2))}><Copy size={14}/>Salin</button></div><pre class="terminal max-h-[48dvh] overflow-auto p-4 text-xs">{JSON.stringify({job:selected,events}, null, 2)}</pre>
      {/if}
    </div>
    {#if active(selected)}<div class="shrink-0 border-t border-[var(--line)] p-3 text-right"><button class="button danger" onclick={() => requestTerminate('one', selected!)}><XCircle size={15}/>Terminate job</button></div>{/if}
  </div>{/if}
</Modal>

<Modal bind:open={logOpen} title={selected ? `Log ${selected.id.slice(0,12)}` : 'Log job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex h-[78dvh] min-h-0 flex-col bg-[#080d19] text-slate-100">
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-4 py-3"><div><b>{displayLogLines.length} baris</b>{#if liveLog?.log?.truncated || latestSnapshot?.result?.log?.truncated}<span class="ml-2 text-xs text-amber-300">terpotong</span>{/if}</div><div class="flex gap-2"><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={loadEvents} disabled={loadingEvents}><RefreshCw class={loadingEvents ? 'animate-spin' : ''} size={15}/>Refresh</button><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={() => copy(displayLogLines.join('\n'))}><Copy size={15}/>Copy</button></div></div>
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
