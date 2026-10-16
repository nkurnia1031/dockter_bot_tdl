<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
import { api, post, remove } from '$lib/api';
import { session } from '$lib/session.svelte';
  import { profileDiagnosticLabel } from '$lib/tdl-lanes';
import { CircleAlert, KeyRound, Plus, RefreshCw, ShieldCheck, Trash2, Upload, UserRoundPlus, X } from '@lucide/svelte';

  type Worker = { name: string; enabled: boolean; selected?: boolean };
type ProvisioningWorker = { name: string; enabled: boolean; online: boolean; secure: boolean };
  type ProfileCheck = { name: string; ready: boolean; code: string };
  type UploadLane = { status: string; phase: string; progress: number; code: string; updated_at: string };
  type LocalProfile = { name: string; ready: boolean; deletable?: boolean; reason_codes: string[]; checks: ProfileCheck[]; upload_lane: UploadLane };
  type IdentityCleanup = { profile: string; status: string; deleted_worker: string; updated_at: string };
  type Inventory = { worker: string; checked_at: string; items: LocalProfile[]; pending_identity_cleanup?: IdentityCleanup[] };
  type ScanWorker = { name: string; status: 'success' | 'failed' | 'disabled'; checked_at: string; error_code: string };
  type LocalProfileCatalog = { checked_at: string; workers: ScanWorker[]; inventories: Inventory[] };
  type VaultProfile = { name: string; vault: boolean; status: string; source?: string; operation_id?: string; error?: string };
  type AdoptionOperation = { id: string; status: string; error?: string };
type ProvisioningOperation = {
  id: string;
  profile: string;
  status: string;
  source: string;
  bootstrap_worker?: string;
  error?: string;
  workers: { worker: string; status: string; error?: string }[];
  login?: { status: string; step?: string; qr_text?: string; error?: string };
};
  type DeleteOperation = {
    operation_id: string;
    kind: string;
    target: { profile?: string; worker?: string };
    status: string;
    phase: string;
    progress: Record<string, unknown>;
    error?: { code?: string; message?: string } | null;
    created_at: string;
  };

  let workers = $state<Worker[]>([]);
  let selectedWorker = $state('');
let provisioningWorkers = $state<ProvisioningWorker[]>([]);
let provisioningWorker = $state('');
let profileName = $state('');
let provisioningMode = $state<'upload' | 'login'>('upload');
let loginMethod = $state<'qr' | 'code'>('qr');
let loginPhone = $state('');
let loginInput = $state('');
let profileArchive = $state<File | null>(null);
let provisioningOperation = $state<ProvisioningOperation | null>(null);
let provisioningLoading = $state(false);
let provisioningFailure = $state('');
let provisioningNotice = $state('');
  let inventory = $state<Inventory | null>(null);
  let profileCatalog = $state<LocalProfileCatalog | null>(null);
  let catalogFailure = $state('');
  let vaultProfiles = $state<VaultProfile[]>([]);
  let vaultStatusLoaded = $state(false);
  let vaultStatusFailure = $state('');
  let adoptionOperations = $state<Record<string, AdoptionOperation>>({});
  let adoptingProfiles = $state<string[]>([]);
  let deleteOperations = $state<DeleteOperation[]>([]);
  let loadingWorkers = $state(false);
  let scanning = $state(false);
let savingProvisioning = $state(false);
  let failure = $state('');
  let notice = $state('');
  let progressTimer: ReturnType<typeof setTimeout> | undefined;
  let provisioningTimer: ReturnType<typeof setTimeout> | undefined;
  let provisioningRequestActive = false;
  let progressRequestActive = false;
  let progressGeneration = 0;
  let catalogGeneration = 0;

  const codeMessages: Record<string, string> = {
    PROFILE_IDENTITY_MISSING: 'File identitas tidak ditemukan.',
    PROFILE_IDENTITY_INVALID: 'Identitas profil tidak valid.',
    PROFILE_IDENTITY_UNSAFE: 'File identitas menggunakan path yang tidak aman.',
    PROFILE_ROOT_SESSION_MISSING: 'Sesi lane Download tidak ditemukan.',
    PROFILE_USER1_SESSION_MISSING: 'Sesi lane Export tidak ditemukan.',
    PROFILE_ROOT_SESSION_EMPTY: 'Data sesi lane Download kosong.',
    PROFILE_USER1_SESSION_EMPTY: 'Data sesi lane Export kosong.',
    PROFILE_SESSION_UNSAFE: 'Sesi berisi path yang tidak aman.',
    PROFILE_SESSION_UNREADABLE: 'Data sesi tidak dapat dibaca.',
    PROFILE_SESSION_BUSY: 'Sesi sedang dipakai job.',
    PROFILE_SESSION_UNAVAILABLE: 'Pemeriksaan sesi tidak tersedia.',
    PROFILE_EXPORT_SESSION_MISSING: 'Sesi Export tidak ditemukan.',
    PROFILE_EXPORT_SESSION_UNSAFE: 'Sesi Export memiliki file yang tidak aman.',
    PROFILE_EXPORT_SESSION_INVALID: 'TDL tidak dapat memakai sesi Export.',
    PROFILE_EXPORT_IDENTITY_MISMATCH: 'Identitas sesi Export tidak cocok dengan profil.',
    PROFILE_UPLOAD_LANE_UNSAFE: 'Folder lane Upload tidak aman.',
    PROFILE_UPLOAD_SESSION_INVALID: 'TDL tidak dapat memakai salinan sesi Upload.',
    PROFILE_UPLOAD_IDENTITY_MISMATCH: 'Identitas sesi Upload tidak cocok dengan profil.',
    PROFILE_DEFAULT_PROTECTED: 'Profil default tidak dapat dihapus.',
    PROFILE_ROOT_UNSAFE: 'Folder profil menggunakan path yang tidak aman; tidak ada data dihapus.',
    PROFILE_DELETE_FAILED: 'Penghapusan gagal. Periksa worker dan scan kembali sebelum mencoba lagi.',
    PROFILE_UPLOAD_PREPARATION_FAILED: 'Worker gagal menyiapkan lane Upload. Tekan Scan untuk mencoba lagi.',
    PROFILE_UPLOAD_PREPARATION_INTERRUPTED: 'Pemeriksaan lane Upload belum selesai. Tekan Scan untuk mencoba lagi.',
    WORKER_UNAVAILABLE: 'Worker offline atau tidak dapat dijangkau.',
    WORKER_TIMEOUT: 'Worker melewati batas waktu pemeriksaan.',
    WORKER_UPDATE_REQUIRED: 'Worker perlu diperbarui untuk membaca inventaris profil.',
    WORKER_SCAN_FAILED: 'Worker gagal membaca inventaris profil.'
  };

  const uploadPhaseLabels: Record<string, string> = {
    not_started: 'Belum diperiksa',
    queued: 'Dalam antrean',
    waiting_idle: 'Menunggu semua job TDL selesai',
    validating_source: 'Memeriksa sesi Export',
    copying: 'Menyalin sesi ke lane Upload',
    validating_upload: 'Memvalidasi sesi Upload',
    installing: 'Memasang lane Upload',
    ready: 'Siap',
    failed: 'Gagal'
  };

