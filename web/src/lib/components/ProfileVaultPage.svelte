<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { CircleAlert, RefreshCw, ShieldCheck, Trash2 } from '@lucide/svelte';

  type Worker = { name: string; enabled: boolean; online: boolean; secure: boolean };
  type WorkerState = {
    worker: string;
    status: string;
    error?: string;
    desired_revision?: number | null;
    installed_revision?: number | null;
    vault_ack_status?: string;
    vault_ack_installed_revision?: number | null;
    runtime_status?: string;
    runtime_error_code?: string;
    runtime_desired_revision?: number | null;
    runtime_installed_revision?: number | null;
  };
  type Profile = { name: string; status: string; vault: boolean; error?: string; workers: WorkerState[] };
  type Management = { items: Profile[]; workers: Worker[] };
  type SyncEvent = {
    id: number; run_id: string; sequence: number | null; revision: number | null;
    phase: string; status: string; code: string; created_at: string;
    details?: Record<string, number>;
  };
  type SyncHistory = { items: SyncEvent[]; active: boolean; next_after_id: number };

  let profiles = $state<Profile[]>([]);
  let workers = $state<Worker[]>([]);
  let loading = $state(false);
  let failure = $state('');
  let notice = $state('');
  let checkedAt = $state('');
  let deletingProfile = $state('');
  let syncHistories = $state<Record<string, SyncHistory>>({});

  const workerByName = $derived(new Map(workers.map((worker) => [worker.name, worker])));
  const statusLabel = (status: string) => ({
    ready: 'Siap', stored: 'Tersimpan di Vault', queued: 'Dalam antrean', running: 'Berjalan', waiting: 'Menunggu', waiting_worker: 'Menunggu worker', sync_pending: 'Belum tersinkron',
    succeeded: 'Selesai', cancelled: 'Dibatalkan',
    not_assigned: 'Belum ditugaskan', worker_unavailable: 'Worker tidak terjangkau', worker_update_required: 'Perlu diperbarui',
    failed: 'Gagal', unavailable: 'Tidak tersedia'
  } as Record<string, string>)[status] || status || 'Belum diperiksa';
  const phaseLabel = (phase: string) => ({
    queued: 'Antrean', manifest_fetch: 'Baca daftar profil', revision_compare: 'Bandingkan revision',
    bundle_download: 'Unduh bundle', bundle_validation: 'Validasi bundle',
    session_validation: 'Validasi sesi', session_install: 'Pasang sesi', session_commit: 'Simpan sesi',
    acknowledgement: 'Konfirmasi ke Vault', worker_unreachable: 'Worker tidak terjangkau',
    completed: 'Selesai', cancelled: 'Dibatalkan'
  } as Record<string, string>)[phase] || phase;
  const historyKey = (profile: string, worker: string) => `${profile}:${worker}`;

  async function loadSyncHistories() {
    const targets = profiles
      .filter((profile) => profile.vault)
      .flatMap((profile) => profile.workers.map((worker) => ({ profile: profile.name, worker: worker.worker })));
    await Promise.all(targets.map(async ({ profile, worker }) => {
      const key = historyKey(profile, worker);
      try {
        const result = await api<SyncHistory>(`/profiles/${encodeURIComponent(profile)}/workers/${encodeURIComponent(worker)}/sync-logs?limit=50`);
        syncHistories = { ...syncHistories, [key]: result };
      } catch {
        syncHistories = { ...syncHistories, [key]: { items: [], active: false, next_after_id: 0 } };
      }
    }));
  }

  function runtimeMessage(item: WorkerState, worker?: Worker) {
    if (item.runtime_status === 'ready' && item.runtime_installed_revision === item.desired_revision) {
      return `Sesi runtime sudah siap pada revision ${item.runtime_installed_revision}.`;
    }
    if (worker && !worker.online) return 'Worker sedang offline. Status lokal belum bisa diperiksa.';
    if (item.runtime_error_code) {
      const httpStatus = item.runtime_error_code.match(/^PROFILE_BACKEND_HTTP_(\d{3})$/)?.[1];
      if (httpStatus) return `Worker menerima penolakan manifest dari backend (HTTP ${httpStatus}; ${item.runtime_error_code}).`;
      if (item.runtime_error_code === 'WORKER_IDENTITY_AMBIGUOUS') return 'Token worker dipakai bersama. Setiap worker harus memiliki token internal yang unik.';
      if (item.runtime_error_code === 'WORKER_UNAUTHORIZED') return 'WORKER_API_TOKEN pada worker tidak cocok dengan token worker di registry backend. Pulihkan token yang terdaftar, lalu rotasi dari halaman Workers.';
      if (item.runtime_error_code === 'INTERNAL_UNAUTHORIZED') return 'BACKEND_INTERNAL_TOKEN pada worker tidak cocok dengan token internal backend.';
      if (item.runtime_error_code === 'PROFILE_BACKEND_UNAUTHORIZED') return 'Backend tidak menerima token internal worker.';
      if (item.runtime_error_code === 'PROFILE_BACKEND_FORBIDDEN') return 'Backend menolak identitas worker.';
      if (item.runtime_error_code === 'PROFILE_TRANSFER_REQUIRES_HTTPS') return 'Worker perlu memakai URL backend HTTPS.';
      if (item.runtime_error_code === 'BACKEND_UNAVAILABLE') return 'Worker belum dapat menjangkau backend.';
      return `Pemeriksaan runtime gagal (${item.runtime_error_code}).`;
    }
    if (item.runtime_status === 'waiting_worker') return 'Worker belum berhasil membaca manifest vault dari backend.';
    if (item.runtime_status === 'sync_pending') return 'Worker belum mengonfirmasi revision vault yang diinginkan.';
    if (item.runtime_status === 'worker_update_required') return 'Perbarui worker untuk membaca status sinkronisasi profil.';
    return item.error || 'Kesiapan sesi runtime belum dikonfirmasi.';
  }

  function runtimeReady(item: WorkerState) {
    return item.runtime_status === 'ready'
      && item.runtime_desired_revision === item.desired_revision
      && item.runtime_installed_revision === item.desired_revision;
  }

  async function load() {
    loading = true;
    failure = '';
    try {
      const result = await api<Management>('/profiles/management');
      profiles = Array.isArray(result.items) ? result.items : [];
      workers = Array.isArray(result.workers) ? result.workers : [];
      checkedAt = new Date().toLocaleString();
      await loadSyncHistories();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Status Vault gagal dimuat.';
    } finally {
      loading = false;
    }
  }

  async function deleteBundle(profile: Profile) {
    if (deletingProfile) return;
    if (typeof window !== 'undefined' && !window.confirm(`Hapus bundle terenkripsi "${profile.name}" dari Vault? Sesi pada worker lokal tidak akan dihapus atau diubah.`)) return;
    deletingProfile = profile.name;
    failure = '';
    notice = '';
    try {
      await api(`/profiles/${encodeURIComponent(profile.name)}/vault`, { method: 'DELETE' });
      profiles = profiles.map((item) => item.name === profile.name
        ? { ...item, vault: false, status: 'legacy', workers: [], error: undefined }
        : item);
      notice = `Bundle ${profile.name} dihapus dari Vault. Sesi worker lokal tetap utuh.`;
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : `Bundle ${profile.name} gagal dihapus dari Vault.`;
    } finally {
      deletingProfile = '';
    }
  }

  onMount(() => {
    void load();
    const timer = window.setInterval(() => {
      if (Object.values(syncHistories).some((history) => history.active)) void loadSyncHistories();
    }, 3000);
    return () => window.clearInterval(timer);
  });
