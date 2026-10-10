<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { CircleAlert, KeyRound, Plus, RefreshCw, ShieldCheck, Upload, UserRoundPlus, X } from '@lucide/svelte';

  type Worker = { name: string; enabled: boolean; online: boolean; secure: boolean };
  type WorkerState = { worker: string; status: string; error?: string; desired_revision?: number | null; installed_revision?: number | null; installed_sha256?: string; sync_requested?: boolean };
  type Profile = { name: string; active: boolean; status: string; source?: string; vault: boolean; adoptable?: boolean; operation_id?: string; bootstrap_worker?: string; error?: string; workers: WorkerState[] };
  type Operation = { id: string; profile: string; status: string; source: string; bootstrap_worker?: string; error?: string; workers: WorkerState[]; login?: { status: string; step?: string; qr_text?: string; error?: string } };
  type AdoptionCheck = { profile: string; worker: string; ready: boolean; reason_codes: string[]; checks: { name: string; ready: boolean; code?: string }[]; logs_url: string };
  type SyncOperation = { operation_id: string; kind: string; profile: string; status: string; phase: string; target?: { profile?: string; worker?: string; desired_revision?: number }; progress?: Record<string, any>; error?: { code?: string; message?: string } | null; dismissed?: boolean };
  type WorkerProfileSync = { worker: string; status: string; error_code?: string; backend_available: boolean | null; last_checked_at: string; profiles: Record<string, { status: string; error_code: string; desired_revision: number | null; installed_revision: number | null }> };
  type SyncLog = { id: number; run_id: string; revision: number | null; phase: string; status: string; code: string; details: Record<string, number>; created_at: string };
  type SyncLogSnapshot = { items: SyncLog[]; next_after_id: number; latest_run_id: string | null; latest_status: string | null; active: boolean };

  let profiles = $state<Profile[]>([]);
  let workers = $state<Worker[]>([]);
  let name = $state('');
  let worker = $state('');
  let method = $state<'qr' | 'code'>('qr');
  let phone = $state('');
  let loginInput = $state('');
  let file = $state<File | null>(null);
  let mode = $state<'upload' | 'login'>('upload');
  let operation = $state<Operation | null>(null);
  let adopting = $state('');
  let adoptWorker = $state('');
  let adoptionCheck = $state<AdoptionCheck | null>(null);
  let checkingAdoption = $state(false);
  let retrySourceWorker = $state('');
  let loading = $state(false);
  let saving = $state(false);
  let message = $state('');
  let failure = $state('');
  let syncOperations = $state<SyncOperation[]>([]);
  let syncOperationsError = $state('');
  let workerProfileSync = $state<Record<string, WorkerProfileSync | { status: 'unavailable'; error_code: string }>>({});
  let syncActionPending = $state<Record<string, boolean>>({});
  let syncLogs = $state<Record<string, SyncLogSnapshot & { error?: string }>>({});
  let syncLogExpanded = $state<Record<string, boolean>>({});
  const syncLogTimers = new Map<string, ReturnType<typeof setTimeout>>();

  const availableWorkers = $derived(workers.filter((item) => item.online && item.secure));
  const workerStatus = (value: string) => ({ ready: 'Siap', waiting: 'Menunggu', failed: 'Perlu dicoba ulang' } as Record<string, string>)[value] || value;
  const profileStatus = (value: string) => ({ active: 'Aktif', legacy: 'Belum diadopsi', authenticating: 'Login TDL', validating: 'Memvalidasi sesi', distributing: 'Sinkronisasi', failed: 'Gagal' } as Record<string, string>)[value] || value;
  const syncActiveStatuses = new Set(['queued', 'running', 'waiting_worker', 'paused', 'cancelling']);

  function operationKey() {
    const nonce = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    return `profile-sync-${nonce}`;
  }

  async function loadSyncOperations(showError = false) {
    try {
      const result = await api<{ items: SyncOperation[] }>('/operations?limit=100');
      syncOperations = (result.items || [])
        .filter((item) => item.kind === 'profile.sync' && !item.dismissed && item.status !== 'succeeded')
        .slice(0, 20);
      syncOperationsError = '';
    } catch (cause) {
      syncOperationsError = cause instanceof Error ? cause.message : 'Status sinkronisasi gagal dimuat.';
      if (showError) failure = `Status operasi sinkronisasi belum dapat dimuat: ${syncOperationsError}`;
    }
  }

  async function loadWorkerSyncStatus(items: Worker[]) {
    const results = await Promise.all(items.map(async (item) => {
      if (!item.online) return [item.name, { status: 'unavailable', error_code: 'WORKER_OFFLINE' }] as const;
      try {
        return [item.name, await api<WorkerProfileSync>(`/workers/${encodeURIComponent(item.name)}/profile-sync`)] as const;
      } catch (cause) {
        const code = (cause as { code?: string })?.code || 'WORKER_UNAVAILABLE';
        return [item.name, { status: 'unavailable', error_code: code }] as const;
      }
    }));
    workerProfileSync = Object.fromEntries(results);
  }

  function syncOperationFor(profile: string, targetWorker: string) {
    return syncOperations.find((item) => item.profile === profile && item.target?.worker === targetWorker && syncActiveStatuses.has(item.status));
  }

  function syncLogKey(profile: string, targetWorker: string) {
    return `${profile}:${targetWorker}`;
  }

  function syncLogUrl(profile: string, targetWorker: string) {
    return `/api/v1/profiles/${encodeURIComponent(profile)}/workers/${encodeURIComponent(targetWorker)}/sync-logs?limit=500`;
  }

  function workerIsOnline(targetWorker: string) {
    return Boolean(workers.find((item) => item.name === targetWorker)?.online);
  }

  function stopSyncLogPolling(key: string) {
    const timer = syncLogTimers.get(key);
    if (timer) clearTimeout(timer);
    syncLogTimers.delete(key);
  }

  function scheduleSyncLogPolling(profile: string, targetWorker: string) {
    const key = syncLogKey(profile, targetWorker);
    stopSyncLogPolling(key);
    if (document.hidden || !workerIsOnline(targetWorker) || !syncLogs[key]?.active) return;
    syncLogTimers.set(key, setTimeout(() => {
      void refreshSyncLog(profile, targetWorker, false);
    }, 2500));
  }

  async function refreshSyncLog(profile: string, targetWorker: string, expand = true) {
    const key = syncLogKey(profile, targetWorker);
    if (expand) syncLogExpanded = { ...syncLogExpanded, [key]: true };
    const previous = syncLogs[key];
    const query = new URLSearchParams({ limit: '100' });
    if (previous?.next_after_id) query.set('after_id', String(previous.next_after_id));
    try {
      const result = await api<SyncLogSnapshot>(`${syncLogUrl(profile, targetWorker).split('?')[0]}?${query}`);
      const items = previous?.next_after_id
        ? [...previous.items, ...(result.items || [])].slice(-200)
        : result.items || [];
      syncLogs = {
        ...syncLogs,
        [key]: { ...result, items, error: undefined }
      };
      if (result.active && workerIsOnline(targetWorker)) scheduleSyncLogPolling(profile, targetWorker);
      else stopSyncLogPolling(key);
    } catch (cause) {
      syncLogs = {
        ...syncLogs,
        [key]: {
          ...(previous || { items: [], next_after_id: 0, latest_run_id: null, latest_status: null, active: false }),
          error: cause instanceof Error ? cause.message : 'Log sinkronisasi gagal dimuat.'
        }
      };
      stopSyncLogPolling(key);
    }
  }

  async function loadVisibleSyncLogs() {
    const targets: Array<[string, string]> = [];
    for (const profile of profiles) {
      if (!profile.vault) continue;
      for (const item of profile.workers || []) {
        const local = workerProfileSync[item.worker];
        const localProfile = local && 'profiles' in local ? local.profiles[profile.name] : undefined;
        const active = syncOperationFor(profile.name, item.worker);
        if (item.status !== 'ready' || localProfile?.status !== 'ready' || active) {
          const key = syncLogKey(profile.name, item.worker);
          syncLogExpanded = { ...syncLogExpanded, [key]: true };
          targets.push([profile.name, item.worker]);
        }
      }
    }
    await Promise.all(targets.map(([profile, targetWorker]) => refreshSyncLog(profile, targetWorker, false)));
  }

  function syncPhaseLabel(phase: string) {
    return ({
      queued: 'Antrean', manifest_fetch: 'Mengambil manifest', revision_compare: 'Memeriksa revision',
      bundle_download: 'Mengunduh bundle', bundle_validation: 'Memvalidasi bundle',
      session_validation: 'Memvalidasi sesi', session_install: 'Memasang sesi',
      session_commit: 'Commit sesi', acknowledgement: 'Konfirmasi backend',
      worker_unreachable: 'Worker tidak terjangkau', completed: 'Selesai', cancelled: 'Dibatalkan'
    } as Record<string, string>)[phase] || phase;
  }

  function syncLogMessage(item: SyncLog) {
    if (item.code === 'PROFILE_SYNC_QUEUED') return 'Sinkronisasi revision masuk antrean.';
    if (item.code === 'WORKER_SYNC_REQUESTED') return 'Perintah sinkronisasi dikirim ke worker.';
    if (item.code === 'REVISION_CURRENT') return 'Revision sudah cocok; bundle tidak dipasang ulang.';
    if (item.code === 'WORKER_UNAVAILABLE' || item.code === 'BACKEND_UNAVAILABLE') return 'Worker atau backend belum dapat dijangkau; akan dicoba lagi saat tersedia.';
    if (item.code === 'PROFILE_SYNC_INSTALLED') return 'Revision sudah terpasang dan dikonfirmasi.';
    if (item.status === 'failed') return `Tahap gagal (${item.code || 'PROFILE_SYNC_FAILED'}).`;
    if (item.status === 'waiting') return `Menunggu koneksi (${item.code || 'WORKER_UNAVAILABLE'}).`;
    if (item.status === 'cancelled') return 'Permintaan sinkronisasi dibatalkan.';
    return `${syncPhaseLabel(item.phase)}${item.revision ? ` · revision ${item.revision}` : ''}.`;
  }

  function profileNeedsRepair(profile: string, item: WorkerState) {
    if (!workerIsOnline(item.worker) || syncOperationFor(profile, item.worker)) return false;
    if (item.status === 'ready' && item.installed_revision === item.desired_revision) return false;
    if (syncLogs[syncLogKey(profile, item.worker)]?.active) return false;
    if (!workers.find((candidate) => candidate.name === item.worker)?.secure) return false;
    const runtime = workerProfileSync[item.worker];
    const local = runtime && 'profiles' in runtime ? runtime.profiles[profile] : undefined;
    if (item.status === 'failed' || Boolean(item.error) || local?.status === 'failed') return true;
    if (local?.error_code && !['', 'WORKER_OFFLINE', 'BACKEND_UNAVAILABLE'].includes(local.error_code)) return true;
    if (item.desired_revision && item.installed_revision !== item.desired_revision) return true;
    return Boolean(local?.desired_revision && local.installed_revision !== local.desired_revision);
  }

  function workerSyncMessage(profile: string, item: WorkerState) {
    const worker = workers.find((candidate) => candidate.name === item.worker);
    const runtime = workerProfileSync[item.worker];
    const local = runtime && 'profiles' in runtime ? runtime.profiles[profile] : undefined;
    if (item.status === 'ready') return `Revision vault ${item.desired_revision ?? local?.desired_revision ?? '-'} sudah terpasang dan dikonfirmasi.`;
    if (!worker?.online || runtime?.error_code === 'WORKER_OFFLINE') return 'Worker offline; revision terbaru akan disinkronkan otomatis saat worker kembali online.';
    if (runtime?.status === 'unavailable') return `Diagnosis worker gagal: ${runtime.error_code}.`;
    if (local?.status === 'ready' && local.installed_revision === item.desired_revision) return `Worker melaporkan revision ${local.installed_revision} siap; backend menunggu konfirmasi distribusi.`;
    if (local?.status === 'waiting_worker' && local.error_code) return `Worker belum dapat menjangkau backend (${local.error_code}).`;
    if (item.status === 'failed' || local?.error_code) return `Sinkronisasi perlu dipulihkan: ${item.error || local?.error_code || 'PROFILE_SYNC_FAILED'}.`;
    if (item.status === 'waiting' || local?.status === 'sync_pending') return `Menunggu revision ${local?.desired_revision ?? '-'} terpasang; lihat log untuk tahap terakhir.`;
    return '';
  }

  function syncOperationMessage(item: SyncOperation) {
    if (item.error?.message) return item.error.message;
    const targetWorker = String(item.target?.worker || 'worker');
    const profile = String(item.target?.profile || item.profile || 'profil');
    const worker = workers.find((candidate) => candidate.name === targetWorker);
    const runtime = workerProfileSync[targetWorker];
    const local = runtime && 'profiles' in runtime ? runtime.profiles[profile] : undefined;
    if (item.status === 'cancelling') return 'Pembatalan sudah dikirim dan sedang diproses.';
    if (item.status === 'waiting_worker' && !worker?.online) return `Worker ${targetWorker} sedang offline. Sinkronisasi menunggu worker aktif; kamu bisa membatalkan operasi ini.`;
    if (item.status === 'waiting_worker' && runtime?.error_code === 'WORKER_UPDATE_REQUIRED') return `Worker ${targetWorker} perlu diperbarui untuk menjalankan sinkronisasi profil.`;
    if (item.status === 'waiting_worker' && local?.error_code) return `Worker ${targetWorker} melaporkan ${local.error_code}. Status sesi: ${local.status}.`;
    if (item.status === 'waiting_worker' && local?.status === 'ready' && local.installed_revision === item.target?.desired_revision) return `Worker ${targetWorker} sudah melaporkan revision siap, tetapi ACK operasi belum diterima. Refresh atau batalkan operasi ini.`;
    if (item.status === 'waiting_worker') return `Worker ${targetWorker} belum mengonfirmasi revision ${item.target?.desired_revision ?? ''}. Periksa status worker atau batalkan operasi ini.`;
    if (item.status === 'queued') return 'Operasi menunggu proses antrean backend.';
    if (item.status === 'running') return `Permintaan sinkronisasi profil ${profile} sedang diteruskan ke worker ${targetWorker}.`;
    if (item.status === 'failed') return 'Sinkronisasi gagal. Periksa status worker, lalu coba sinkronkan ulang.';
    if (item.status === 'cancelled') {
      const cancelStatus = String(item.progress?.worker_sync_cancel || '');
      if (cancelStatus === 'worker_unavailable') return 'Operasi dibatalkan, tetapi worker offline atau tidak dapat dijangkau; pembatalan proses worker belum terkonfirmasi.';
      if (cancelStatus === 'other_requests_pending') return 'Operasi ini dibatalkan. Sinkronisasi worker tetap berjalan karena masih ada operasi lain yang menunggunya.';
      if (cancelStatus === 'cancelling') return 'Operasi dibatalkan. Worker menyelesaikan pemasangan bundle yang sedang berlangsung, lalu berhenti.';
      if (cancelStatus === 'cancelled') return 'Operasi dan permintaan sinkronisasi yang masih antre berhasil dibatalkan.';
      if (cancelStatus === 'unsupported') return 'Operasi dibatalkan, tetapi worker belum mendukung pembatalan proses sinkronisasi.';
      return 'Operasi sinkronisasi dibatalkan; proses worker sudah selesai atau tidak lagi berada di antrean.';
    }
    return `Status sinkronisasi: ${item.status}.`;
  }

  async function load() {
    loading = true;
    try {
      const result = await api<{ items: Profile[]; workers: Worker[] }>('/profiles/management');
      profiles = result.items || [];
      workers = result.workers || [];
      await Promise.all([loadSyncOperations(), loadWorkerSyncStatus(workers)]);
      if (!operation) {
        const pending = profiles.find((item) => item.operation_id && item.status !== 'active' && item.status !== 'legacy');
        if (pending?.operation_id) {
          operation = {
            id: pending.operation_id,
            profile: pending.name,
            status: pending.status,
            source: pending.source || 'upload',
            bootstrap_worker: pending.bootstrap_worker,
            error: pending.error,
            workers: pending.workers || []
          };
        }
      }
      if (!worker || !availableWorkers.some((item) => item.name === worker)) worker = availableWorkers[0]?.name || '';
      if (operation?.id) await refreshOperation(operation.id, false);
      await loadVisibleSyncLogs();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Data profil gagal dimuat.';
    } finally {
      loading = false;
    }
  }

  async function refreshOperation(id: string, showErrors = true) {
    try {
      const previousStatus = operation?.status;
      operation = await api<Operation>(`/profiles/provisionings/${encodeURIComponent(id)}`);
      if (operation.status === 'active' && previousStatus !== 'active') {
        message = `Profil ${operation.profile} siap digunakan.`;
        session.restore();
        name = '';
        phone = '';
        loginInput = '';
        file = null;
      }
    } catch (cause) {
      if (showErrors) failure = cause instanceof Error ? cause.message : 'Status provisioning gagal dimuat.';
    }
  }

  async function submitUpload() {
    if (!file || !name.trim() || !worker || saving) return;
    saving = true; failure = ''; message = '';
    try {
      const query = new URLSearchParams({ name: name.trim(), worker });
      const result = await api<{ id: string; status: string }>(`/profiles/provisionings/upload?${query}`, {
        method: 'POST', body: file, headers: { 'content-type': 'application/zip' }
      });
      operation = { id: result.id, profile: name.trim(), status: result.status, source: 'upload', workers: [] };
      message = 'Sesi valid. Distribusi ke seluruh worker dimulai.';
      await load();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Upload sesi gagal.';
    } finally { saving = false; }
  }

  async function startLogin() {
    if (!name.trim() || !worker || saving || (method === 'code' && !phone.trim())) return;
    saving = true; failure = ''; message = '';
    try {
      const result = await post<{ id: string; status: string }>('/profiles/provisionings/login', {
        name: name.trim(), worker, method, phone: method === 'code' ? phone.trim() : ''
      });
      operation = { id: result.id, profile: name.trim(), status: result.status, source: 'login', workers: [] };
      message = method === 'qr' ? 'QR sedang disiapkan pada worker.' : 'Menunggu kode verifikasi Telegram.';
      await refreshOperation(result.id);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Login TDL gagal dimulai.';
    } finally { saving = false; }
  }

  async function sendLoginInput() {
    if (!operation || !loginInput.trim() || saving) return;
    const step = operation.login?.step || '';
    const field = step === 'password' ? 'password' : 'code';
    saving = true; failure = '';
    try {
      await post(`/profiles/provisionings/${encodeURIComponent(operation.id)}/input`, { field, value: loginInput });
      loginInput = '';
      await refreshOperation(operation.id);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Input login gagal dikirim.';
    } finally { saving = false; }
  }

  async function cancelOperation() {
    if (!operation || saving) return;
    saving = true; failure = '';
    try {
      await remove(`/profiles/provisionings/${encodeURIComponent(operation.id)}`);
      operation = null; message = 'Provisioning dibatalkan.'; await load();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Provisioning tidak dapat dibatalkan.';
    } finally { saving = false; }
  }

  async function retryOperation(id: string, sourceWorker?: string) {
    failure = '';
    try {
      await post(`/profiles/provisionings/${encodeURIComponent(id)}/retry`, sourceWorker ? { worker: sourceWorker } : undefined);
      operation = await api<Operation>(`/profiles/provisionings/${encodeURIComponent(id)}`);
      retrySourceWorker = '';
      await load();
    }
    catch (cause) { failure = cause instanceof Error ? cause.message : 'Retry distribusi gagal.'; }
  }

  async function startProfileSync(profile: string, targetWorker: string, mode: 'check' | 'repair' = 'repair') {
    const key = `${profile}:${targetWorker}`;
    if (syncActionPending[key] || syncOperationFor(profile, targetWorker)) return;
    syncActionPending = { ...syncActionPending, [key]: true };
    failure = '';
    try {
      await api<SyncOperation>('/operations', {
        method: 'POST',
        headers: { 'Idempotency-Key': operationKey() },
        body: JSON.stringify({ kind: 'profile.sync', target: { profile, worker: targetWorker }, input: { mode } })
      });
      message = `Pemulihan revision ${profile} pada ${targetWorker} masuk antrean.`;
      await Promise.all([loadSyncOperations(true), loadWorkerSyncStatus(workers)]);
      await refreshSyncLog(profile, targetWorker, true);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Permintaan sinkronisasi gagal dibuat.';
    } finally {
      const next = { ...syncActionPending };
      delete next[key];
      syncActionPending = next;
    }
  }

  async function cancelProfileSync(item: SyncOperation) {
    const id = item.operation_id;
    if (!id || !syncActiveStatuses.has(item.status) || syncActionPending[id]) return;
    syncActionPending = { ...syncActionPending, [id]: true };
    failure = '';
    try {
      await api(`/operations/${encodeURIComponent(id)}/cancel`, {
        method: 'POST',
        headers: { 'Idempotency-Key': operationKey() }
      });
      message = `Permintaan pembatalan sinkronisasi ${item.profile} pada ${item.target?.worker || 'worker'} dikirim.`;
      await Promise.all([loadSyncOperations(true), refreshSyncLog(item.profile, item.target?.worker || '', true)]);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Operasi sinkronisasi tidak dapat dibatalkan.';
    } finally {
      const next = { ...syncActionPending };
      delete next[id];
      syncActionPending = next;
    }
  }

  async function diagnoseAdoption(profileName: string) {
    if (!adoptWorker || checkingAdoption || saving) return;
    checkingAdoption = true;
    adoptionCheck = null;
    failure = '';
    try {
      adoptionCheck = await post<AdoptionCheck>(`/profiles/${encodeURIComponent(profileName)}/adoption-diagnostics`, { worker: adoptWorker });
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Pemeriksaan sesi worker gagal.';
    } finally {
      checkingAdoption = false;
    }
  }

  async function adoptProfile(profileName: string) {
    if (!adopting || !adoptWorker || !adoptionCheck?.ready || adoptionCheck.profile !== adopting || adoptionCheck.worker !== adoptWorker) return;
    failure = ''; saving = true;
    try {
      const result = await post<{ id: string; status: string }>(`/profiles/${encodeURIComponent(profileName)}/adopt`, { worker: adoptWorker });
      operation = { id: result.id, profile: profileName, status: result.status, source: 'adoption', bootstrap_worker: adoptWorker, workers: [] };
      message = `Ekspor sesi ${profileName} dari ${adoptWorker} berjalan di background. Buka log JSON atau perbarui status untuk melihat hasilnya.`;
      profiles = profiles.map((item) => item.name === profileName
        ? { ...item, status: result.status, source: 'adoption', operation_id: result.id, bootstrap_worker: adoptWorker }
        : item);
      adopting = ''; adoptWorker = ''; adoptionCheck = null;
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Adopsi profil gagal.';
    } finally { saving = false; }
  }

  onMount(() => {
    void load();
    const onVisibilityChange = () => {
      if (document.hidden) {
        for (const key of syncLogTimers.keys()) stopSyncLogPolling(key);
        return;
      }
      for (const profile of profiles) {
        for (const item of profile.workers || []) {
          const key = syncLogKey(profile.name, item.worker);
          if (syncLogs[key]?.active && workerIsOnline(item.worker)) {
            void refreshSyncLog(profile.name, item.worker, false);
          }
        }
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      for (const key of syncLogTimers.keys()) stopSyncLogPolling(key);
    };
  });
</script>

<svelte:head><title>Profil TDL · tme3</title></svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">AKUN TELEGRAM</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Profil TDL</h1><p class="muted mt-2">Tambahkan sesi dari ZIP atau login TDL, lalu distribusikan ke semua worker.</p></div>
  <div class="page-icon"><UserRoundPlus size={23}/></div>
</header>

{#if message}<div class="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">{message}</div>{/if}
{#if failure}<div class="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100"><CircleAlert size={17} class="mt-0.5 shrink-0"/>{failure}</div>{/if}

<div class="mt-7 grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
  <section class="card p-5 sm:p-6">
    <div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={19}/></div><div><h2 class="font-extrabold">Tambah profil</h2><p class="muted text-sm">Gunakan sesi Telegram yang akan menjadi identitas profil.</p></div></div>
    <div class="mt-5 space-y-4">
      <label class="block text-sm font-bold">Nama profil<input class="field mt-2" bind:value={name} maxlength="48" autocomplete="off" placeholder="contoh: irang"/></label>
      <label class="block text-sm font-bold">Worker untuk menyiapkan sesi<select class="field mt-2" bind:value={worker}><option value="">Pilih worker online</option>{#each availableWorkers as item}<option value={item.name}>{item.name}{item.enabled ? '' : ' · nonaktif untuk job baru'}</option>{/each}</select></label>
      {#if availableWorkers.length === 0}<p class="muted rounded-xl border border-amber-300/40 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">Tidak ada worker online dengan transport aman untuk memvalidasi sesi. Worker disabled tetap dapat dipilih jika sedang online. Worker remote perlu URL HTTPS.</p>{/if}
      <div class="grid grid-cols-2 gap-2 rounded-xl bg-[var(--panel-strong)] p-1"><button class:active={mode === 'upload'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => mode = 'upload'}><Upload size={15} class="mr-1 inline"/>Upload ZIP</button><button class:active={mode === 'login'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => mode = 'login'}><KeyRound size={15} class="mr-1 inline"/>Login TDL</button></div>
      {#if mode === 'upload'}
        <label class="block text-sm font-bold">ZIP berisi folder <code>.tdl/</code><input class="field mt-2" type="file" accept=".zip,application/zip" onchange={(event) => file = (event.currentTarget as HTMLInputElement).files?.[0] || null}/></label>
        <p class="muted text-xs">Maksimum 128 MiB. Sesi akan disalin terpisah ke `root/.tdl` dan `user1/.tdl`.</p>
        <button class="button w-full" onclick={submitUpload} disabled={saving || !file || !name.trim() || !worker}><Upload size={16}/>{saving ? 'Memvalidasi...' : 'Validasi dan sebarkan'}</button>
      {:else}
        <div class="grid grid-cols-2 gap-2"><button class:active={method === 'qr'} class="button secondary justify-center" onclick={() => method = 'qr'}>QR</button><button class:active={method === 'code'} class="button secondary justify-center" onclick={() => method = 'code'}>Nomor dan kode</button></div>
        {#if method === 'code'}<label class="block text-sm font-bold">Nomor telepon Telegram<input class="field mt-2" bind:value={phone} type="tel" autocomplete="tel" placeholder="+62..."/></label>{/if}
        <button class="button w-full" onclick={startLogin} disabled={saving || !name.trim() || !worker || (method === 'code' && !phone.trim())}><KeyRound size={16}/>{saving ? 'Menyiapkan...' : 'Mulai login TDL'}</button>
      {/if}
    </div>
  </section>

  <section class="card p-5 sm:p-6">
    <div class="flex items-center justify-between gap-3"><div><h2 class="font-extrabold">Status profil dan worker</h2><p class="muted mt-1 text-sm">Profil baru aktif setelah semua worker awal mengonfirmasi sesi.</p></div><button class="button secondary !px-3" onclick={load} disabled={loading} aria-label="Muat ulang"><RefreshCw size={16}/></button></div>

    {#if operation}
      <article class="mt-5 rounded-2xl border border-violet-300/50 bg-violet-50/50 p-4 dark:bg-violet-950/20">
        <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="text-xs font-bold uppercase tracking-wider text-violet-600">Provisioning {operation.profile}</p><p class="mt-1 font-bold">{profileStatus(operation.status)}</p></div><div class="flex flex-wrap gap-2"><a class="button secondary !px-3 !py-2" href={`/api/v1/profiles/provisionings/${encodeURIComponent(operation.id)}/logs?limit=500`} target="_blank" rel="noreferrer">Log JSON</a><button class="button secondary !px-3 !py-2" onclick={() => refreshOperation(operation!.id)} disabled={loading || saving} aria-label="Perbarui status provisioning"><RefreshCw size={15}/>Perbarui status</button>{#if operation.status !== 'active' && (operation.status !== 'distributing' || operation.source !== 'adoption')}<button class="button secondary !px-3 !py-2" onclick={cancelOperation} disabled={saving}><X size={15}/>Batalkan</button>{/if}</div></div>
        {#if operation.login && operation.status === 'authenticating'}
          <div class="mt-4 space-y-3">
            {#if operation.login.step === 'qr'}
              <p class="muted text-sm">Pindai QR dengan Telegram pada perangkat yang ingin ditambahkan.</p>
              <pre class="qr-screen overflow-x-auto rounded-xl bg-slate-950 p-4 text-center font-mono text-[9px] leading-[.85] text-white">{operation.login.qr_text || 'Menunggu QR dari worker...'}</pre>
            {:else if operation.login.step === 'code' || operation.login.step === 'password'}
              <label class="block text-sm font-bold">{operation.login.step === 'password' ? 'Password 2FA' : 'Kode Telegram'}<input class="field mt-2" bind:value={loginInput} type={operation.login.step === 'password' ? 'password' : 'text'} autocomplete="one-time-code"/></label>
              <button class="button" onclick={sendLoginInput} disabled={saving || !loginInput.trim()}>{operation.login.step === 'password' ? 'Kirim password 2FA' : 'Kirim kode'}</button>
            {:else}<p class="muted text-sm">Menunggu prompt login dari worker...</p>{/if}
            {#if operation.login.error}<p class="text-sm text-rose-600">{operation.login.error}</p>{/if}
          </div>
        {/if}
        {#if operation.status === 'validating'}<p class="muted mt-3 text-sm">Worker memvalidasi sesi TDL di background. Perbarui status untuk melihat hasilnya.</p>{/if}
        {#if operation.error}<p class="mt-3 text-sm text-rose-600">{operation.error}</p>{/if}
        {#if operation.source === 'adoption' && operation.status === 'failed'}
          <div class="mt-4 flex flex-wrap items-end gap-2 rounded-xl border border-rose-300/40 p-3">
            <label class="min-w-48 flex-1 text-xs font-bold">Worker sumber
              <select class="field mt-1" bind:value={retrySourceWorker}><option value="">{operation.bootstrap_worker || 'Pilih worker'}</option>{#each availableWorkers as item}<option value={item.name}>{item.name}</option>{/each}</select>
            </label>
            <button class="button" onclick={() => retryOperation(operation!.id, retrySourceWorker || operation!.bootstrap_worker)} disabled={saving || !availableWorkers.length}><RefreshCw size={15}/>Coba ekspor lagi</button>
          </div>
        {/if}
        {#if operation.workers?.length}<div class="mt-4 grid gap-2 sm:grid-cols-2">{#each operation.workers as item}<div class="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm"><div class="flex items-center justify-between gap-2"><span class="font-semibold">{item.worker}</span><span class="badge">{workerStatus(item.status)}</span></div>{#if item.error}<p class="muted mt-1 text-xs">{item.error}</p>{/if}</div>{/each}</div>{/if}
      </article>
    {/if}

    <div class="mt-5 space-y-3">
      {#each profiles as profile}
        <article class="rounded-2xl border border-[var(--line)] p-4">
          <div class="flex flex-wrap items-center justify-between gap-2"><div class="flex items-center gap-2"><h3 class="font-extrabold">{profile.name}</h3><span class="badge">{profileStatus(profile.status)}</span></div>{#if profile.vault && profile.operation_id && profile.status === 'failed'}<button class="button secondary !px-3 !py-2" onclick={() => retryOperation(profile.operation_id!)}><RefreshCw size={14}/>Retry distribusi</button>{/if}</div>
          {#if profile.workers?.length}
            <div class="mt-3 grid gap-2 sm:grid-cols-2">
              {#each profile.workers as item}
                {@const activeSync = syncOperationFor(profile.name, item.worker)}
                {@const logKey = syncLogKey(profile.name, item.worker)}
                {@const log = syncLogs[logKey]}
                {@const showRepair = profileNeedsRepair(profile.name, item)}
                <div class="rounded-lg bg-[var(--panel-strong)] px-3 py-2 text-xs">
                  <div class="flex items-center justify-between gap-2"><span class="font-semibold">{item.worker}</span><span class={item.status === 'ready' ? 'text-emerald-600' : item.status === 'failed' ? 'text-rose-600' : 'text-amber-600'}>{workerStatus(item.status)}</span></div>
                  {#if item.error}<p class="muted mt-1">{item.error}</p>{:else if profile.vault && workerSyncMessage(profile.name, item)}<p class="muted mt-1">{workerSyncMessage(profile.name, item)}</p>{/if}
                  {#if profile.vault}
                    <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <span class="muted">Runtime worker: {workerProfileSync[item.worker]?.status || 'belum diperiksa'}</span>
                      <div class="flex flex-wrap gap-2">
                        <button class="button secondary !px-2 !py-1 text-[11px]" onclick={() => refreshSyncLog(profile.name, item.worker, !syncLogExpanded[logKey])}>
                          {syncLogExpanded[logKey] ? 'Muat ulang log' : 'Lihat log'}{log?.active ? ' · berjalan' : ''}
                        </button>
                        {#if showRepair}<button class="button secondary !px-2 !py-1 text-[11px]" onclick={() => startProfileSync(profile.name, item.worker, 'repair')} disabled={Boolean(syncActionPending[`${profile.name}:${item.worker}`])}>{syncActionPending[`${profile.name}:${item.worker}`] ? 'Mengirim...' : 'Pulihkan'}</button>{/if}
                        <a class="button secondary !px-2 !py-1 text-[11px]" href={syncLogUrl(profile.name, item.worker)} target="_blank" rel="noreferrer">Log JSON</a>
                      </div>
                    </div>
                    {#if syncLogExpanded[logKey]}
                      <div class="mt-3 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-2">
                        {#if log?.error}<p class="text-rose-600">{log.error}</p>{/if}
                        {#if log?.items?.length}
                          <ol class="space-y-2">
                            {#each log.items as entry (entry.id)}
                              <li class="flex flex-wrap items-start justify-between gap-2 border-b border-[var(--line)] pb-2 last:border-0 last:pb-0">
                                <span><b>{syncPhaseLabel(entry.phase)}</b><span class="muted"> · {syncLogMessage(entry)}</span>{#if entry.revision}<span class="muted"> · rev {entry.revision}</span>{/if}</span>
                                <time class="muted shrink-0" datetime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
                              </li>
                            {/each}
                          </ol>
                        {:else if !log?.error}<p class="muted">Belum ada event sinkronisasi. Worker offline tetap akan mencoba revision terbaru saat aktif.</p>{/if}
                        {#if log?.active && workerIsOnline(item.worker)}<p class="mt-2 text-[11px] text-violet-600">Log diperbarui otomatis selama proses berjalan.</p>{/if}
                      </div>
                    {/if}
                  {/if}
                </div>
              {/each}
            </div>
          {/if}
          {#if profile.error}<p class="mt-2 text-sm text-rose-600">{profile.error}</p>{/if}
          {#if (profile.status === 'legacy' || (profile.source === 'adoption' && profile.status === 'failed')) && profile.adoptable !== false}
            {#if adopting === profile.name}
              <div class="mt-4 rounded-xl border border-amber-300/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20"><p>Sesi `root` dan `user1` dari worker terpilih akan disalin ke vault, lalu disebarkan ke semua worker. Periksa sumber sebelum memulai.</p><div class="mt-3 flex flex-wrap gap-2"><select class="field min-w-44 flex-1" bind:value={adoptWorker} onchange={() => adoptionCheck = null}><option value="">Worker sumber</option>{#each availableWorkers as item}<option value={item.name}>{item.name}</option>{/each}</select><button class="button secondary" onclick={() => diagnoseAdoption(profile.name)} disabled={checkingAdoption || saving || !adoptWorker}><RefreshCw size={15}/>{checkingAdoption ? 'Memeriksa...' : 'Periksa sumber'}</button>{#if adoptionCheck?.ready && adoptionCheck.profile === profile.name && adoptionCheck.worker === adoptWorker}<button class="button" onclick={() => adoptProfile(profile.name)} disabled={saving}>Adopsi dan sebarkan</button>{/if}<button class="button secondary" onclick={() => { adopting = ''; adoptionCheck = null; }}>Batal</button></div>
                {#if adoptionCheck?.profile === profile.name && adoptionCheck.worker === adoptWorker}<div class="mt-3 rounded-lg bg-[var(--panel)] p-3"><p class={adoptionCheck.ready ? 'text-emerald-600' : 'text-amber-600'}>{adoptionCheck.ready ? 'Sesi root dan user1 tersedia untuk diekspor.' : `Belum siap: ${adoptionCheck.reason_codes.join(', ')}`}</p>{#if adoptionCheck.checks.length}<ul class="muted mt-2 space-y-1 text-xs">{#each adoptionCheck.checks as check}<li>{check.ready ? '✓' : '✕'} {check.name}: {check.code || (check.ready ? 'ready' : 'not_ready')}</li>{/each}</ul>{/if}<a class="muted mt-2 inline-block text-xs underline" href={adoptionCheck.logs_url} target="_blank" rel="noreferrer">Buka log diagnosis JSON</a></div>{/if}
              </div>
            {:else}<button class="button secondary mt-3" onclick={() => { adopting = profile.name; adoptWorker = availableWorkers[0]?.name || ''; }} disabled={!availableWorkers.length}>Adopsi ke vault</button>{/if}
          {/if}
        </article>
      {:else}<p class="muted rounded-xl border border-dashed border-[var(--line)] p-5 text-center">{loading ? 'Memuat profil...' : 'Belum ada profil.'}</p>{/each}
    </div>
    {#if syncOperationsError}<p class="mt-4 rounded-xl border border-amber-300/50 bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-100">Status operasi sinkronisasi belum dapat dimuat: {syncOperationsError}</p>{/if}
    {#if syncOperations.length}
      <section class="mt-5 rounded-2xl border border-amber-300/50 bg-amber-50/50 p-4 dark:bg-amber-950/20">
        <div class="flex flex-wrap items-center justify-between gap-2"><div><h3 class="font-extrabold">Operasi sinkronisasi</h3><p class="muted mt-1 text-xs">Status diambil saat halaman dimuat atau tombol muat ulang ditekan.</p></div><span class="badge">{syncOperations.length} operasi</span></div>
        <div class="mt-3 space-y-2">
          {#each syncOperations as item (item.operation_id)}
            <article class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
              <div class="flex flex-wrap items-center justify-between gap-2"><div class="flex items-center gap-2"><b>{item.profile}</b><span class="muted">· {item.target?.worker || 'worker'}</span><span class="badge">{item.status}</span></div>{#if syncActiveStatuses.has(item.status) && item.status !== 'cancelling'}<button class="button secondary !px-3 !py-2" onclick={() => cancelProfileSync(item)} disabled={Boolean(syncActionPending[item.operation_id])}><X size={14}/>{syncActionPending[item.operation_id] ? 'Membatalkan...' : 'Batalkan sync'}</button>{:else if item.status === 'cancelling'}<span class="muted text-xs">Pembatalan diproses</span>{/if}</div>
              <p class="muted mt-2 text-xs">{syncOperationMessage(item)}</p>
              {#if item.target?.desired_revision}<p class="muted mt-1 text-[11px]">Revision tujuan: {item.target.desired_revision}</p>{/if}
            </article>
          {/each}
        </div>
      </section>
    {/if}
    <p class="muted mt-4 flex items-start gap-2 text-xs"><ShieldCheck size={15} class="mt-0.5 shrink-0 text-emerald-600"/>Sesi disimpan terenkripsi di backend. ZIP, kode, password, dan isi QR tidak ditampilkan di log.</p>
  </section>
</div>

<style>
  button.active { background: var(--brand-soft); color: var(--brand-strong); }
  .qr-screen { min-height: 12rem; white-space: pre; }
</style>