const availableProvisioningWorkers = $derived(
  provisioningWorkers.filter((worker) => worker.online && worker.secure)
);

const provisioningStatusLabels: Record<string, string> = {
  authenticating: 'Menunggu login TDL',
  validating: 'Memvalidasi sesi',
  distributing: 'Memasang sesi pada worker terpilih',
  active: 'Profil aktif',
  failed: 'Gagal',
  cancelled: 'Dibatalkan'
};

  function codeMessage(code: string) {
    return codeMessages[code] || code;
  }

  function checkedAt(value: string) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function workerScanLabel(worker: ScanWorker) {
    if (worker.status === 'success') {
      const count = profileCatalog?.inventories.find((item) => item.worker === worker.name)?.items.length || 0;
      return `Berhasil · ${count} profil`;
    }
    if (worker.status === 'disabled') return 'Nonaktif · tidak dipindai';
    return `Gagal · ${codeMessage(worker.error_code || 'WORKER_SCAN_FAILED')}`;
  }

  function normalizeProfileCatalog(value: unknown): LocalProfileCatalog {
    const payload = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    if (Array.isArray(payload.workers) && Array.isArray(payload.inventories)) {
      return {
        checked_at: String(payload.checked_at || ''),
        workers: payload.workers as ScanWorker[],
        inventories: payload.inventories as Inventory[]
      };
    }
    // Older worker snapshots are accepted while a mixed-version deployment rolls forward.
    if (typeof payload.worker === 'string' && Array.isArray(payload.items)) {
      const checked_at = String(payload.checked_at || '');
      const worker = payload.worker;
      return {
        checked_at,
        workers: [{ name: worker, status: 'success', checked_at, error_code: '' }],
        inventories: [{ worker, checked_at, items: payload.items as LocalProfile[] }]
      };
    }
    return { checked_at: '', workers: [], inventories: [] };
  }

  async function loadProfileCatalog() {
    const generation = catalogGeneration;
    catalogFailure = '';
    try {
      const result = normalizeProfileCatalog(await api<unknown>('/profiles/local'));
      if (generation !== catalogGeneration) return;
      profileCatalog = result;
      if (selectedWorker) {
        inventory = profileCatalog.inventories.find((item) => item.worker === selectedWorker) || null;
      }
    } catch (cause) {
      catalogFailure = cause instanceof Error ? cause.message : 'Katalog profil lokal gagal dimuat.';
    }
  }

function setProvisioningWorkers(items: ProvisioningWorker[]) {
  provisioningWorkers = Array.isArray(items) ? items : [];
  const available = provisioningWorkers.filter((worker) => worker.online && worker.secure);
  if (!available.some((worker) => worker.name === provisioningWorker)) {
    provisioningWorker = available[0]?.name || '';
  }
}

async function loadProvisioningWorkers() {
  provisioningLoading = true;
  provisioningFailure = '';
  try {
    const result = await api<{ workers?: ProvisioningWorker[] }>('/profiles/management');
    setProvisioningWorkers(result.workers || []);
  } catch (cause) {
    provisioningFailure = cause instanceof Error
      ? cause.message
      : 'Worker aman untuk menambah profil belum dapat dimuat.';
  } finally {
    provisioningLoading = false;
  }
}

function scheduleProvisioningRefresh(id: string) {
  if (provisioningTimer !== undefined) clearTimeout(provisioningTimer);
  provisioningTimer = undefined;
  if (!provisioningOperation || provisioningOperation.id !== id
    || ['active', 'failed', 'cancelled'].includes(provisioningOperation.status)) return;
  provisioningTimer = setTimeout(() => void refreshProvisioningOperation(id), 1500);
}

async function refreshProvisioningOperation(id: string) {
  if (provisioningRequestActive) return;
  provisioningRequestActive = true;
  try {
    const previousStatus = provisioningOperation?.status;
    const current = await api<ProvisioningOperation>(`/profiles/provisionings/${encodeURIComponent(id)}`);
    if (provisioningOperation?.id !== id) return;
    provisioningOperation = current;
    provisioningFailure = '';
    if (current.status === 'active' && previousStatus !== 'active') {
      provisioningNotice = `Profil ${current.profile} aktif pada worker terpilih; sesi tidak disimpan di Vault.`;
      session.restore();
      profileName = '';
      loginPhone = '';
      loginInput = '';
      profileArchive = null;
    }
  } catch (cause) {
    if (provisioningOperation?.id === id) {
      provisioningFailure = cause instanceof Error ? cause.message : 'Status penambahan profil gagal dimuat.';
    }
  } finally {
    provisioningRequestActive = false;
    scheduleProvisioningRefresh(id);
  }
}

