<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import type { LabelItem } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { FileDown, ListFilter, Plus, Trash2 } from '@lucide/svelte';

  let sources = $state<any[]>([]);
  let labels = $state<LabelItem[]>([]);
  let chatRef = $state('');
  let startId = $state('1');
  let label = $state('');
  let selected = $state('');
  let message = $state('');

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
    try { await post('/exports', { chat_ref: chatRef, start_id: Number(startId), label: label || undefined }); message = 'Export masuk antrean.'; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Export gagal dibuat.'; }
  }
  onMount(load);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">EXPORT</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Source & pembuatan export</h1><p class="muted mt-2">Pilih source tersimpan atau masukkan username/numeric chat ID.</p></div><div class="hidden rounded-2xl bg-violet-50 p-3 text-violet-700 sm:block dark:bg-violet-950 dark:text-violet-200"><FileDown size={24}/></div></header>

<div class="mt-7 grid gap-5 xl:grid-cols-[.84fr_1.16fr]">
  <section class="card p-5 sm:p-6"><div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={20}/></div><div><h2 class="font-extrabold">Export baru</h2><p class="muted text-sm">Start ID dapat dioverride saat diperlukan.</p></div></div>
    <label class="mt-6 block text-sm font-bold">Pilih source tersimpan<select class="field mt-2" value={selected} onchange={(event) => choose((event.currentTarget as HTMLSelectElement).value)}><option value="">Source baru...</option>{#each sources as source}<option value={source.chat_ref}>{source.label ? `${source.label} — ` : ''}{source.chat_ref} (berikutnya: {Number(source.last_id) + 1})</option>{/each}</select></label>
    <div class="mt-4 grid gap-4 sm:grid-cols-2"><label class="block text-sm font-bold sm:col-span-2">Username atau chat ID<input class="field mt-2" bind:value={chatRef} placeholder="username atau numeric ID" /></label><label class="block text-sm font-bold">Start message ID<input class="field mt-2" type="number" min="1" bind:value={startId} /></label><label class="block text-sm font-bold">Label<input class="field mt-2" list="labels" bind:value={label} placeholder="Opsional" /><datalist id="labels">{#each labels as item}<option value={item.label}></option>{/each}</datalist></label></div>
    {#if labels.length}<div class="mt-3 flex flex-wrap gap-2">{#each labels as item}<button class="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700 transition hover:-translate-y-0.5 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200" onclick={() => label = item.label}>{item.label}</button>{/each}</div>{/if}
    <button class="button mt-6 w-full" onclick={submit}><FileDown size={16}/>Mulai export</button>{#if message}<p class="mt-3 rounded-xl bg-violet-50 px-3 py-2 text-sm text-violet-700 dark:bg-violet-950 dark:text-violet-200">{message}</p>{/if}
  </section>

  <section class="card overflow-hidden"><div class="flex items-center justify-between border-b border-[var(--line)] px-5 py-4 sm:px-6"><div class="flex items-center gap-3"><div class="grid size-9 place-items-center rounded-xl bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"><ListFilter size={18}/></div><div><h2 class="font-extrabold">Source tersimpan</h2><p class="muted text-sm">Klik source untuk memakai Last ID berikutnya.</p></div></div><span class="badge">{sources.length} source</span></div>
    <div class="divide-y divide-[var(--line)] px-5 sm:px-6">{#each sources as source}<article class="group flex items-center justify-between gap-3 py-4"><button class="min-w-0 text-left" onclick={() => choose(source.chat_ref)}><b class="block truncate text-sm group-hover:text-violet-700 dark:group-hover:text-violet-300">{source.chat_ref}</b><p class="muted mt-1 text-sm">{source.label || 'Tanpa label'} · Last ID {source.last_id}</p></button><button class="button ghost size-9 !rounded-lg !p-0 text-rose-600 hover:!bg-rose-50 dark:hover:!bg-rose-950" onclick={async () => { await remove(`/sources/${encodeURIComponent(source.chat_ref)}`); await load(); }} aria-label={`Hapus ${source.chat_ref}`}><Trash2 size={16}/></button></article>{:else}<div class="py-14 text-center"><ListFilter class="mx-auto mb-3 text-violet-500" size={28}/><p class="font-bold">Belum ada source.</p><p class="muted mt-1 text-sm">Export yang sukses akan menyimpan source ini.</p></div>{/each}</div>
  </section>
</div>
<JobTable kind="export" title="Riwayat export" />
