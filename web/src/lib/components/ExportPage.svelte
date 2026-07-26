<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import type { LabelItem } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { CheckCircle2, CircleAlert, Clock3, FileDown, ListFilter, LoaderCircle, Plus, Trash2, X } from '@lucide/svelte';

  type ExportJob = {
    id:string; status:string; progress?:Record<string,any>; result?:{value?:Record<string,any>};
    error?:{message?:string}|null
  };
  type ExportNotice = { job:ExportJob; announcedTerminal:boolean };

  let sources = $state<any[]>([]);
  let labels = $state<LabelItem[]>([]);
  let chatRef = $state('');
  let startId = $state('1');
  let label = $state('');
  let selected = $state('');
  let message = $state('');
  let notices = $state<ExportNotice[]>([]);
  let pollTimer:ReturnType<typeof setTimeout>|undefined;
  let mounted=false;

  const activeStatuses=['queued','dispatched','running'];
  const activeNotice=$derived(notices.some(item => activeStatuses.includes(item.job.status)));

  function persistNotices() {
    sessionStorage.setItem('tme3-export-notices', JSON.stringify(notices.map(item => item.job.id)));
  }
  function remember(job:ExportJob) {
    const current=notices.find(item => item.job.id===job.id);
    if (current) current.job=job;
    else notices=[{job,announcedTerminal:false},...notices].slice(0,4);
    notices=[...notices];
    persistNotices();
  }
  function dismiss(jobId:string) {
    notices=notices.filter(item => item.job.id!==jobId);
    persistNotices();
  }
  function resultValue(job:ExportJob) { return job.result?.value || {}; }
  function completionText(job:ExportJob) {
    const value=resultValue(job);
    const messages=value.message_count ?? value.exported_count ?? 0;
    const media=value.media_count;
    const mediaText=typeof media==='number' ? `${media} media` : value.has_media ? 'media tersedia' : '0 media';
    const details=[
      typeof value.photo_count==='number' ? `${value.photo_count} foto` : '',
      typeof value.video_count==='number' ? `${value.video_count} video` : ''
    ].filter(Boolean).join(' · ');
    return `${messages} pesan · ${mediaText}${details ? ` · ${details}` : ''}`;
  }
  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    if (!mounted || !activeNotice) return;
    pollTimer=setTimeout(pollNotices,1000);
  }
  async function pollNotices() {
    const active=notices.filter(item => activeStatuses.includes(item.job.status));
    if (!active.length) return;
    const updates=await Promise.all(active.map(async item => {
      try { return await api<ExportJob>(`/jobs/${item.job.id}`); }
      catch { return item.job; }
    }));
    let completed=false;
    for (const job of updates) {
      const index=notices.findIndex(item => item.job.id===job.id);
      if (index>=0) {
        if (activeStatuses.includes(notices[index].job.status) && !activeStatuses.includes(job.status)) completed=true;
        notices[index]={...notices[index],job};
      }
    }
    notices=[...notices];
    persistNotices();
    if (completed) await load();
    schedulePoll();
  }

  async function load() {
    const [sourceResult, labelResult] = await Promise.all([api<any>('/sources'), api<any>('/labels')]);
    sources = sourceResult.items || [];
    labels = (labelResult.items || []).filter((item: unknown): item is LabelItem => Boolean(item && typeof item === 'object' && typeof (item as LabelItem).label === 'string'));
  }
  function choose(value: string) {
    selected = value;
    const found = sources.find((source) => source.chat_ref === value);
    if (found) { chatRef = found.chat_ref; startId = String(Number(found.last_id || 0) + 1); label = found.label || ''; }
  }
  async function submit() {
    try {
      const job=await post<ExportJob>('/exports', { chat_ref: chatRef, start_id: Number(startId), label: label || undefined });
      remember(job);
      message='';
      schedulePoll();
      await load();
    }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Export gagal dibuat.'; }
  }
  onMount(() => {
    mounted=true;
    const saved=JSON.parse(sessionStorage.getItem('tme3-export-notices') || '[]');
    if (Array.isArray(saved)) {
      Promise.all(saved.slice(0,4).map(id => api<ExportJob>(`/jobs/${id}`).catch(() => null)))
        .then(jobs => { notices=jobs.filter((job):job is ExportJob => Boolean(job)).map(job => ({job,announcedTerminal:false})); schedulePoll(); });
    }
    load();
    return () => { mounted=false;if(pollTimer)clearTimeout(pollTimer); };
  });
</script>

