<script lang="ts">
  import { onDestroy } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import WorkspaceExplorer from './WorkspaceExplorer.svelte';
  import TargetPicker from './TargetPicker.svelte';
  import JobTable from './JobTable.svelte';
  import { FolderCog, Play, Plus, Trash2 } from '@lucide/svelte';

  type Job = Record<string, any>;
  type FlattenAction = {
    type: 'delete_empty' | 'move' | 'skip_multiple';
    folder: string;
    source?: string;
    destination?: string;
    collision?: boolean;
    item_count?: number;
  };
  type FlattenDetail = {
    folder: string;
    flatten_preview: {
      fingerprint: string;
      passes: { index: number; actions: FlattenAction[] }[];
      action_count: number;
      moves: number;
      deleted: number;
      skipped: number;
    };
  };
  type FlattenPreviewState = {
    selectionKey: string;
    details: FlattenDetail[];
    fingerprints: Record<string, string>;
    summary: Record<string, number>;
  };

  let selected = $state<string[]>([]);
  let saved = $state<string[]>([]);
  let utility = $state('pindah');
  let password = $state('');
  let pending = $state(false);
  let message = $state('');
  let worker = $state('');
  let flattenPreview = $state<FlattenPreviewState | null>(null);
  let pageDisposed = false;

  const selectionKey = () => JSON.stringify({ worker, folders: [...selected].sort() });
  const currentFlattenPreview = $derived(
    utility === 'flatten' && flattenPreview?.selectionKey === selectionKey()
      ? flattenPreview
      : null
  );
  const terminalStates = new Set(['succeeded', 'failed', 'cancelled']);

  async function loadSaved() {
    try { saved = (await api<{items:string[]}>('/utility/folders')).items || []; }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Daftar folder gagal dimuat.'; }
  }

  async function saveFolders() {
    for (const path of selected.filter((item) => !saved.includes(item))) await post('/utility/folders', { path });
    await loadSaved();
  }

  async function waitForJob(jobId: string): Promise<Job | null> {
    while (!pageDisposed) {
      const job = await api<Job>(`/jobs/${encodeURIComponent(jobId)}`);
      if (terminalStates.has(String(job.status))) return job;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    return null;
  }

  function jobResult(job: Job): Record<string, any> {
    const result = job.result?.value || job.result || {};
    return result && typeof result === 'object' ? result : {};
  }

  async function previewFlatten() {
    if (!selected.length) return;
    const previewKey = selectionKey();
    pending = true;
    flattenPreview = null;
    try {
      const submitted = await post<Job>('/utility/jobs', {
        utility: 'flatten', folders: selected, worker, flatten_action: 'preview'
      });
      if (!submitted.id) throw new Error('Job preview tidak mengembalikan ID.');
      message = 'Menyusun preview Flatten...';
      const job = await waitForJob(String(submitted.id));
      if (!job) return;
      if (job.status !== 'succeeded') {
        message = String(job.error?.message || 'Preview Flatten gagal.');
        return;
      }
      const result = jobResult(job);
      const details = Array.isArray(result.details)
        ? result.details.filter((item: any) => item?.flatten_preview?.fingerprint)
        : [];
      if (details.length !== selected.length) {
        throw new Error('Hasil preview tidak mencakup semua folder pilihan.');
      }
      if (selectionKey() !== previewKey) {
        message = 'Pilihan worker atau folder berubah. Buat preview baru.';
        return;
      }
      const fingerprints = Object.fromEntries(
        details.map((item: FlattenDetail) => [item.folder, item.flatten_preview.fingerprint])
      );
      flattenPreview = {
        selectionKey: previewKey,
        details,
        fingerprints,
        summary: result.summary || {}
      };
      const actionCount = Number(result.summary?.action_count || 0);
      message = actionCount
        ? `Preview siap: ${actionCount} tindakan pada ${details.length} folder.`
        : 'Preview selesai. Tidak ada perubahan yang perlu diterapkan.';
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Preview Flatten gagal dibuat.';
    } finally {
      pending = false;
    }
  }

  async function applyFlatten() {
    const preview = currentFlattenPreview;
    if (!preview || !preview.summary.action_count || pending) return;
    const confirmed = window.confirm(
      `Terapkan ${preview.summary.action_count} tindakan Flatten pada ${preview.details.length} folder?`
    );
    if (!confirmed) return;

    pending = true;
    try {
      const submitted = await post<Job>('/utility/jobs', {
        utility: 'flatten',
        folders: preview.details.map((item) => item.folder),
        worker,
        flatten_action: 'apply',
        flatten_fingerprints: preview.fingerprints
      });
      if (!submitted.id) throw new Error('Job apply tidak mengembalikan ID.');
      flattenPreview = null;
      message = 'Apply Flatten berjalan pada worker terpilih...';
      const job = await waitForJob(String(submitted.id));
      if (!job) return;
      message = job.status === 'succeeded'
        ? 'Flatten selesai.'
        : String(job.error?.message || 'Apply Flatten gagal. Buat preview baru sebelum mencoba lagi.');
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Apply Flatten gagal dibuat.';
    } finally {
      pending = false;
    }
  }

  async function run() {
    if (utility === 'flatten') {
      await previewFlatten();
      return;
    }
    pending = true;
    try {
      await post('/utility/jobs', { utility, folders: selected, worker, ...(password ? { password } : {}) });
      message = `${selected.length} folder masuk antrean utility.`;
    } catch (cause) { message = cause instanceof Error ? cause.message : 'Utility gagal dibuat.'; }
    finally { pending = false; }
  }

  function changeUtility(event: Event) {
    utility = (event.currentTarget as HTMLSelectElement).value;
    flattenPreview = null;
    if (utility !== 'extract') password = '';
    message = '';
  }

  onDestroy(() => { pageDisposed = true; });
  void loadSaved();
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">UTILITY</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Utility workspace</h1><p class="muted mt-2">Jelajahi folder pada worker aktif dan proses beberapa folder sekaligus.</p></div><div class="page-icon"><FolderCog size={23}/></div></header>

<div class="mt-7 grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
  <section class="card p-5 sm:p-6">
    <h2 class="font-extrabold">Worker dan folder workspace</h2><p class="muted mb-4 mt-1 text-sm">Utility berjalan pada worker yang dipilih, tanpa bergantung profile actor.</p>
    <TargetPicker purpose="utility" requireProfile={false} bind:worker requiresVerification={false} showReadiness={false} />
    <div class="mt-4"><WorkspaceExplorer bind:selected {worker} /></div>
  </section>
  <section class="card p-5 sm:p-6">
    <label class="block text-sm font-bold">Jenis operasi<select class="field mt-2" value={utility} onchange={changeUtility}><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option><option value="flatten">Flatten folder</option></select></label>
    {#if utility === 'extract'}<label class="mt-4 block text-sm font-bold">Password arsip<input class="field mt-2" type="password" bind:value={password} autocomplete="new-password" placeholder="Kosongkan untuk default"/></label>{/if}
    <div class="mt-5 flex flex-wrap gap-2"><button class="button" onclick={run} disabled={!selected.length || pending}><Play size={16}/>{pending ? 'Memproses...' : utility === 'flatten' ? 'Preview Flatten' : 'Jalankan utility'}</button><button class="button secondary" onclick={saveFolders} disabled={!selected.length || pending}><Plus size={16}/>Simpan pilihan</button></div>
    {#if message}<p class="mt-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm" role="status">{message}</p>{/if}

    {#if currentFlattenPreview}
      <section class="mt-5 rounded-xl border border-[var(--line)] p-4" aria-label="Preview Flatten">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div><h3 class="font-bold">Preview Flatten</h3><p class="muted mt-1 text-sm">{currentFlattenPreview.summary.moves || 0} pindah · {currentFlattenPreview.summary.deleted || 0} hapus · {currentFlattenPreview.summary.skipped || 0} dilewati</p></div>
          {#if currentFlattenPreview.summary.action_count}<button class="button danger" onclick={applyFlatten} disabled={pending}>Terapkan Flatten</button>{/if}
        </div>
        <div class="mt-4 space-y-4">
          {#each currentFlattenPreview.details as detail}
            <article class="rounded-lg bg-[var(--surface-soft)] p-3">
              <h4 class="break-all font-mono text-xs font-bold">{detail.folder}</h4>
              {#each detail.flatten_preview.passes as pass}
                <div class="mt-3">
                  <p class="muted text-xs font-semibold">Putaran {pass.index}</p>
                  <ul class="mt-1 space-y-1 text-sm">
                    {#each pass.actions as action, index (`${pass.index}:${index}`)}
                      <li>
                        {#if action.type === 'delete_empty'}Hapus folder kosong: <code>{action.folder}</code>
                        {:else if action.type === 'move'}Pindah <code>{action.source}</code> → <code>{action.destination}</code> (hapus <code>{action.folder}</code>){#if action.collision} · nama bentrok, diberi prefix{/if}
                        {:else}Lewati <code>{action.folder}</code> ({action.item_count} item){/if}
                      </li>
                    {/each}
                  </ul>
                </div>
              {/each}
            </article>
          {/each}
        </div>
      </section>
    {/if}

    <div class="mt-7"><h3 class="font-bold">Folder tersimpan</h3><div class="mt-2 space-y-2">{#each saved as path}<div class="flex items-center justify-between gap-2 rounded-xl border border-[var(--line)] px-3 py-2"><button class="min-w-0 truncate text-left font-mono text-xs" onclick={() => selected = selected.includes(path) ? selected : [...selected, path]}>{path}</button><button class="button ghost size-8 !p-0 text-rose-600" aria-label={`Hapus ${path}`} onclick={async () => { await remove(`/utility/folders?path=${encodeURIComponent(path)}`); await loadSaved(); }}><Trash2 size={15}/></button></div>{:else}<p class="muted text-sm">Belum ada folder tersimpan.</p>{/each}</div></div>
  </section>
</div>
<JobTable kind="utility" title="Riwayat utility"/>