async function submitProfileArchive() {
  if (!profileArchive || !profileName.trim() || !provisioningWorker || savingProvisioning) return;
  savingProvisioning = true;
  provisioningFailure = '';
  provisioningNotice = '';
  try {
    const query = new URLSearchParams({ name: profileName.trim(), worker: provisioningWorker, local_only: 'true' });
    const result = await api<{ id: string; status: string }>(`/profiles/provisionings/upload?${query}`, {
      method: 'POST',
      body: profileArchive,
      headers: { 'content-type': 'application/zip' }
    });
    provisioningOperation = {
      id: result.id,
      profile: profileName.trim(),
      status: result.status,
      source: 'upload',
      bootstrap_worker: provisioningWorker,
      workers: []
    };
    provisioningNotice = `Sesi valid. Pemasangan dimulai pada worker ${provisioningWorker}.`;
    await refreshProvisioningOperation(result.id);
  } catch (cause) {
    provisioningFailure = cause instanceof Error ? cause.message : 'Upload sesi gagal.';
  } finally {
    savingProvisioning = false;
  }
}

async function startProfileLogin() {
  if (!profileName.trim() || !provisioningWorker || savingProvisioning
    || (loginMethod === 'code' && !loginPhone.trim())) return;
  savingProvisioning = true;
  provisioningFailure = '';
  provisioningNotice = '';
  try {
    const result = await post<{ id: string; status: string }>('/profiles/provisionings/login', {
      name: profileName.trim(),
      worker: provisioningWorker,
      method: loginMethod,
      phone: loginMethod === 'code' ? loginPhone.trim() : '',
      local_only: true
    });
    provisioningOperation = {
      id: result.id,
      profile: profileName.trim(),
      status: result.status,
      source: 'login',
      bootstrap_worker: provisioningWorker,
      workers: []
    };
    provisioningNotice = loginMethod === 'qr'
      ? 'QR sedang disiapkan pada worker.'
      : 'Menunggu kode verifikasi Telegram.';
    await refreshProvisioningOperation(result.id);
  } catch (cause) {
    provisioningFailure = cause instanceof Error ? cause.message : 'Login TDL gagal dimulai.';
  } finally {
    savingProvisioning = false;
  }
}

async function submitLoginInput() {
  if (!provisioningOperation || !loginInput.trim() || savingProvisioning) return;
  const field = provisioningOperation.login?.step === 'password' ? 'password' : 'code';
  savingProvisioning = true;
  provisioningFailure = '';
  try {
    await post(`/profiles/provisionings/${encodeURIComponent(provisioningOperation.id)}/input`, {
      field,
      value: loginInput
    });
    loginInput = '';
    await refreshProvisioningOperation(provisioningOperation.id);
  } catch (cause) {
    provisioningFailure = cause instanceof Error ? cause.message : 'Input login gagal dikirim.';
  } finally {
    savingProvisioning = false;
  }
}