<div class="pointer-events-none fixed inset-x-3 top-20 z-[70] flex flex-col items-end gap-3 sm:left-auto sm:right-5 sm:w-[390px]" aria-live="polite" aria-atomic="false">
  {#each notices as notice (notice.job.id)}
    {@const value=resultValue(notice.job)}
    <section class={`pointer-events-auto w-full overflow-hidden rounded-2xl border bg-[var(--panel)] shadow-2xl transition ${notice.job.status==='succeeded'?'border-emerald-300 dark:border-emerald-800':notice.job.status==='failed'?'border-rose-300 dark:border-rose-800':'border-violet-300 dark:border-violet-800'}`} role="alert">
      <div class="flex items-start gap-3 p-4">
        <div class={`grid size-10 shrink-0 place-items-center rounded-xl ${notice.job.status==='succeeded'?'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300':notice.job.status==='failed'?'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300':'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300'}`}>
          {#if notice.job.status==='succeeded'}<CheckCircle2 size={21}/>{:else if notice.job.status==='failed'}<CircleAlert size={21}/>{:else}<LoaderCircle class="animate-spin" size={21}/>{/if}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-2"><b>{notice.job.status==='succeeded'?'Export selesai':notice.job.status==='failed'?'Export gagal':'Export masuk antrean'}</b><button class="rounded-lg p-1 text-[var(--muted)] hover:bg-[var(--brand-soft)]" onclick={() => dismiss(notice.job.id)} aria-label="Tutup notifikasi export"><X size={16}/></button></div>
          {#if notice.job.status==='succeeded'}
            <p class="mt-1 text-sm font-semibold">{completionText(notice.job)}</p>
            <p class="muted mt-1 truncate text-xs">{value.chat_ref || chatRef}{value.requested_label ? ` · ${value.requested_label}` : ''}</p>
          {:else if notice.job.status==='failed'}
            <p class="mt-1 text-sm text-rose-600 dark:text-rose-300">{notice.job.error?.message || 'Worker tidak dapat menyelesaikan export.'}</p>
          {:else}
            <p class="muted mt-1 text-sm">{notice.job.progress?.message || 'Menunggu worker yang dipilih.'}</p>
            <p class="muted mt-2 flex items-center gap-1 font-mono text-[11px]"><Clock3 size={12}/>{notice.job.id.slice(0,12)}</p>
          {/if}
        </div>
      </div>
      {#if activeStatuses.includes(notice.job.status)}<div class="h-1 overflow-hidden bg-violet-100 dark:bg-violet-950"><div class="h-full w-1/2 animate-pulse rounded-full bg-violet-600"></div></div>{/if}
    </section>
  {/each}
</div>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">EXPORT</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Source & pembuatan export</h1><p class="muted mt-2">Pilih source tersimpan atau masukkan username/numeric chat ID.</p></div><div class="hidden rounded-2xl bg-violet-50 p-3 text-violet-700 sm:block dark:bg-violet-950 dark:text-violet-200"><FileDown size={24}/></div></header>

<div class="mt-7 grid gap-5 xl:grid-cols-[.84fr_1.16fr]">
  <section class="card p-5 sm:p-6"><div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={20}/></div><div><h2 class="font-extrabold">Export baru</h2><p class="muted text-sm">Start ID dapat dioverride saat diperlukan.</p></div></div>
    <label class="mt-6 block text-sm font-bold">Pilih source tersimpan<select class="field mt-2" value={selected} onchange={(event) => choose((event.currentTarget as HTMLSelectElement).value)}><option value="">Source baru...</option>{#each sources as source}<option value={source.chat_ref}>{source.label ? `${source.label} — ` : ''}{source.chat_ref} (berikutnya: {Number(source.last_id) + 1})</option>{/each}</select></label>
    <div class="mt-4 grid gap-4 sm:grid-cols-2"><label class="block text-sm font-bold sm:col-span-2">Username atau chat ID<input class="field mt-2" bind:value={chatRef} placeholder="username atau numeric ID" /></label><label class="block text-sm font-bold">Start message ID<input class="field mt-2" type="number" min="1" bind:value={startId} /></label><label class="block text-sm font-bold">Label<input class="field mt-2" list="labels" bind:value={label} placeholder="Opsional" /><datalist id="labels">{#each labels as item}<option value={item.label}></option>{/each}</datalist></label></div>
    {#if labels.length}<div class="mt-3 flex flex-wrap gap-2">{#each labels as item}<button class="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700 transition hover:-translate-y-0.5 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200" onclick={() => label = item.label}>{item.label}</button>{/each}</div>{/if}
    <button class="button mt-6 w-full" onclick={submit}><FileDown size={16}/>Mulai export</button>{#if message}<p class="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">{message}</p>{/if}
  </section>

  <section class="card overflow-hidden"><div class="flex items-center justify-between border-b border-[var(--line)] px-5 py-4 sm:px-6"><div class="flex items-center gap-3"><div class="grid size-9 place-items-center rounded-xl bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"><ListFilter size={18}/></div><div><h2 class="font-extrabold">Source tersimpan</h2><p class="muted text-sm">Klik source untuk memakai Last ID berikutnya.</p></div></div><span class="badge">{sources.length} source</span></div>
    <div class="divide-y divide-[var(--line)] px-5 sm:px-6">{#each sources as source}<article class="group flex items-center justify-between gap-3 py-4"><button class="min-w-0 text-left" onclick={() => choose(source.chat_ref)}><b class="block truncate text-sm group-hover:text-violet-700 dark:group-hover:text-violet-300">{source.chat_ref}</b><p class="muted mt-1 text-sm">{source.label || 'Tanpa label'} · Last ID {source.last_id}</p></button><button class="button ghost size-9 !rounded-lg !p-0 text-rose-600 hover:!bg-rose-50 dark:hover:!bg-rose-950" onclick={async () => { await remove(`/sources/${encodeURIComponent(source.chat_ref)}`); await load(); }} aria-label={`Hapus ${source.chat_ref}`}><Trash2 size={16}/></button></article>{:else}<div class="py-14 text-center"><ListFilter class="mx-auto mb-3 text-violet-500" size={28}/><p class="font-bold">Belum ada source.</p><p class="muted mt-1 text-sm">Export yang sukses akan menyimpan source ini.</p></div>{/each}</div>
  </section>
</div>
<JobTable kind="export" title="Riwayat export" />
