<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, patch, post, put, remove } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { CheckCircle2, Pencil, Plus, RefreshCw, Server, Settings2, Trash2 } from '@lucide/svelte';

  type Worker = { name: string; url: string; enabled?: boolean; selected?: boolean; healthy?: boolean; latency_ms?: number };
  type WorkerSettings = {
    worker: string;
    worker_api_token_configured: boolean;
    job_stall_timeout_seconds: number;
    tdl_export_stall_timeout_seconds: number;
    tdl_download_stall_timeout_seconds: number;
    storage_profile: string;
    storage_profile_available: boolean;
    available_storage_profiles: string[];
    tts_helper_urls: string[];
    tts_part_retries: number;
    tts_retry_base_seconds: number;
    tts_newnym_after_retries: number;
  };
  type TtsDraft = {
    helper_urls: string;
    part_retries: string;
    retry_base_seconds: string;
    newnym_after_retries: string;
  };
  type WorkerOpsDraft = { job_stall: string; export_stall: string; download_stall: string };
  let workers = $state<Worker[]>([]);
  let name = $state(''); let url = $state(''); let token = $state(''); let message = $state('');
  let editing = $state<Worker|null>(null); let deleting = $state<Worker|null>(null); let editOpen = $state(false); let deleteOpen = $state(false); let editUrl = $state(''); let editToken = $state('');
  let settingsOpen = $state('');
  let workerSettings = $state<Record<string, WorkerSettings>>({});
  let storageProfileDrafts = $state<Record<string, string>>({});
  let ttsDrafts = $state<Record<string, TtsDraft>>({});
  let opsDrafts = $state<Record<string, WorkerOpsDraft>>({});
  let settingsLoading = $state<Record<string, boolean>>({});
  let settingsSaving = $state<Record<string, boolean>>({});
  async function load() { try { workers = (await api<{items:Worker[]}>('/workers')).items || []; } catch (cause) { message = cause instanceof Error ? cause.message : 'Worker gagal dimuat.'; } }
  async function add() { await post('/workers', { name, url, token }); name = url = token = ''; message = 'Worker ditambahkan.'; await load(); }
  async function select(worker: Worker) {
    if (worker.enabled === false) return;
    await session.chooseWorker(worker.name);
    message = `Job baru akan memakai ${worker.name}.`;
    await load();
  }
  async function toggle(worker: Worker) {
    try {
      const enabled = worker.enabled === false;
      await patch(`/workers/${encodeURIComponent(worker.name)}`, { enabled });
      message = enabled
        ? `${worker.name} diaktifkan dan dapat menerima job baru.`
        : `${worker.name} dinonaktifkan. Job lama tetap berjalan.`;
      await load();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Status worker gagal diubah.';
    }
  }
  async function loadWorkerSettings(worker: Worker) {
    settingsLoading = { ...settingsLoading, [worker.name]: true };
    try {
      const result = await api<WorkerSettings>(`/workers/${encodeURIComponent(worker.name)}/settings`);
      workerSettings = { ...workerSettings, [worker.name]: result };
      storageProfileDrafts = { ...storageProfileDrafts, [worker.name]: result.storage_profile };
      opsDrafts = { ...opsDrafts, [worker.name]: {
        job_stall: String(result.job_stall_timeout_seconds ?? 600),
        export_stall: String(result.tdl_export_stall_timeout_seconds ?? 300),
        download_stall: String(result.tdl_download_stall_timeout_seconds ?? 300),
      } };
      ttsDrafts = {
        ...ttsDrafts,
        [worker.name]: {
          helper_urls: (result.tts_helper_urls || []).join(', '),
          part_retries: String(result.tts_part_retries ?? 4),
          retry_base_seconds: String(result.tts_retry_base_seconds ?? 2),
          newnym_after_retries: String(result.tts_newnym_after_retries ?? 3),
        },
      };
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Pengaturan runtime worker gagal dimuat.';
    } finally {
      settingsLoading = { ...settingsLoading, [worker.name]: false };
    }
  }
  async function toggleSettings(worker: Worker) {
    if (settingsOpen === worker.name) { settingsOpen = ''; return; }
    settingsOpen = worker.name;
    if (!workerSettings[worker.name]) await loadWorkerSettings(worker);
  }
  async function refreshWorkerSettings(worker: Worker) {
    const next = { ...workerSettings };
    delete next[worker.name];
    workerSettings = next;
    await loadWorkerSettings(worker);
  }
  async function saveStorageProfile(worker: Worker) {
    const storage_profile = storageProfileDrafts[worker.name];
    if (!storage_profile) return;
    settingsSaving = { ...settingsSaving, [worker.name]: true };
    try {
      const result = await put<WorkerSettings>(`/workers/${encodeURIComponent(worker.name)}/settings`, { storage_profile });
      workerSettings = { ...workerSettings, [worker.name]: result };
      storageProfileDrafts = { ...storageProfileDrafts, [worker.name]: result.storage_profile };
      message = `Profil Storage worker ${worker.name} disimpan.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Profil Storage gagal disimpan.';
    } finally {
      settingsSaving = { ...settingsSaving, [worker.name]: false };
    }
  }
  async function saveOperationalSettings(worker: Worker) {
    const draft = opsDrafts[worker.name];
    if (!draft) return;
    settingsSaving = { ...settingsSaving, [worker.name]: true };
    try {
      const result = await put<WorkerSettings>(`/workers/${encodeURIComponent(worker.name)}/settings`, {
        job_stall_timeout_seconds: Number(draft.job_stall),
        tdl_export_stall_timeout_seconds: Number(draft.export_stall),
        tdl_download_stall_timeout_seconds: Number(draft.download_stall),
      });
      workerSettings = { ...workerSettings, [worker.name]: result };
      message = `Timeout worker ${worker.name} disimpan untuk job berikutnya.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Timeout worker gagal disimpan.';
    } finally {
      settingsSaving = { ...settingsSaving, [worker.name]: false };
    }
  }
  function updateTtsDraft(worker: Worker, values: Partial<TtsDraft>) {
    const current = ttsDrafts[worker.name];
    if (current) ttsDrafts = { ...ttsDrafts, [worker.name]: { ...current, ...values } };
  }
  function parseList(value: string): string[] {
    return value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
  }
  async function saveTtsSettings(worker: Worker) {
    const draft = ttsDrafts[worker.name];
    if (!draft) return;
    const payload: Record<string, unknown> = {
      tts_helper_urls: parseList(draft.helper_urls),
      tts_part_retries: Number(draft.part_retries),
      tts_retry_base_seconds: Number(draft.retry_base_seconds),
      tts_newnym_after_retries: Number(draft.newnym_after_retries),
    };
    settingsSaving = { ...settingsSaving, [worker.name]: true };
    try {
      const result = await put<WorkerSettings>(`/workers/${encodeURIComponent(worker.name)}/settings`, payload);
      workerSettings = { ...workerSettings, [worker.name]: result };
      message = `Pengaturan TTS worker ${worker.name} disimpan untuk job berikutnya.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Pengaturan TTS gagal disimpan.';
    } finally {
      settingsSaving = { ...settingsSaving, [worker.name]: false };
    }
  }
  async function update() { if (!editing) return; await put(`/workers/${encodeURIComponent(editing.name)}`, { url: editUrl, token: editToken }); editing = null; editOpen = false; await load(); }
  async function destroy() { if (!deleting) return; await remove(`/workers/${encodeURIComponent(deleting.name)}`); deleting = null; deleteOpen = false; await load(); }
  onMount(() => {
    const refresh = () => load();
    window.addEventListener('tme3:context-changed', refresh);
    load();
    return () => window.removeEventListener('tme3:context-changed', refresh);
  });
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">WORKERS</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Worker & routing</h1><p class="muted mt-2">Route baru hanya berlaku untuk job berikutnya; job lama tetap pada worker asal.</p></div><div class="page-icon"><Server size={23}/></div></header>
{#if message}<p class="mt-5 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
<div class="mt-7 grid gap-5 xl:grid-cols-[.72fr_1.28fr]">
  <section class="card p-5 sm:p-6"><h2 class="font-extrabold">Tambah worker</h2><div class="mt-4 space-y-3"><label class="block text-sm font-bold">Nama<input class="field mt-2" bind:value={name} placeholder="remote-1"/></label><label class="block text-sm font-bold">URL API<input class="field mt-2" bind:value={url} placeholder="https://worker.example.com"/></label><label class="block text-sm font-bold">Token<input class="field mt-2" type="password" bind:value={token} autocomplete="new-password"/></label></div><button class="button mt-5 w-full" onclick={add} disabled={!name || !url || !token}><Plus size={16}/>Tambahkan worker</button></section>
  <section class="card overflow-hidden"><div class="border-b border-[var(--line)] px-5 py-4"><h2 class="font-extrabold">Registry worker</h2><p class="muted mt-1 text-sm">Profile aktif: {session.current.actor?.profile || '-'}</p></div><div class="divide-y divide-[var(--line)]">
    {#each workers as worker}
      <div class="border-b border-[var(--line)] last:border-0">
        <article class="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div class="min-w-0"><div class="flex items-center gap-2"><b>{worker.name}</b>{#if worker.selected}<span class="badge succeeded">Route aktif</span>{/if}{#if worker.enabled === false}<span class="badge failed">Nonaktif</span>{:else}<span class="badge">Siap</span>{/if}</div><p class="muted mt-1 truncate text-sm">{worker.url}</p><p class="muted mt-1 text-xs">{worker.enabled === false ? 'Tidak menerima job baru; job lama tidak dihentikan.' : 'Dapat menerima job baru.'}</p></div>
          <div class="flex flex-wrap gap-2"><button class="button secondary" onclick={() => select(worker)} disabled={worker.selected || worker.enabled === false}><CheckCircle2 size={15}/>Pilih</button><button class={`button ${worker.enabled === false ? '' : 'danger'}`} onclick={() => toggle(worker)}>{worker.enabled === false ? 'Aktifkan' : 'Nonaktifkan'}</button><button class="button secondary" onclick={() => toggleSettings(worker)}><Settings2 size={15}/>{settingsOpen === worker.name ? 'Tutup' : 'Runtime'}</button><button class="button secondary" onclick={() => { editing = worker; editUrl = worker.url; editToken = ''; editOpen = true; }}><Pencil size={15}/>Edit</button><button class="button ghost text-rose-600" onclick={() => { deleting = worker; deleteOpen = true; }}><Trash2 size={15}/></button></div>
        </article>
        {#if settingsOpen === worker.name}
          <section class="border-t border-[var(--line)] bg-[var(--panel)] px-5 py-4">
            <div class="flex items-center justify-between gap-3"><h3 class="text-sm font-extrabold">Pengaturan runtime worker</h3><button class="button ghost !p-2" aria-label="Muat ulang pengaturan worker" title="Muat ulang" onclick={() => refreshWorkerSettings(worker)} disabled={settingsLoading[worker.name]}><RefreshCw size={15}/></button></div>
            <p class="muted mt-1 text-xs">Profil Storage dan TTS berlaku untuk job baru. Token API: {workerSettings[worker.name]?.worker_api_token_configured ? 'sudah diatur' : 'belum diatur'}; token baru bisa dirotasi dari Edit tanpa menampilkan nilai aktif.</p>
            {#if settingsLoading[worker.name]}
              <p class="muted mt-3 text-sm">Memuat pengaturan...</p>
            {:else if workerSettings[worker.name]}
              {@const settings = workerSettings[worker.name]}
              {#if !settings.storage_profile_available}<p class="mt-3 rounded-lg bg-amber-100 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-100">Profil aktif “{settings.storage_profile}” belum memiliki sesi TDL Storage. Siapkan sesi Storage satu kali di mesin worker, lalu muat ulang pengaturan.</p>{/if}
              <div class="mt-3 flex flex-wrap items-end gap-3">
                <label class="min-w-56 flex-1 text-sm font-bold">Profil sesi Storage
                  <select class="field mt-2" value={storageProfileDrafts[worker.name] || ''} onchange={(event) => storageProfileDrafts = { ...storageProfileDrafts, [worker.name]: event.currentTarget.value }}>
                    <option value="" disabled>Pilih profil dengan sesi aktif</option>
                    {#each settings.available_storage_profiles as profile}<option value={profile}>{profile}</option>{/each}
                  </select>
                </label>
                <button class="button" onclick={() => saveStorageProfile(worker)} disabled={!storageProfileDrafts[worker.name] || settingsSaving[worker.name] || storageProfileDrafts[worker.name] === settings.storage_profile}>{settingsSaving[worker.name] ? 'Menyimpan...' : 'Simpan'}</button>
              </div>
              {#if settings.available_storage_profiles.length === 0}<p class="muted mt-2 text-xs">Belum ada sesi Storage yang siap dipilih pada worker ini.</p>{/if}
              {@const tts = ttsDrafts[worker.name]}
              {#if tts}
                <div class="mt-6 border-t border-[var(--line)] pt-5">
                  <div><h4 class="text-sm font-extrabold">Mesin TTS</h4><p class="muted mt-1 text-xs">Setiap helper menjalankan Tor lokal. Worker memakai endpoint internal helper untuk pemeriksaan kesiapan dan rotasi circuit.</p></div>
                  <div class="mt-4 grid gap-3 lg:grid-cols-2">
                    <label class="text-sm font-bold">URL tiga helper gTTS<textarea class="field mt-2 min-h-20" value={tts.helper_urls} oninput={(event) => updateTtsDraft(worker, { helper_urls: event.currentTarget.value })} placeholder="http://tts-1:5000, http://tts-2:5000, http://tts-3:5000"></textarea></label>
                    <label class="text-sm font-bold">Retry per bagian<input class="field mt-2" type="number" min="0" max="10" value={tts.part_retries} oninput={(event) => updateTtsDraft(worker, { part_retries: event.currentTarget.value })}/></label>
                    <label class="text-sm font-bold">Backoff awal (detik)<input class="field mt-2" type="number" min="0.1" max="60" step="0.1" value={tts.retry_base_seconds} oninput={(event) => updateTtsDraft(worker, { retry_base_seconds: event.currentTarget.value })}/></label>
                    <label class="text-sm font-bold">Rotasi circuit setelah retry<input class="field mt-2" type="number" min="1" max="20" value={tts.newnym_after_retries} oninput={(event) => updateTtsDraft(worker, { newnym_after_retries: event.currentTarget.value })}/></label>
                  </div>
                  <button class="button mt-4" onclick={() => saveTtsSettings(worker)} disabled={settingsSaving[worker.name]}>{settingsSaving[worker.name] ? 'Menyimpan...' : 'Simpan pengaturan TTS'}</button>
                </div>
              {/if}
              {@const ops = opsDrafts[worker.name]}
              {#if ops}
                <div class="mt-6 border-t border-[var(--line)] pt-5">
                  <h4 class="text-sm font-extrabold">Timeout job worker</h4>
                  <p class="muted mt-1 text-xs">Angka 0 menonaktifkan batas stall. Perubahan hanya berlaku untuk job berikutnya dan ditolak saat worker sedang menjalankan job.</p>
                  <div class="mt-4 grid gap-3 sm:grid-cols-3">
                    <label class="text-sm font-bold">Semua job<input class="field mt-2" type="number" min="0" max="86400" value={ops.job_stall} oninput={(event) => opsDrafts = { ...opsDrafts, [worker.name]: { ...ops, job_stall: event.currentTarget.value } }}/></label>
                    <label class="text-sm font-bold">Export TDL<input class="field mt-2" type="number" min="0" max="86400" value={ops.export_stall} oninput={(event) => opsDrafts = { ...opsDrafts, [worker.name]: { ...ops, export_stall: event.currentTarget.value } }}/></label>
                    <label class="text-sm font-bold">Download TDL<input class="field mt-2" type="number" min="0" max="86400" value={ops.download_stall} oninput={(event) => opsDrafts = { ...opsDrafts, [worker.name]: { ...ops, download_stall: event.currentTarget.value } }}/></label>
                  </div>
                  <button class="button mt-4" onclick={() => saveOperationalSettings(worker)} disabled={settingsSaving[worker.name]}>{settingsSaving[worker.name] ? 'Menyimpan...' : 'Simpan timeout'}</button>
                </div>
              {/if}
            {/if}
          </section>
        {/if}
      </div>
    {:else}<p class="muted p-6 text-center">Belum ada worker.</p>{/each}
  </div></section>
</div>

<Modal bind:open={editOpen} title={editing ? `Edit ${editing.name}` : 'Edit worker'} size="md">{#if editing}<div class="space-y-3"><label class="block text-sm font-bold">URL<input class="field mt-2" bind:value={editUrl}/></label><label class="block text-sm font-bold">Token API baru<input class="field mt-2" type="password" bind:value={editToken} autocomplete="new-password" placeholder="Kosongkan agar tetap sama"/></label><p class="muted text-xs">Token worker dirotasi melalui koneksi internal. Jika koneksi sama, perubahan langsung berlaku di worker dan gateway.</p></div><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => editOpen = false}>Batal</button><button class="button" onclick={update} disabled={!editUrl}>Simpan</button></div>{/if}</Modal>
<Modal bind:open={deleteOpen} title="Hapus worker?" size="sm"><p>Worker <b>{deleting?.name}</b> akan dihapus dari registry. Job yang sudah dibuat tidak dipindahkan.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => deleteOpen = false}>Batal</button><button class="button danger" onclick={destroy}>Hapus</button></div></Modal>
