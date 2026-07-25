<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal, Toast } from 'flowbite-svelte';
  import { AlertTriangle, ClipboardList, Copy, FileText, RefreshCw, ScrollText, SquareTerminal, XCircle } from '@lucide/svelte';
  import { api, post } from '$lib/api';
  import { formatDate, jobMessage, resultEntries, textValue } from '$lib/presentation';

  type Job = Record<string, any>;
  type JobEvent = Record<string, any>;
  let { kind = '', title = 'Aktivitas terbaru' }: { kind?: string; title?: string } = $props();
  let jobs = $state<Job[]>([]);
  let error = $state('');
  let selected = $state<Job | null>(null);
  let events = $state<JobEvent[]>([]);
  let reportOpen = $state(false);
  let logOpen = $state(false);
  let rawOpen = $state(false);
  let confirmOpen = $state(false);
  let confirmTarget = $state<'one'|'all'>('one');
  let loadingEvents = $state(false);
  let toastOpen = $state(false);
  let toastMessage = $state('');
  let timer: ReturnType<typeof setInterval>;
  const activeStates = ['queued', 'dispatched', 'running'];
  const active = (job: Job) => activeStates.includes(job.status);
  const latestSnapshot = $derived([...events].reverse().find((event) => event.event_type === 'log.snapshot' && Array.isArray(event.result?.log?.lines)));
  const logLines = $derived(latestSnapshot?.result?.log?.lines || []);

  async function load() {
    try { jobs = (await api<{items:Job[]}>(`/jobs?limit=30${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`)).items || []; error = ''; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Tidak dapat memuat job.'; }
  }
  async function loadEvents() {
    if (!selected) return;
    loadingEvents = true;
    try { events = (await api<{items:Job[]}>(`/jobs/${selected.id}/events?after_sequence=0`)).items || []; }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Tidak dapat memuat event.'; }
    finally { loadingEvents = false; }
  }
  async function openReport(job: Job) { selected = job; events = []; rawOpen = false; reportOpen = true; await loadEvents(); }
  async function openLog(job: Job) { selected = job; events = []; logOpen = true; await loadEvents(); }
  function requestTerminate(target: 'one'|'all', job?: Job) { if (job) selected = job; confirmTarget = target; confirmOpen = true; }
  async function terminate() {
    try {
      if (confirmTarget === 'all') await post('/jobs/terminate-active');
      else if (selected) await post(`/jobs/${selected.id}/cancel`);
      toastMessage = confirmTarget === 'all' ? 'Terminate dikirim ke semua job aktif.' : 'Terminate dikirim ke job.';
      toastOpen = true; confirmOpen = false; await load();
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Job gagal dihentikan.'; }
  }
  async function copy(value: string) { await navigator.clipboard?.writeText(value); toastMessage = 'Disalin ke clipboard.'; toastOpen = true; }
  const eventLine = (event: JobEvent) => `#${event.sequence} [${event.status}] ${event.event_type}: ${textValue(event.progress?.message || event.error?.message || event.result?.status, 'Event tercatat')}`;
  onMount(() => { load(); timer = setInterval(load, 2500); return () => clearInterval(timer); });
</script>

<section class="card mt-7 overflow-hidden">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-4 sm:px-5">
    <div><p class="eyebrow">JOB MONITOR</p><h2 class="mt-1 text-lg font-extrabold">{title}</h2></div>
    <div class="flex flex-wrap gap-2"><button class="button danger" onclick={() => requestTerminate('all')}><XCircle size={16}/>Terminate semua aktif</button><button class="button secondary" onclick={load} aria-label="Refresh daftar job"><RefreshCw size={16}/>Refresh</button></div>
  </div>
  {#if error}<p class="m-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}
  <div class="divide-y divide-[var(--line)] px-4 sm:px-5">{#each jobs as job (job.id)}
    <article class="grid gap-3 py-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center"><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><b class="capitalize">{job.kind.replaceAll('_',' ')}</b><span class={`badge ${job.status}`}>{job.status}</span><span class="muted text-xs">{job.worker || '-'}</span></div><p class="muted mt-1 truncate text-sm">{jobMessage(job)}</p></div><div class="flex flex-wrap items-center gap-2"><small class="muted mr-auto whitespace-nowrap lg:mr-0">{formatDate(job.updated_at)}</small><button class="button secondary" onclick={() => openReport(job)}><FileText size={15}/>Report</button><button class="button secondary" onclick={() => openLog(job)}><SquareTerminal size={15}/>Log</button>{#if active(job)}<button class="button danger" onclick={() => requestTerminate('one', job)}><XCircle size={15}/>Terminate</button>{/if}</div></article>
  {:else}<div class="py-14 text-center"><ClipboardList class="mx-auto mb-2 text-violet-500"/><b>Belum ada job.</b></div>{/each}</div>
</section>

<Modal bind:open={reportOpen} title={selected ? `Report ${selected.kind.replaceAll('_',' ')}` : 'Report job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex max-h-[78dvh] min-h-0 flex-col">
    <div class="border-b border-[var(--line)] bg-[var(--brand-soft)] px-4 py-3"><div class="flex flex-wrap gap-2"><span class={`badge ${selected.status}`}>{selected.status}</span><span class="muted text-sm">{selected.profile} · {selected.worker}</span></div><p class="mt-2 font-mono text-xs">{selected.id}</p></div>
    <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5"><div class="grid gap-3 sm:grid-cols-2"><div class="record-card sm:col-span-2"><p class="muted text-xs font-bold uppercase">Pesan akhir</p><p class="mt-1 font-semibold">{jobMessage(selected)}</p></div>{#each resultEntries(selected.result) as [key,value]}<div class="record-card"><p class="muted text-xs font-bold uppercase">{key.replaceAll('_',' ')}</p><p class="mt-1 break-words text-sm font-semibold">{value}</p></div>{/each}{#if selected.error}<div class="record-card border-rose-200 bg-rose-50 sm:col-span-2 dark:border-rose-900 dark:bg-rose-950"><b class="text-rose-600">Error</b><p class="mt-1 break-words text-sm">{textValue(selected.error?.message || selected.error)}</p></div>{/if}</div>
      <button class="button ghost mt-4" onclick={() => rawOpen = !rawOpen}><ScrollText size={15}/>{rawOpen ? 'Sembunyikan' : 'Lihat'} Raw JSON</button>{#if rawOpen}<div class="mt-2 flex justify-end"><button class="button secondary" onclick={() => copy(JSON.stringify(selected, null, 2))}><Copy size={14}/>Salin</button></div><pre class="terminal mt-2 max-h-72 overflow-auto p-4 text-xs">{JSON.stringify(selected, null, 2)}</pre>{/if}
    </div>
    {#if active(selected)}<div class="shrink-0 border-t border-[var(--line)] p-3 text-right"><button class="button danger" onclick={() => requestTerminate('one', selected!)}><XCircle size={15}/>Terminate job</button></div>{/if}
  </div>{/if}
</Modal>

<Modal bind:open={logOpen} title={selected ? `Log ${selected.id.slice(0,12)}` : 'Log job'} size="xl" classes={{body:'!p-0'}}>
  {#if selected}<div class="flex h-[78dvh] min-h-0 flex-col bg-[#080d19] text-slate-100">
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-4 py-3"><div><b>{logLines.length ? `${logLines.length} baris` : `${events.length} event`}</b>{#if latestSnapshot?.result?.log?.truncated}<span class="ml-2 text-xs text-amber-300">terpotong</span>{/if}</div><div class="flex gap-2"><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={loadEvents} disabled={loadingEvents}><RefreshCw class={loadingEvents ? 'animate-spin' : ''} size={15}/>Refresh</button><button class="button secondary !border-slate-600 !bg-slate-800 !text-white" onclick={() => copy((logLines.length ? logLines : events.map(eventLine)).join('\n'))}><Copy size={15}/>Copy</button></div></div>
    <pre class="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-6 text-emerald-200">{logLines.length ? logLines.join('\n') : events.map(eventLine).join('\n') || 'Snapshot log belum tersedia. Tekan Refresh untuk mencoba lagi.'}</pre>
  </div>{/if}
</Modal>

<Modal bind:open={confirmOpen} title={confirmTarget === 'all' ? 'Terminate semua job aktif?' : 'Terminate job ini?'} size="sm" permanent>
  <div class="flex gap-3"><AlertTriangle class="shrink-0 text-rose-600" size={23}/><p>Sinyal seperti Ctrl+C akan dikirim. Proses dapat membutuhkan beberapa saat untuk mengirim status terakhir.</p></div><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => confirmOpen = false}>Batal</button><button class="button danger" onclick={terminate}>Terminate</button></div>
</Modal>
<Toast bind:toastStatus={toastOpen} position="bottom-right" color="primary">{toastMessage}</Toast>
