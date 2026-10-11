<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import { CircleAlert, RefreshCw, ShieldCheck, UserRoundPlus } from '@lucide/svelte';

  type Worker = { name: string; enabled: boolean; selected?: boolean };
  type ProfileCheck = { name: 'identity' | 'root_session' | 'user1_session'; ready: boolean; code: string };
  type LocalProfile = { name: string; ready: boolean; reason_codes: string[]; checks: ProfileCheck[] };
  type Inventory = { worker: string; checked_at: string; items: LocalProfile[] };

  let workers = $state<Worker[]>([]);
  let selectedWorker = $state('');
  let inventory = $state<Inventory | null>(null);
  let loadingWorkers = $state(false);
  let scanning = $state(false);
  let failure = $state('');
  let notice = $state('');

  const checkLabels: Record<ProfileCheck['name'], string> = {
    identity: 'Identitas',
    root_session: 'root',
    user1_session: 'user1'
  };

  const codeMessages: Record<string, string> = {
    PROFILE_IDENTITY_MISSING: 'File identitas tidak ditemukan.',
    PROFILE_IDENTITY_INVALID: 'Identitas profil tidak valid.',
    PROFILE_IDENTITY_UNSAFE: 'File identitas menggunakan path yang tidak aman.',
    PROFILE_ROOT_SESSION_MISSING: 'Sesi root tidak ditemukan.',
    PROFILE_USER1_SESSION_MISSING: 'Sesi user1 tidak ditemukan.',
    PROFILE_ROOT_SESSION_EMPTY: 'Data sesi root kosong.',
    PROFILE_USER1_SESSION_EMPTY: 'Data sesi user1 kosong.',
    PROFILE_SESSION_UNSAFE: 'Sesi berisi path yang tidak aman.',
    PROFILE_SESSION_UNREADABLE: 'Data sesi tidak dapat dibaca.',
    PROFILE_SESSION_BUSY: 'Sesi sedang dipakai job.',
    PROFILE_SESSION_UNAVAILABLE: 'Pemeriksaan sesi tidak tersedia.'
  };

  function codeMessage(code: string) {
    return codeMessages[code] || code;
  }

  function checkedAt(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  async function loadWorkers() {
    loadingWorkers = true;
    failure = '';
    try {
      const result = await api<{ items: Worker[] }>('/workers');
      workers = Array.isArray(result.items) ? result.items : [];
      if (selectedWorker && !workers.some((worker) => worker.name === selectedWorker)) {
        selectedWorker = '';
        inventory = null;
      }
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Daftar worker gagal dimuat.';
    } finally {
      loadingWorkers = false;
    }
  }

  function selectWorker(value: string) {
    selectedWorker = value;
    inventory = null;
    failure = '';
    notice = '';
  }

  function refreshWorkers() {
    inventory = null;
    failure = '';
    notice = selectedWorker
      ? 'Daftar worker diperbarui. Hasil scan sebelumnya dihapus; tekan Scan untuk memeriksa ulang.'
      : '';
    void loadWorkers();
  }

  async function scanProfiles() {
    if (!selectedWorker || scanning) return;
    scanning = true;
    failure = '';
    notice = '';
    inventory = null;
    try {
      inventory = await post<Inventory>(
        `/workers/${encodeURIComponent(selectedWorker)}/profiles/scan`
      );
    } catch (cause) {
      const error = cause as { code?: string; message?: string };
      if (error.code === 'WORKER_UNAVAILABLE') {
        failure = `Worker ${selectedWorker} sedang offline atau tidak dapat dijangkau. Coba Scan lagi setelah worker tersedia.`;
      } else if (error.code === 'WORKER_UPDATE_REQUIRED') {
        failure = `Worker ${selectedWorker} perlu diperbarui agar scan profil lokal tersedia.`;
      } else {
        failure = error.message || 'Scan profil lokal gagal. Coba lagi.';
      }
    } finally {
      scanning = false;
    }
  }

  onMount(() => {
    void loadWorkers();
  });
</script>

<svelte:head><title>Profil lokal · tme3</title></svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">SESI WORKER</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Profil lokal</h1>
    <p class="muted mt-2">Pilih worker lalu scan untuk melihat profil TDL lokal pada worker tersebut.</p>
  </div>
  <div class="page-icon"><UserRoundPlus size={23}/></div>
</header>

{#if failure}
  <div class="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100" role="alert">
    <CircleAlert size={17} class="mt-0.5 shrink-0"/>{failure}
  </div>
{/if}

<section class="card mt-7 p-5 sm:p-6" aria-labelledby="local-profiles-target">
  <div class="flex flex-wrap items-end gap-3">
    <label id="local-profiles-target" class="min-w-56 flex-1 text-sm font-bold">
      Worker
      <select
        class="field mt-2"
        aria-label="Worker"
        value={selectedWorker}
        onchange={(event) => selectWorker(event.currentTarget.value)}
        disabled={loadingWorkers || scanning}
      >
        <option value="">Pilih worker</option>
        {#each workers as worker (worker.name)}
          <option value={worker.name}>{worker.name}{worker.enabled ? '' : ' · nonaktif untuk job baru'}</option>
        {/each}
      </select>
    </label>
    <button class="button secondary" onclick={refreshWorkers} disabled={loadingWorkers || scanning} aria-label="Muat ulang worker">
      <RefreshCw size={16}/>{loadingWorkers ? 'Memuat...' : 'Muat ulang worker'}
    </button>
    <button class="button" onclick={scanProfiles} disabled={!selectedWorker || scanning || loadingWorkers}>
      <RefreshCw size={16}/>{scanning ? 'Memindai...' : 'Scan'}
    </button>
  </div>
  <p class="muted mt-3 flex items-start gap-2 text-xs">
    <ShieldCheck size={15} class="mt-0.5 shrink-0"/>
    Scan membaca snapshot lokal worker setelah tombol ditekan. Hasil tidak diperbarui otomatis; scan ulang untuk memeriksa kondisi terbaru.
  </p>
  {#if notice}
    <p class="mt-3 text-sm text-violet-700 dark:text-violet-200" role="status">{notice}</p>
  {/if}
</section>

{#if inventory}
  <section class="card mt-5 p-5 sm:p-6" aria-label="Hasil scan profil lokal">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="font-extrabold">Hasil scan · {inventory.worker}</h2>
        <p class="muted mt-1 text-sm">Diperiksa {checkedAt(inventory.checked_at)}</p>
      </div>
      <span class="badge">{inventory.items.length} profil</span>
    </div>

    {#if inventory.items.length === 0}
      <p class="muted mt-5 rounded-xl border border-dashed border-[var(--line)] p-5 text-center">Worker ini tidak memiliki profil lokal yang ditemukan.</p>
    {:else}
      <div class="mt-5 grid gap-3 lg:grid-cols-2">
        {#each inventory.items as profile (profile.name)}
          <article class="rounded-2xl border border-[var(--line)] bg-[var(--panel-strong)] p-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="font-extrabold">{profile.name}</h3>
              <span class={profile.ready ? 'text-sm font-bold text-emerald-600' : 'text-sm font-bold text-rose-600'}>
                {profile.ready ? 'Sesi tersedia' : 'Perlu diperiksa'}
              </span>
            </div>
            <div class="mt-3 grid gap-2 sm:grid-cols-3">
              {#each profile.checks as check (check.name)}
                <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                  <p class="text-sm font-bold">{checkLabels[check.name]} · {check.ready ? 'Siap' : 'Gagal'}</p>
                  {#if !check.ready}<p class="muted mt-1 text-xs">{codeMessage(check.code)}</p>{/if}
                </div>
              {/each}
            </div>
            {#if profile.reason_codes.length}
              <p class="mt-3 text-xs text-rose-600">Kode: {profile.reason_codes.join(', ')}</p>
            {/if}
          </article>
        {/each}
      </div>
    {/if}
  </section>
{:else}
  <section class="card muted mt-5 p-6 text-center" aria-live="polite">
    {#if scanning}
      Memindai profil lokal pada {selectedWorker}...
    {:else if selectedWorker}
      Tekan Scan untuk memeriksa profil lokal pada {selectedWorker}.
    {:else}
      Pilih worker untuk memulai.
    {/if}
  </section>
{/if}
