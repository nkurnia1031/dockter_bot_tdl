<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import WorkspaceExplorer from './WorkspaceExplorer.svelte';
  import TargetPicker from './TargetPicker.svelte';
  import JobTable from './JobTable.svelte';
  import { FolderCog, Play, Plus, Trash2 } from '@lucide/svelte';

  let selected = $state<string[]>([]);
  let saved = $state<string[]>([]);
  let utility = $state('pindah');
  let password = $state('');
  let pending = $state(false);
  let message = $state('');
  let worker = $state('');
  let verified = $state<any>(null);

  async function loadSaved() {
    try { saved = (await api<{items:string[]}>('/utility/folders')).items || []; }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Daftar folder gagal dimuat.'; }
  }
  async function saveFolders() {
    for (const path of selected.filter((item) => !saved.includes(item))) await post('/utility/folders', { path });
    await loadSaved();
  }
  async function run() {
    pending = true;
    try {
      if (!verified || verified.worker !== worker) { message = 'Verifikasi worker terlebih dahulu.'; return; }
      await post('/utility/jobs', { utility, folders: selected, worker, ...(password ? { password } : {}) });
      message = `${selected.length} folder masuk antrean utility.`;
    } catch (cause) { message = cause instanceof Error ? cause.message : 'Utility gagal dibuat.'; }
    finally { pending = false; }
  }
  onMount(loadSaved);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">UTILITY</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Utility workspace</h1><p class="muted mt-2">Jelajahi folder pada worker aktif dan proses beberapa folder sekaligus.</p></div><div class="page-icon"><FolderCog size={23}/></div></header>

<div class="mt-7 grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
  <section class="card p-5 sm:p-6">
    <h2 class="font-extrabold">Worker dan folder workspace</h2><p class="muted mb-4 mt-1 text-sm">Utility berjalan pada worker yang dipilih, tanpa bergantung profile actor.</p>
    <TargetPicker purpose="utility" requireProfile={false} bind:worker bind:verified />
    <div class="mt-4"><WorkspaceExplorer bind:selected {worker} /></div>
  </section>
  <section class="card p-5 sm:p-6">
    <label class="block text-sm font-bold">Jenis operasi<select class="field mt-2" bind:value={utility}><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option></select></label>
    {#if utility === 'extract'}<label class="mt-4 block text-sm font-bold">Password arsip<input class="field mt-2" type="password" bind:value={password} autocomplete="new-password" placeholder="Kosongkan untuk default"/></label>{/if}
    <div class="mt-5 flex flex-wrap gap-2"><button class="button" onclick={run} disabled={!selected.length || pending}><Play size={16}/>{pending ? 'Menambahkan...' : 'Jalankan utility'}</button><button class="button secondary" onclick={saveFolders} disabled={!selected.length}><Plus size={16}/>Simpan pilihan</button></div>
    {#if message}<p class="mt-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
    <div class="mt-7"><h3 class="font-bold">Folder tersimpan</h3><div class="mt-2 space-y-2">{#each saved as path}<div class="flex items-center justify-between gap-2 rounded-xl border border-[var(--line)] px-3 py-2"><button class="min-w-0 truncate text-left font-mono text-xs" onclick={() => selected = selected.includes(path) ? selected : [...selected, path]}>{path}</button><button class="button ghost size-8 !p-0 text-rose-600" aria-label={`Hapus ${path}`} onclick={async () => { await remove(`/utility/folders?path=${encodeURIComponent(path)}`); await loadSaved(); }}><Trash2 size={15}/></button></div>{:else}<p class="muted text-sm">Belum ada folder tersimpan.</p>{/each}</div></div>
  </section>
</div>
<JobTable kind="utility" title="Riwayat utility"/>