</script>

<svelte:head><title>Vault profil · tme3</title></svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">PROFIL BERSAMA</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Vault profil</h1>
    <p class="muted mt-2">Bandingkan ACK Vault dengan kesiapan sesi TDL yang benar-benar dilaporkan tiap worker.</p>
  </div>
  <div class="flex items-center gap-2">
    <a class="button secondary" href="/profiles/">Profil lokal</a>
    <button class="button secondary" onclick={load} disabled={loading} aria-label="Muat ulang status Vault">
      <RefreshCw size={16}/>{loading ? 'Memeriksa...' : 'Muat ulang'}
    </button>
  </div>
</header>

{#if failure}
  <div class="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100" role="alert">
    <CircleAlert size={17} class="mt-0.5 shrink-0"/>{failure}
  </div>
{/if}
{#if notice}
  <p class="mt-5 text-sm text-violet-700 dark:text-violet-200" role="status">{notice}</p>
{/if}

<section class="card mt-6 p-5 sm:p-6" aria-label="Status Vault">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="font-extrabold">Profil dan kesiapan worker</h2>
      <p class="muted mt-1 text-sm">ACK Vault, revision runtime, dan hasil pemeriksaan worker ditampilkan terpisah.</p>
    </div>
    {#if checkedAt}<p class="muted text-xs">Diperiksa {checkedAt}</p>{/if}
  </div>

  {#if loading && profiles.length === 0}
    <p class="muted mt-5">Memuat status Vault...</p>
  {:else}
    {@const vaultedProfiles = profiles.filter((profile) => profile.vault)}
    {#if vaultedProfiles.length === 0}
      <p class="muted mt-5 rounded-xl border border-dashed border-[var(--line)] p-5 text-center">Belum ada profil yang tersimpan di Vault.</p>
    {:else}
      <div class="mt-5 space-y-4">
        {#each vaultedProfiles as profile (profile.name)}
          <article class="rounded-2xl border border-[var(--line)] bg-[var(--panel-strong)] p-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="font-extrabold">{profile.name}</h3>
              <div class="flex items-center gap-2">
                <span class="badge">{statusLabel(profile.status)}</span>
                <button class="button secondary" onclick={() => deleteBundle(profile)} disabled={Boolean(deletingProfile)} aria-label={`Hapus bundle ${profile.name} dari Vault`}>
                  <Trash2 size={15}/>{deletingProfile === profile.name ? 'Menghapus...' : 'Hapus dari Vault'}
                </button>
              </div>
            </div>
            {#if profile.error}<p class="mt-2 text-sm text-rose-600">{profile.error}</p>{/if}
            {#if profile.workers.length === 0}
              <p class="muted mt-3 text-sm">Belum ada status distribusi worker untuk profil ini.</p>
            {:else}
              <div class="mt-3 grid gap-2 lg:grid-cols-2">
                {#each profile.workers as item (`${profile.name}:${item.worker}`)}
                  {@const worker = workerByName.get(item.worker)}
                  {@const history = syncHistories[historyKey(profile.name, item.worker)]}
                  <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <b>{item.worker}</b>
                      <span class={runtimeReady(item) ? 'text-sm font-bold text-emerald-600' : 'text-sm font-bold text-amber-600'}>
                        {runtimeReady(item) ? 'Sesi runtime siap' : statusLabel(item.runtime_status || item.status)}
                      </span>
                    </div>
                    <p class="muted mt-2 text-xs">Vault ACK: {statusLabel(item.vault_ack_status || item.status)} · revision {item.vault_ack_installed_revision ?? item.installed_revision ?? '-'} · Runtime worker: {statusLabel(item.runtime_status || item.status)} · revision {item.runtime_installed_revision ?? '-'}</p>
                    <p class="mt-2 text-sm">{runtimeMessage(item, worker)}</p>
                    {#if item.desired_revision}<p class="muted mt-1 text-xs">Revision tujuan: {item.desired_revision}</p>{/if}
                    <div class="mt-3 border-t border-[var(--line)] pt-3" aria-label={`Riwayat progress ${profile.name} ${item.worker}`}>
                      <div class="flex items-center justify-between gap-2">
                        <h4 class="text-xs font-bold">Riwayat progress</h4>
                        {#if history?.active}<span class="text-xs font-bold text-amber-600">Berjalan</span>{/if}
                      </div>
                      {#if !history}
                        <p class="muted mt-2 text-xs">Memuat event...</p>
                      {:else if history.items.length === 0}
                        <p class="muted mt-2 text-xs">Belum ada event sinkronisasi.</p>
                      {:else}
                        <ol class="mt-2 space-y-2">
                          {#each history.items.slice(-12).reverse() as event (event.id)}
                            <li class="flex items-start justify-between gap-3 text-xs">
                              <span>
                                <b>{phaseLabel(event.phase)}</b>
                                <span class="muted"> · {statusLabel(event.status)}</span>
                                {#if event.code}<span class="muted block">{event.code}</span>{/if}
                              </span>
                              <time class="muted shrink-0" datetime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time>
                            </li>
                          {/each}
                        </ol>
                      {/if}
                    </div>
                    <a class="muted mt-2 inline-block text-xs underline" href={`/api/v1/profiles/${encodeURIComponent(profile.name)}/workers/${encodeURIComponent(item.worker)}/sync-logs?limit=500`} target="_blank" rel="noreferrer">Buka log JSON</a>
                  </div>
                {/each}
              </div>
            {/if}
          </article>
        {/each}
      </div>
    {/if}
  {/if}

  <p class="muted mt-5 flex items-start gap-2 text-xs"><ShieldCheck size={15} class="mt-0.5 shrink-0 text-emerald-600"/>Menghapus bundle hanya mengosongkan Vault; sesi pada worker lokal tetap ada. Adopsi dimulai dari card Profil lokal, sedangkan distribusi adalah operasi terpisah.</p>
</section>