async function cancelProfileProvisioning() {
  if (!provisioningOperation || savingProvisioning) return;
  savingProvisioning = true;
  provisioningFailure = '';
  try {
    await remove(`/profiles/provisionings/${encodeURIComponent(provisioningOperation.id)}`);
    if (provisioningTimer !== undefined) clearTimeout(provisioningTimer);
    provisioningTimer = undefined;
    provisioningOperation = null;
    provisioningNotice = 'Penambahan profil dibatalkan.';
  } catch (cause) {
    provisioningFailure = cause instanceof Error ? cause.message : 'Penambahan profil tidak dapat dibatalkan.';
  } finally {
    savingProvisioning = false;
  }
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
      } else if (selectedWorker) {
        inventory = profileCatalog?.inventories.find((item) => item.worker === selectedWorker) || null;
      }
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Daftar worker gagal dimuat.';
    } finally {
      loadingWorkers = false;
    }
  }

  function selectWorker(value: string) {
    stopProgressRefresh();
    selectedWorker = value;
    inventory = profileCatalog?.inventories.find((item) => item.worker === value) || null;
    deleteOperations = [];
    vaultProfiles = [];
    vaultStatusLoaded = false;
    vaultStatusFailure = '';
    adoptionOperations = {};
    adoptingProfiles = [];
    failure = '';
    notice = '';
    if (value && inventory) {
      scheduleProgressRefresh();
      const generation = progressGeneration;
      void refreshDeleteOperations(value, generation);
      void refreshVaultProfiles(value, generation);
    }
  }

  function refreshWorkers() {
    stopProgressRefresh();
    failure = '';
    notice = 'Daftar worker diperbarui. Katalog tetap memakai hasil Scan terakhir; tekan Scan untuk memperbaruinya.';
    void loadWorkers();
  }

  async function scanProfiles() {
    if (scanning) return;
    stopProgressRefresh();
    catalogGeneration += 1;
    const generation = progressGeneration;
    scanning = true;
    failure = '';
    notice = '';
    try {
      const result = normalizeProfileCatalog(await post<unknown>('/profiles/local/scan'));
      if (generation !== progressGeneration) return;
      profileCatalog = result;
      inventory = selectedWorker
        ? profileCatalog.inventories.find((item) => item.worker === selectedWorker) || null
        : null;
      catalogFailure = '';
      const successful = profileCatalog.workers.filter((worker) => worker.status === 'success').length;
      const failed = profileCatalog.workers.filter((worker) => worker.status === 'failed').length;
      const disabled = profileCatalog.workers.filter((worker) => worker.status === 'disabled').length;
      notice = `Scan selesai: ${successful} worker berhasil, ${failed} gagal, ${disabled} nonaktif.`;
      if (selectedWorker && inventory) {
        await refreshDeleteOperations(selectedWorker, generation);
        await refreshVaultProfiles(selectedWorker, generation);
        scheduleProgressRefresh();
      }
    } catch (cause) {
      if (generation !== progressGeneration) return;
      const error = cause as { code?: string; message?: string };
      failure = error.message || 'Scan profil lokal semua worker gagal. Katalog sebelumnya dipertahankan.';
    } finally {
      scanning = false;
    }
  }

  function stopProgressRefresh() {
    progressGeneration += 1;
    if (progressTimer !== undefined) clearTimeout(progressTimer);
    progressTimer = undefined;
  }

  function scheduleProgressRefresh() {
    stopProgressRefresh();
    if (!inventory?.items.some((profile) => profile.upload_lane?.status === 'running')
      && !deleteOperations.some(isDeleteActive)
      && !Object.values(adoptionOperations).some(isAdoptionActive)) return;
    progressTimer = setTimeout(() => void refreshProgress(), 1500);
  }

  function isDeleteActive(operation: DeleteOperation) {
    return ['queued', 'running', 'waiting_worker', 'paused', 'cancelling'].includes(operation.status);
  }

  function isAdoptionActive(operation: AdoptionOperation) {
    return ['validating', 'distributing'].includes(operation.status);
  }

  function adoptionStatusLabel(status: string) {
    return ({
      validating: 'Memeriksa dan menyimpan bundle terenkripsi ke Vault',
      stored: 'Bundle tersimpan di Vault; belum didistribusikan',
      failed: 'Adopsi gagal',
      cancelled: 'Adopsi dibatalkan'
    } as Record<string, string>)[status] || status;
  }

  function isVaulted(profile: string) {
    return vaultProfiles.some((item) => item.name === profile && item.vault);
  }

  function adoptionIsActive(profile: string) {
    const operation = adoptionOperations[profile];
    return adoptingProfiles.includes(profile) || Boolean(operation && isAdoptionActive(operation));
  }

  async function refreshVaultProfiles(worker: string, generation = progressGeneration) {
    try {
    const result = await api<{ items: VaultProfile[]; workers?: ProvisioningWorker[] }>('/profiles/management');
      if (generation !== progressGeneration || selectedWorker !== worker) return;
      vaultProfiles = Array.isArray(result.items) ? result.items : [];
    if (Array.isArray(result.workers)) setProvisioningWorkers(result.workers);
      vaultStatusLoaded = true;
      vaultStatusFailure = '';
      const operations: Record<string, AdoptionOperation> = {};
      for (const item of vaultProfiles) {
        if (item.source === 'adoption' && item.operation_id && ['validating', 'distributing', 'stored', 'failed', 'cancelled'].includes(item.status)) {
          operations[item.name] = { id: item.operation_id, status: item.status, error: item.error };
        }
      }
      adoptionOperations = { ...adoptionOperations, ...operations };
    } catch (cause) {
      if (generation !== progressGeneration || selectedWorker !== worker) return;
      vaultStatusLoaded = false;
      vaultStatusFailure = cause instanceof Error ? cause.message : 'Status Vault belum dapat dimuat.';
    }
  }

  async function refreshAdoptionOperations() {
    const active = Object.entries(adoptionOperations).filter(([, operation]) => isAdoptionActive(operation));
    if (!active.length) return;
    const results = await Promise.allSettled(active.map(async ([profile, operation]) => {
      const current = await api<{ id: string; status: string; error?: string }>(`/profiles/provisionings/${encodeURIComponent(operation.id)}`);
      return { profile, id: current.id, status: current.status, error: current.error };
    }));
    const next = { ...adoptionOperations };
    for (const result of results) {
      if (result.status !== 'fulfilled') continue;
      const operation = result.value;
      next[operation.profile] = { id: operation.id, status: operation.status, error: operation.error };
      if (operation.status === 'stored') {
        vaultProfiles = [
          ...vaultProfiles.filter((item) => item.name !== operation.profile),
          { name: operation.profile, vault: true, status: 'stored', source: 'adoption', operation_id: operation.id }
        ];
        notice = `Profil ${operation.profile} tersimpan di Vault. Tidak ada worker lain yang diubah.`;
      }
    }
    adoptionOperations = next;
  }

  async function adoptProfile(profile: LocalProfile) {
    const worker = selectedWorker;
    if (!worker || !profile.ready || !vaultStatusLoaded || isVaulted(profile.name) || adoptionIsActive(profile.name)) return;
    if (typeof window !== 'undefined' && !window.confirm(`Adopsi profil "${profile.name}" dari worker "${worker}" ke Vault? Ini hanya menyimpan bundle terenkripsi; sesi worker lain tidak akan diubah.`)) return;
    adoptingProfiles = [...adoptingProfiles, profile.name];
    failure = '';
    notice = '';
    try {
      const operation = await post<{ id: string; status: string }>(
        `/profiles/${encodeURIComponent(profile.name)}/adopt`, { worker }
      );
      adoptionOperations = { ...adoptionOperations, [profile.name]: { id: operation.id, status: operation.status } };
      notice = `Adopsi ${profile.name} dimulai dari worker ${worker}. Bundle hanya disimpan di Vault.`;
      await refreshAdoptionOperations();
      scheduleProgressRefresh();
    } catch (cause) {
      const error = cause as { code?: string; message?: string };
      failure = error.message || `Adopsi profil ${profile.name} gagal.`;
      if (error.code === 'PROFILE_ALREADY_VAULTED') await refreshVaultProfiles(worker);
    } finally {
      adoptingProfiles = adoptingProfiles.filter((name) => name !== profile.name);
    }
  }

  function deletionIsActive(profile: string) {
    return deleteOperations.some((operation) => operation.target.worker === selectedWorker
      && operation.target.profile === profile && isDeleteActive(operation));
  }

  async function refreshDeleteOperations(worker: string, generation = progressGeneration) {
    try {
      const result = await api<{ items: DeleteOperation[] }>('/operations?limit=100');
      if (generation !== progressGeneration || selectedWorker !== worker) return;
      const previous = deleteOperations;
      deleteOperations = (Array.isArray(result.items) ? result.items : [])
        .filter((operation) => operation.kind === 'profile.local_delete' && operation.target.worker === worker)
        .sort((left, right) => right.created_at.localeCompare(left.created_at))
        .slice(0, 10);
      const completed = deleteOperations.filter((operation) => operation.status === 'succeeded'
        && previous.some((before) => before.operation_id === operation.operation_id && isDeleteActive(before)));
      for (const operation of completed) {
        const profile = String(operation.target.profile || '');
        if (inventory && inventory.worker === worker && profile) {
          inventory = { ...inventory, items: inventory.items.filter((item) => item.name !== profile) };
        }
      }
    } catch {
      // Inventory remains useful even if operation history is temporarily unavailable.
    }
  }

  function deleteStatusLabel(status: string) {
    return ({
      queued: 'Menunggu diproses',
      running: 'Sedang menghapus',
      waiting_worker: 'Menunggu worker online',
      succeeded: 'Berhasil',
      failed: 'Gagal',
      cancelled: 'Dibatalkan'
    } as Record<string, string>)[status] || status;
  }

  function identityCleanupLabel(status: unknown) {
    return ({
      removed: 'Mapping identitas dihapus setelah semua worker terverifikasi.',
      local_copy_remaining: 'Mapping identitas dipertahankan karena masih ada salinan di worker lain.',
      pending_recheck: 'Mapping identitas dipertahankan; inventaris worker lain menunggu pemeriksaan ulang.'
    } as Record<string, string>)[String(status || '')] || '';
  }

  function newIdempotencyKey() {
    return globalThis.crypto?.randomUUID?.()
      || `profile-delete-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  async function deleteProfile(profile: LocalProfile) {
    const worker = selectedWorker;
    if (!worker || !profile.deletable || deletionIsActive(profile.name)) return;
    if (typeof window !== 'undefined' && !window.confirm(`Hapus seluruh data profil "${profile.name}" dari worker "${worker}"? Bundle Vault tidak ikut dihapus.`)) return;
    failure = '';
    notice = '';
    try {
      const operation = await api<DeleteOperation>(
        `/workers/${encodeURIComponent(worker)}/profiles/local/${encodeURIComponent(profile.name)}`,
        { method: 'DELETE', headers: { 'Idempotency-Key': newIdempotencyKey() } }
      );
      deleteOperations = [operation, ...deleteOperations.filter((item) => item.operation_id !== operation.operation_id)];
      notice = `Penghapusan profil ${profile.name} pada worker ${worker} tercatat dan dapat dipantau setelah halaman dibuka ulang.`;
      scheduleProgressRefresh();
    } catch (cause) {
      const error = cause as { code?: string; message?: string };
      if (
        error.code === 'PROFILE_NOT_IN_LOCAL_SCAN'
        && selectedWorker === worker
        && inventory?.worker === worker
      ) {
        inventory = { ...inventory, items: inventory.items.filter((item) => item.name !== profile.name) };
        notice = `Profil ${profile.name} tidak ditemukan pada scan terbaru worker ${worker}; entri dihapus dari daftar lokal. Tidak ada file yang dihapus.`;
        return;
      }
      failure = cause instanceof Error ? cause.message : `Penghapusan profil ${profile.name} gagal.`;
    }
  }

  async function refreshProgress() {
    if (!selectedWorker || !inventory || scanning) return;
    if (progressRequestActive) {
      progressTimer = setTimeout(() => void refreshProgress(), 250);
      return;
    }
    const worker = selectedWorker;
    const generation = progressGeneration;
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      progressTimer = setTimeout(() => void refreshProgress(), 4000);
      return;
    }
    const refreshLocalInventory = inventory.items.some((profile) => profile.upload_lane?.status === 'running')
      || deleteOperations.some(isDeleteActive);
    progressRequestActive = true;
    try {
      if (refreshLocalInventory) {
        const result = await api<Inventory>(`/workers/${encodeURIComponent(worker)}/profiles/local`);
        if (generation !== progressGeneration || selectedWorker !== worker) return;
        inventory = result;
        await refreshDeleteOperations(worker, generation);
      }
      await refreshAdoptionOperations();
      if (generation !== progressGeneration || selectedWorker !== worker) return;
      failure = '';
      scheduleProgressRefresh();
    } catch (cause) {
      if (generation !== progressGeneration || selectedWorker !== worker) return;
      failure = cause instanceof Error
        ? `${cause.message} Status lane Upload berhenti diperbarui; tekan Scan untuk mencoba lagi.`
        : 'Status lane Upload tidak dapat dimuat. Tekan Scan untuk mencoba lagi.';
      stopProgressRefresh();
    } finally {
      progressRequestActive = false;
    }
  }

  onMount(() => {
    void loadWorkers();
    void loadProfileCatalog();
  void loadProvisioningWorkers();
  });

  onDestroy(() => {
    stopProgressRefresh();
    if (provisioningTimer !== undefined) clearTimeout(provisioningTimer);
  });
</script>

<svelte:head><title>Profil lokal · tme3</title></svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">SESI WORKER</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Profil lokal</h1>
    <p class="muted mt-2">Scan memeriksa semua worker aktif. Pilih worker setelahnya untuk melihat profil TDL lokal dan aksi khusus worker.</p>
  </div>
  <div class="flex items-center gap-2"><a class="button secondary" href="/profiles/vault/"><KeyRound size={16}/>Kelola Vault</a><div class="page-icon"><UserRoundPlus size={23}/></div></div>
</header>

{#if failure}
  <div class="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100" role="alert">
    <CircleAlert size={17} class="mt-0.5 shrink-0"/>{failure}
  </div>
{/if}

<section class="card mt-7 p-5 sm:p-6" aria-labelledby="profile-create-title">
  <div class="flex items-center gap-3">
    <div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={19}/></div>
    <div>
      <h2 id="profile-create-title" class="font-extrabold">Tambah profil local</h2>
      <p class="muted text-sm">Upload sesi atau login TDL. Sesi hanya dipasang pada worker yang dipilih dan tidak disimpan di Vault.</p>
    </div>
  </div>

  <div class="mt-5 grid gap-4 lg:grid-cols-2">
    <label class="block text-sm font-bold">
      Nama profil
      <input class="field mt-2" bind:value={profileName} maxlength="48" autocomplete="off" placeholder="contoh: irang"/>
    </label>
    <label class="block text-sm font-bold">
      Worker untuk menyiapkan sesi
      <select class="field mt-2" aria-label="Worker untuk menyiapkan sesi" bind:value={provisioningWorker} disabled={provisioningLoading || savingProvisioning}>
        <option value="">Pilih worker online</option>
        {#each availableProvisioningWorkers as worker (worker.name)}
          <option value={worker.name}>{worker.name}{worker.enabled ? '' : ' · nonaktif untuk job baru'}</option>
        {/each}
      </select>
    </label>
  </div>

  {#if availableProvisioningWorkers.length === 0}
    <p class="muted mt-3 rounded-xl border border-amber-300/40 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
      {provisioningLoading
        ? 'Memeriksa worker yang online dan aman...'
        : 'Tidak ada worker online dengan transport aman. Worker remote perlu URL HTTPS.'}
      <button class="button secondary ml-2 !px-3 !py-2" onclick={loadProvisioningWorkers} disabled={provisioningLoading}>Muat ulang</button>
    </p>
  {/if}

  <div class="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-[var(--panel-strong)] p-1">
    <button class:active={provisioningMode === 'upload'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => provisioningMode = 'upload'}><Upload size={15} class="mr-1 inline"/>Upload ZIP</button>
    <button class:active={provisioningMode === 'login'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => provisioningMode = 'login'}><KeyRound size={15} class="mr-1 inline"/>Login TDL</button>
  </div>

  {#if provisioningMode === 'upload'}
    <div class="mt-4 space-y-3">
      <label class="block text-sm font-bold">
        ZIP berisi folder <code>.tdl/</code>
        <input class="field mt-2" type="file" accept=".zip,application/zip" onchange={(event) => profileArchive = (event.currentTarget as HTMLInputElement).files?.[0] || null}/>
      </label>
      <p class="muted text-xs">Maksimum 128 MiB. Sesi dipasang terpisah pada lane Download dan Export di worker terpilih.</p>
      <button class="button w-full sm:w-auto" onclick={submitProfileArchive} disabled={savingProvisioning || !profileArchive || !profileName.trim() || !provisioningWorker}>
        <Upload size={16}/>{savingProvisioning ? 'Memvalidasi...' : 'Validasi dan simpan lokal'}
      </button>
    </div>
  {:else}
    <div class="mt-4 space-y-3">
      <div class="grid grid-cols-2 gap-2">
        <button class:active={loginMethod === 'qr'} class="button secondary justify-center" onclick={() => loginMethod = 'qr'}>QR</button>
        <button class:active={loginMethod === 'code'} class="button secondary justify-center" onclick={() => loginMethod = 'code'}>Nomor dan kode</button>
      </div>
      {#if loginMethod === 'code'}
        <label class="block text-sm font-bold">Nomor telepon Telegram<input class="field mt-2" bind:value={loginPhone} type="tel" autocomplete="tel" placeholder="+62..."/></label>
      {/if}
      <button class="button w-full sm:w-auto" onclick={startProfileLogin} disabled={savingProvisioning || !profileName.trim() || !provisioningWorker || (loginMethod === 'code' && !loginPhone.trim())}>
        <KeyRound size={16}/>{savingProvisioning ? 'Menyiapkan...' : 'Mulai login TDL'}
      </button>
    </div>
  {/if}

  {#if provisioningNotice}<p class="mt-3 text-sm text-violet-700 dark:text-violet-200" role="status">{provisioningNotice}</p>{/if}
  {#if provisioningFailure}<p class="mt-3 text-sm text-rose-600" role="alert">{provisioningFailure}</p>{/if}

  {#if provisioningOperation}
    <article class="mt-5 rounded-2xl border border-violet-300/50 bg-violet-50/50 p-4 dark:bg-violet-950/20" aria-label={`Penambahan profil ${provisioningOperation.profile}`}>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-xs font-bold uppercase tracking-wider text-violet-600">Profil {provisioningOperation.profile}{#if provisioningOperation.bootstrap_worker} · {provisioningOperation.bootstrap_worker}{/if}</p>
          <p class="mt-1 font-bold">{provisioningStatusLabels[provisioningOperation.status] || provisioningOperation.status}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <a class="button secondary !px-3 !py-2" href={`/api/v1/profiles/provisionings/${encodeURIComponent(provisioningOperation.id)}/logs?limit=500`} target="_blank" rel="noreferrer">Log JSON</a>
          <button class="button secondary !px-3 !py-2" onclick={() => refreshProvisioningOperation(provisioningOperation!.id)} disabled={savingProvisioning} aria-label="Perbarui status penambahan profil"><RefreshCw size={15}/>Perbarui status</button>
          {#if provisioningOperation.status !== 'active' && provisioningOperation.status !== 'cancelled'}
            <button class="button secondary !px-3 !py-2" onclick={cancelProfileProvisioning} disabled={savingProvisioning}><X size={15}/>Batalkan</button>
          {/if}
        </div>
      </div>
      {#if provisioningOperation.login && provisioningOperation.status === 'authenticating'}
        <div class="mt-4 space-y-3">
          {#if provisioningOperation.login.step === 'qr'}
            <p class="muted text-sm">Pindai QR dengan Telegram pada perangkat yang ingin ditambahkan.</p>
            <pre class="qr-screen overflow-x-auto rounded-xl bg-slate-950 p-4 text-center font-mono text-[9px] leading-[.85] text-white">{provisioningOperation.login.qr_text || 'Menunggu QR dari worker...'}</pre>
          {:else if provisioningOperation.login.step === 'code' || provisioningOperation.login.step === 'password'}
            <label class="block text-sm font-bold">
              {provisioningOperation.login.step === 'password' ? 'Password 2FA' : 'Kode Telegram'}
              <input class="field mt-2" bind:value={loginInput} type={provisioningOperation.login.step === 'password' ? 'password' : 'text'} autocomplete="one-time-code"/>
            </label>
            <button class="button" onclick={submitLoginInput} disabled={savingProvisioning || !loginInput.trim()}>
              {provisioningOperation.login.step === 'password' ? 'Kirim password 2FA' : 'Kirim kode'}
            </button>
          {:else}
            <p class="muted text-sm">Menunggu prompt login dari worker...</p>
          {/if}
          {#if provisioningOperation.login.error}<p class="text-sm text-rose-600">{provisioningOperation.login.error}</p>{/if}
        </div>
      {/if}
      {#if provisioningOperation.status === 'validating'}<p class="muted mt-3 text-sm">Worker sedang memvalidasi sesi. Perbarui status untuk melihat hasilnya.</p>{/if}
      {#if provisioningOperation.error}<p class="mt-3 text-sm text-rose-600">{provisioningOperation.error}</p>{/if}
      {#if provisioningOperation.workers.length}
        <div class="mt-3 grid gap-2 sm:grid-cols-2">
          {#each provisioningOperation.workers as worker (worker.worker)}
            <p class="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-2 text-sm">{worker.worker} · {worker.status}{#if worker.error}: {worker.error}{/if}</p>
          {/each}
        </div>
      {/if}
    </article>
  {/if}
</section>

<section class="card mt-7 p-5 sm:p-6" aria-labelledby="local-profiles-target">
  <div class="flex flex-wrap items-end gap-3">
    <label id="local-profiles-target" class="min-w-56 flex-1 text-sm font-bold">
      Worker untuk rincian dan aksi
      <select
        class="field mt-2"
        aria-label="Worker"
        value={selectedWorker}
        onchange={(event) => selectWorker(event.currentTarget.value)}
        disabled={loadingWorkers || scanning}
      >
      <option value="">Pilih worker untuk rincian</option>
        {#each workers as worker (worker.name)}
          <option value={worker.name}>{worker.name}{worker.enabled ? '' : ' · nonaktif untuk job baru'}</option>
        {/each}
      </select>
    </label>
    <button class="button secondary" onclick={refreshWorkers} disabled={loadingWorkers || scanning} aria-label="Muat ulang worker">
      <RefreshCw size={16}/>{loadingWorkers ? 'Memuat...' : 'Muat ulang worker'}
    </button>
    <button class="button" onclick={scanProfiles} disabled={scanning || loadingWorkers}>
      <RefreshCw size={16}/>{scanning ? 'Memindai semua worker...' : 'Scan semua worker'}
    </button>
  </div>
  <p class="muted mt-3 flex items-start gap-2 text-xs">
    <ShieldCheck size={15} class="mt-0.5 shrink-0"/>
    Scan membaca inventaris profil pada semua worker aktif tanpa memilih worker terlebih dahulu atau memulai penyiapan lane Upload. Katalog berubah hanya saat Scan dijalankan; pilih worker setelahnya untuk melihat rincian dan aksi.
  </p>
  {#if catalogFailure}
    <p class="mt-3 text-sm text-rose-600" role="alert">{catalogFailure}</p>
  {/if}
  {#if profileCatalog?.checked_at}
    <section class="mt-4 rounded-xl border border-[var(--line)] p-3" aria-label="Status scan semua worker">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-extrabold">Status scan terakhir</h2>
        <span class="muted text-xs">{checkedAt(profileCatalog.checked_at)}</span>
      </div>
      <div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each profileCatalog.workers as worker (worker.name)}
          <div class="flex items-center justify-between gap-2 rounded-lg bg-[var(--panel)] px-3 py-2 text-sm" aria-label={`Status scan ${worker.name}`}>
            <span class="font-bold">{worker.name}</span>
            <span class={worker.status === 'success' ? 'font-bold text-emerald-600' : worker.status === 'failed' ? 'font-bold text-rose-600' : 'muted font-bold'}>{workerScanLabel(worker)}</span>
          </div>
        {/each}
      </div>
    </section>
  {:else}
    <p class="muted mt-3 text-xs" role="status">Belum ada katalog hasil scan tersimpan.</p>
  {/if}
  {#if notice}
    <p class="mt-3 text-sm text-violet-700 dark:text-violet-200" role="status">{notice}</p>
  {/if}
  {#if vaultStatusFailure}
    <p class="muted mt-3 text-xs" role="status">Status Vault gagal dimuat; tombol adopsi disembunyikan agar profil yang sudah tersimpan tidak dikirim ulang.</p>
  {/if}
  {#if inventory?.pending_identity_cleanup?.length}
    <div class="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100" role="status">
      {#each inventory.pending_identity_cleanup as item (item.profile)}
        <p>Mapping identitas profil {item.profile} menunggu pemeriksaan ulang semua worker setelah penghapusan pada {item.deleted_worker}.</p>
      {/each}
    </div>
  {/if}
</section>

{#if selectedWorker && deleteOperations.length}
  <section class="card mt-5 p-5 sm:p-6" aria-label="Operasi penghapusan profil">
    <h2 class="font-extrabold">Operasi penghapusan · {selectedWorker}</h2>
    <div class="mt-3 grid gap-2">
      {#each deleteOperations as operation (operation.operation_id)}
        {@const mappingMessage = identityCleanupLabel(operation.progress?.identity_mapping_status)}
        <article class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3" aria-label={`Penghapusan ${operation.target.profile || 'profil'}`}>
          <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span class="font-bold">{operation.target.profile}</span>
            <span class={operation.status === 'failed' ? 'font-bold text-rose-600' : operation.status === 'succeeded' ? 'font-bold text-emerald-600' : 'muted font-bold'}>{deleteStatusLabel(operation.status)}</span>
          </div>
          {#if operation.status === 'failed'}
            <p class="mt-1 text-xs text-rose-600">{codeMessage(String(operation.progress?.reason_code || operation.error?.code || 'PROFILE_DELETE_FAILED'))}</p>
          {/if}
          {#if mappingMessage}
            <p class="muted mt-1 text-xs">{mappingMessage}</p>
          {/if}
        </article>
      {/each}
    </div>
  </section>
{/if}

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
              <div class="flex items-center gap-2">
                <span class={profile.ready ? 'text-sm font-bold text-emerald-600' : 'text-sm font-bold text-rose-600'}>
                  {profile.ready ? 'Sesi tersedia' : 'Perlu diperiksa'}
                </span>
                {#if profile.ready && vaultStatusLoaded}
                  {#if isVaulted(profile.name)}
                    <span class="badge">Sudah di Vault</span>
                  {:else}
                    <button class="button secondary" onclick={() => adoptProfile(profile)} disabled={adoptionIsActive(profile.name)} aria-label={`Adopsi profil ${profile.name} dari ${selectedWorker} ke Vault`}>
                      <KeyRound size={15}/>{adoptionIsActive(profile.name) ? 'Menyimpan...' : 'Adopsi ke Vault'}
                    </button>
                  {/if}
                {/if}
                {#if profile.deletable}
                  <button class="button secondary" onclick={() => deleteProfile(profile)} disabled={deletionIsActive(profile.name)} aria-label={`Hapus profil ${profile.name} dari ${selectedWorker}`}>
                    <Trash2 size={15}/>{deletionIsActive(profile.name) ? 'Menghapus...' : 'Hapus profil'}
                  </button>
                {/if}
              </div>
            </div>
            <div class="mt-3 grid gap-2 sm:grid-cols-3">
              {#each profile.checks as check (check.name)}
                <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3">
                  <p class="text-sm font-bold">{profileDiagnosticLabel(check.name)} · {check.ready ? 'Siap' : 'Gagal'}</p>
                  {#if !check.ready}<p class="muted mt-1 text-xs">{codeMessage(check.code)}</p>{/if}
                </div>
              {/each}
            </div>
            {#if profile.reason_codes.length}
              <p class="mt-3 text-xs text-rose-600">Kode: {profile.reason_codes.join(', ')}</p>
            {/if}
            {#if adoptionOperations[profile.name]}
              <p class="mt-3 text-xs" role="status">{adoptionStatusLabel(adoptionOperations[profile.name].status)}{#if adoptionOperations[profile.name].error}: {adoptionOperations[profile.name].error}{/if}</p>
            {/if}
            <section class="mt-4 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3" aria-label={`Lane Upload ${profile.name}`}>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="text-sm font-bold">Lane Upload</p>
                <span class={profile.upload_lane?.status === 'ready' ? 'text-sm font-bold text-emerald-600' : profile.upload_lane?.status === 'failed' ? 'text-sm font-bold text-rose-600' : 'muted text-sm font-bold'}>
                  {profile.upload_lane?.status === 'ready' ? 'Siap' : profile.upload_lane?.status === 'failed' ? 'Gagal' : profile.upload_lane?.status === 'running' ? `${profile.upload_lane.progress}%` : 'Menunggu scan'}
                </span>
              </div>
              {#if profile.upload_lane?.status === 'running'}
                <progress class="mt-2 h-2 w-full accent-violet-500" max="100" value={profile.upload_lane.progress} aria-label={`Progress lane Upload ${profile.name}`}></progress>
                <p class="muted mt-1 text-xs">{uploadPhaseLabels[profile.upload_lane.phase] || profile.upload_lane.phase}</p>
              {:else if profile.upload_lane?.status === 'failed'}
                <p class="mt-1 text-xs text-rose-600">{codeMessage(profile.upload_lane.code)}</p>
              {:else if profile.upload_lane?.status === 'pending'}
                <p class="muted mt-1 text-xs">{codeMessage(profile.upload_lane.code)}</p>
              {:else if profile.upload_lane?.status === 'ready'}
                <p class="muted mt-1 text-xs">Sesi Upload terpisah sudah tervalidasi dan cocok dengan identitas profil.</p>
              {/if}
            </section>
          </article>
        {/each}
      </div>
    {/if}
  </section>
{:else}
  <section class="card muted mt-5 p-6 text-center" aria-live="polite">
    {#if scanning}
      Memindai profil lokal pada semua worker aktif...
    {:else if profileCatalog?.checked_at && selectedWorker}
      {#if profileCatalog.workers.find((worker) => worker.name === selectedWorker)?.status === 'failed'}
        Worker {selectedWorker} gagal dipindai. Worker ini dikeluarkan dari katalog hasil; worker sukses tetap tersedia.
      {:else}
        Tidak ada inventaris sukses untuk worker {selectedWorker} pada Scan terakhir.
      {/if}
    {:else if profileCatalog?.checked_at}
      Pilih worker untuk melihat rincian profil dari Scan terakhir.
    {:else if selectedWorker}
      Tekan Scan semua worker untuk memeriksa profil lokal.
    {:else}
      Tekan Scan semua worker untuk memeriksa profil lokal tanpa memilih worker terlebih dahulu.
    {/if}
  </section>
{/if}
