<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { ChevronLeft, ChevronRight, Folder, FolderCheck, RefreshCw, ServerOff } from '@lucide/svelte';

  type TreeItem = { name: string; path: string; kind: 'directory'|'file'; files?: number; directories?: number; has_children?: boolean };
  type TreeResponse = { path: string; items: TreeItem[] };
  let { selected = $bindable([]), single = false, worker = '' }: { selected?: string[]; single?: boolean; worker?: string } = $props();
  let current = $state('/workspace');
  let items = $state<TreeItem[]>([]);
  let loading = $state(false);
  let error = $state('');

  const folders = $derived(items.filter((item) => item.kind === 'directory'));
  const crumbs = $derived(current.split('/').filter(Boolean));

  async function load(path = current) {
    if (!path.startsWith('/workspace')) return;
    loading = true;
    try {
      const workerQuery = worker ? `&worker=${encodeURIComponent(worker)}` : '';
      const result = await api<TreeResponse>(`/utility/tree?path=${encodeURIComponent(path)}${workerQuery}`);
      current = result.path;
      items = Array.isArray(result.items) ? result.items : [];
      error = '';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Worker tidak dapat membaca workspace.';
    } finally { loading = false; }
  }

  function choose(path: string) {
    if (!path.startsWith('/workspace')) return;
    if (single) selected = [path];
    else selected = selected.includes(path) ? selected.filter((item) => item !== path) : [...selected, path];
  }

  function goUp() {
    if (current === '/workspace') return;
    load(current.slice(0, current.lastIndexOf('/')) || '/workspace');
  }

  function openCrumb(index: number) {
    load('/' + crumbs.slice(0, index + 1).join('/'));
  }

  let lastWorker = '';
  $effect(() => {
    if (worker && worker !== lastWorker) {
      lastWorker = worker;
      current = '/workspace';
      selected = [];
      load('/workspace');
    }
  });
  onMount(() => { if (!worker) load(); });
</script>

<div class="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--panel-strong)]">
  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--line)] p-3">
    <div class="flex min-w-0 items-center gap-1 text-sm">
      {#each crumbs as crumb, index}
        {#if index}<ChevronRight class="muted shrink-0" size={14}/>{/if}
        <button class="max-w-36 truncate rounded-md px-1.5 py-1 font-semibold hover:bg-[var(--brand-soft)]" onclick={() => openCrumb(index)}>{crumb}</button>
      {/each}
    </div>
    <div class="flex gap-1">
      <button class="button ghost size-9 !p-0" onclick={goUp} disabled={current === '/workspace'} aria-label="Folder induk"><ChevronLeft size={17}/></button>
      <button class="button ghost size-9 !p-0" onclick={() => load()} aria-label="Refresh folder"><RefreshCw class={loading ? 'animate-spin' : ''} size={17}/></button>
    </div>
  </div>

  {#if error}
    <div class="m-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">
      <div class="flex gap-2"><ServerOff class="shrink-0" size={18}/><div><b>Folder worker tidak tersedia.</b><p class="mt-1">{error}</p></div></div>
      <button class="button secondary mt-3" onclick={() => load()}><RefreshCw size={15}/>Coba lagi</button>
    </div>
  {:else}
    <div class="flex items-center justify-between gap-3 border-b border-[var(--line)] bg-[var(--brand-soft)]/40 px-4 py-3">
      <div class="min-w-0"><p class="muted text-xs font-bold uppercase">Folder saat ini</p><p class="truncate font-mono text-sm">{current}</p></div>
      <button class="button secondary shrink-0" onclick={() => choose(current)}><FolderCheck size={16}/>{selected.includes(current) ? 'Batalkan' : 'Pilih'}</button>
    </div>
    <div class="max-h-80 divide-y divide-[var(--line)] overflow-auto">
      {#each folders as item}
        <div class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3">
          <input type={single ? 'radio' : 'checkbox'} name={single ? 'workspace-folder' : undefined} checked={selected.includes(item.path)} onchange={() => choose(item.path)} aria-label={`Pilih ${item.name}`}/>
          <button class="min-w-0 text-left" onclick={() => load(item.path)}>
            <span class="flex items-center gap-2 font-semibold"><Folder class="shrink-0 text-violet-500" size={17}/><span class="truncate">{item.name}</span></span>
            <span class="muted mt-1 block text-xs">{item.directories ?? 0} folder · {item.files ?? 0} file</span>
          </button>
          <button class="button ghost size-8 !p-0" onclick={() => load(item.path)} aria-label={`Buka ${item.name}`}><ChevronRight size={16}/></button>
        </div>
      {:else}
        <div class="py-10 text-center"><Folder class="mx-auto mb-2 text-violet-400" size={28}/><p class="font-semibold">Tidak ada subfolder.</p></div>
      {/each}
    </div>
  {/if}
</div>

{#if selected.length}
  <div class="mt-3 flex flex-wrap gap-2">
    {#each selected as path}
      <button class="rounded-full border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs font-bold text-violet-700 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200" onclick={() => choose(path)}>{path} ×</button>
    {/each}
  </div>
{/if}
