<script lang="ts">
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { Modal, TabItem, Tabs, Toast, Tooltip } from 'flowbite-svelte';
  import { AlertTriangle, ClipboardList, Copy, RefreshCw, ScrollText, SquareTerminal, XCircle } from '@lucide/svelte';
  import { api, post } from '$lib/api';

  type Job = Record<string, any>;
  type JobEvent = Record<string, any>;
  let { kind = '', title = 'Aktivitas terbaru' }: { kind?: string; title?: string } = $props();
  let jobs = $state<Job[]>([]);
  let error = $state('');
  let selected = $state<Job | null>(null);
  let events = $state<JobEvent[]>([]);
  let detailsOpen = $state(false);
  let confirmOpen = $state(false);
  let confirmTarget = $state<'one' | 'all'>('one');
  let eventsLoading = $state(false);
  let toastOpen = $state(false);
  let toastMessage = $state('');
  let timer: ReturnType<typeof setInterval>;

  const activeStates = ['queued', 'dispatched', 'running'];
  const terminal = (value: unknown) => JSON.stringify(value, null, 2);
  const isActive = (job: Job) => activeStates.includes(job.status);
  const summary = (job: Job) => job.progress?.message || job.result?.status || job.error?.message || 'Menunggu proses';
  const value = (item: unknown) => {
    if (item === null || item === undefined || item === '') return '-';
    if (typeof item === 'boolean') return item ? 'Ya' : 'Tidak';
    if (typeof item === 'object') return Array.isArray(item) ? `${item.length} item` : `${Object.keys(item as object).length} data`;
    return String(item);
  };

  async function load() {
    try {
      const result = await api<{ items: Job[] }>(`/jobs?limit=30${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`);
      jobs = result.items || [];
      error = '';
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Tidak dapat memuat job.'; }
  }

  async function loadEvents() {
    if (!selected) return;
    eventsLoading = true;
    try {
      const result = await api<{ items: JobEvent[] }>(`/jobs/${selected.id}/events?after_sequence=0`);
      events = result.items || [];
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Tidak dapat memuat event job.'; }
    finally { eventsLoading = false; }
  }

  async function openDetails(job: Job) {
    selected = job;
    events = [];
    detailsOpen = true;
    await loadEvents();
  }

  async function executeTermination() {
    try {
      if (confirmTarget === 'all') await post('/jobs/terminate-active');
      else if (selected) await post(`/jobs/${selected.id}/cancel`);
      toastMessage = confirmTarget === 'all' ? 'Sinyal terminate dikirim ke seluruh job aktif.' : 'Sinyal terminate dikirim ke job.';
      toastOpen = true;
      confirmOpen = false;
      await load();
      if (selected) await loadEvents();
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Job tidak dapat dihentikan.'; }
  }

  async function copySnapshot() {
    if (!selected || !navigator.clipboard) return;
    await navigator.clipboard.writeText(terminal({ job: selected, events }));
    toastMessage = 'Snapshot job disalin.';
    toastOpen = true;
  }

  function requestTermination(target: 'one' | 'all', job?: Job) {
    if (job) selected = job;
    confirmTarget = target;
    confirmOpen = true;
  }

  onMount(() => {
    load();
    timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  });
</script>

<section class="card mt-7 overflow-hidden">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4">
    <div><p class="eyebrow">JOB MONITOR</p><h2 class="mt-1 text-lg font-extrabold">{title}</h2></div>
    <div class="flex flex-wrap gap-2">
      <button class="button danger" onclick={() => requestTermination('all')}><XCircle size={16}/>Terminate semua aktif</button>
      <button id={`refresh-${kind || 'all'}`} class="button secondary" onclick={load} aria-label="Refresh daftar job"><RefreshCw size={16}/>Refresh</button>
      <Tooltip triggeredBy={`#refresh-${kind || 'all'}`} placement="top">Memuat status job terbaru</Tooltip>
    </div>
  </div>

  {#if error}<div class="mx-5 mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>{/if}

  <div class="divide-y divide-[var(--line)] px-5">
    {#each jobs as job, index (job.id)}
      <article class="job-row grid gap-3 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center" style={`--delay:${index * 34}ms`} in:fly={{ y: 8, duration: 220, delay: index * 34 }}>
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2"><b class="capitalize">{job.kind.replaceAll('_', ' ')}</b><span class={`badge ${job.status}`}>{job.status}</span>{#if job.queue_position}<span class="muted text-xs">Antrean #{job.queue_position}</span>{/if}</div>
          <p class="muted mt-1 truncate text-sm">{summary(job)}</p>
        </div>
        <div class="flex flex-wrap items-center gap-2 sm:justify-end">
          <small class="muted whitespace-nowrap text-xs">{new Date(job.updated_at).toLocaleString('id-ID')}</small>
          <button class="button secondary" onclick={() => openDetails(job)}><ScrollText size={15}/>Report / log</button>
          {#if isActive(job)}<button class="button danger" onclick={() => requestTermination('one', job)}><XCircle size={15}/>Terminate</button>{/if}
        </div>
      </article>
    {:else}
      <div class="py-14 text-center"><ClipboardList class="mx-auto mb-3 text-violet-500" size={30}/><p class="font-bold">Belum ada job.</p><p class="muted mt-1 text-sm">Job baru akan tampil beserta progress dan report akhirnya.</p></div>
    {/each}
  </div>
</section>

<Modal bind:open={detailsOpen} title={selected ? `Detail job ${selected.id.slice(0, 12)}` : 'Detail job'} size="xl" focustrap={true} transition={fly} transitionParams={{ y: 14, duration: 220 }} classes={{ body: '!p-0' }}>
  {#if selected}
    <div class="border-b border-[var(--line)] bg-[var(--brand-soft)] px-5 py-3 text-sm">
      <div class="flex flex-wrap items-center gap-2"><span class={`badge ${selected.status}`}>{selected.status}</span><span class="muted">{selected.kind.replaceAll('_', ' ')} · {selected.profile} · {selected.worker}</span></div>
    </div>
    <div class="p-5">
      <Tabs tabStyle="underline" divider={false} contentClass="!pt-4">
        <TabItem title="Ringkasan" key="summary" open>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="record-card sm:col-span-2"><p class="muted text-xs font-bold uppercase tracking-wide">Status terakhir</p><p class="mt-1 font-semibold">{summary(selected)}</p></div>
            {#each Object.entries(selected.result || selected.progress || {}).slice(0, 12) as [key, item]}
              <div class="record-card"><p class="muted text-xs capitalize">{key.replaceAll('_', ' ')}</p><p class="mt-1 break-words text-sm font-bold">{value(item)}</p></div>
            {/each}
            {#if selected.error}<div class="record-card border-rose-200 bg-rose-50 sm:col-span-2 dark:border-rose-900 dark:bg-rose-950"><p class="text-xs font-bold uppercase tracking-wide text-rose-600">Error</p><p class="mt-1 break-words text-sm text-rose-700 dark:text-rose-200">{value(selected.error.message || selected.error)}</p></div>{/if}
          </div>
        </TabItem>
        <TabItem title={`Event / log${events.length ? ` (${events.length})` : ''}`} key="events">
          <div class="mb-3 flex justify-end"><button class="button secondary" onclick={loadEvents} disabled={eventsLoading}><RefreshCw size={15} class={eventsLoading ? 'animate-spin' : ''}/>Refresh snapshot</button></div>
          <div class="max-h-[52vh] space-y-2 overflow-auto pr-1">
            {#each events as event}
              <article class="record-card"><div class="flex flex-wrap justify-between gap-2"><div class="flex items-center gap-2"><span class={`badge ${event.status}`}>{event.status}</span><b class="text-sm">{event.event_type}</b></div><small class="muted text-xs">#{event.sequence} · {new Date(event.created_at).toLocaleString('id-ID')}</small></div><p class="muted mt-2 text-sm">{event.progress?.message || event.error?.message || event.result?.status || 'Event tercatat.'}</p></article>
            {:else}<div class="record-card text-center"><SquareTerminal class="mx-auto mb-2 text-violet-500" size={24}/><p class="muted text-sm">Belum ada event terperinci untuk job ini.</p></div>{/each}
          </div>
        </TabItem>
        <TabItem title="Raw JSON" key="raw">
          <div class="mb-3 flex justify-end"><button class="button secondary" onclick={copySnapshot}><Copy size={15}/>Salin snapshot</button></div>
          <pre class="terminal max-h-[52vh] overflow-auto p-4 text-xs leading-6">{terminal({ job: selected, events })}</pre>
        </TabItem>
      </Tabs>
      {#if isActive(selected)}<div class="mt-5 flex justify-end border-t border-[var(--line)] pt-4"><button class="button danger" onclick={() => requestTermination('one', selected!)}><XCircle size={15}/>Terminate job</button></div>{/if}
    </div>
  {/if}
</Modal>

<Modal bind:open={confirmOpen} title={confirmTarget === 'all' ? 'Terminate semua job aktif?' : 'Terminate job ini?'} size="sm" permanent={true} dismissable={false} transition={fly} transitionParams={{ y: 10, duration: 180 }}>
  <div class="flex gap-3"><div class="grid size-10 shrink-0 place-items-center rounded-xl bg-rose-100 text-rose-600 dark:bg-rose-950"><AlertTriangle size={20}/></div><div><p class="font-semibold">Sinyal seperti Ctrl+C akan dikirim ke proses worker.</p><p class="muted mt-1 text-sm">Job dapat membutuhkan beberapa saat untuk benar-benar berhenti dan mengirim status terakhir.</p></div></div>
  <div class="mt-6 flex justify-end gap-2"><button class="button secondary" onclick={() => confirmOpen = false}>Batal</button><button class="button danger" onclick={executeTermination}><XCircle size={15}/>Ya, terminate</button></div>
</Modal>

<Toast bind:toastStatus={toastOpen} position="bottom-right" color="primary" class="!fixed !z-60 !rounded-xl !border !border-violet-200 !bg-white !text-slate-800 !shadow-2xl dark:!border-violet-900 dark:!bg-slate-900 dark:!text-slate-100">{toastMessage}</Toast>

<style>
  .job-row { animation: row-in .28s cubic-bezier(.16, 1, .3, 1) both; animation-delay: var(--delay); }
  @keyframes row-in { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: translateY(0); } }
</style>
