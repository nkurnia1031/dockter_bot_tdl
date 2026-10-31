<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
import { api, post, remove } from '$lib/api';
import { session } from '$lib/session.svelte';
import { normalizeRuntimeReadiness, runtimeReadinessFor, runtimeReadinessForWorker, type RuntimeReadinessAttempt, type RuntimeReadinessSnapshot } from '$lib/profile-catalog';
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
  type LocalProfileCatalog = { checked_at: string; workers: ScanWorker[]; inventories: Inventory[]; runtime_readiness: RuntimeReadinessSnapshot };
  type ScanProfileProgress = {
    name: string;
    status: string;
    phase: string;
    error_code: string;
    checks?: Record<string, { ready: boolean; reason_code: string }>;
    cleanup?: { status: 'not_needed'|'succeeded'|'failed'; items: Array<{ target: string; message_id: number; status: string; error_code: string }> };
  };
  type ScanWorkerProgress = { name: string; status: string; phase: string; error_code: string; profiles: ScanProfileProgress[]; runtime?: string; checks?: Record<string, { ready: boolean; reason_code: string }> };
  type ProfileScanOperation = {
    id: string;
    status: string;
    target?: { kind: 'worker_runtime' | 'profile_runtime'; worker: string; profile?: string; runtime: string };
    progress: { workers: ScanWorkerProgress[]; total_workers: number; completed_workers: number; total_profiles: number; completed_profiles: number };
    error_code: string;
    created_at: string;
    updated_at: string;
    finished_at: string;
  };
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
  type RuntimeLogDialog = { worker: string; profile?: string; runtime: string; attempt?: RuntimeReadinessAttempt };

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
  let scanOperation = $state<ProfileScanOperation | null>(null);
  let runtimeLogDialog = $state<RuntimeLogDialog | null>(null);
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
  let scanPollTimer: ReturnType<typeof setTimeout> | undefined;
  let provisioningTimer: ReturnType<typeof setTimeout> | undefined;
  let provisioningRequestActive = false;
  let progressRequestActive = false;
  let scanPollRequestActive = false;
  let handledScanOperationId = '';
  let progressGeneration = 0;
  let catalogGeneration = 0;
  let onJobFinished: (() => void) | undefined;
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
    PROFILE_SESSION_CHANGED: 'Sesi berubah sejak scan terakhir.',
    PROFILE_SESSION_MISSING: 'Sesi profil sudah dihapus dari worker.',
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
    RESOLVER_RUNTIME_UNAVAILABLE: 'Addon Resolver tidak dapat digunakan pada worker.',
    RESOLVER_FINGERPRINT_MISSING: 'Bukti kesiapan Resolver tidak lengkap.',
    RCLONE_ACCESS_FAILED: 'Worker tidak dapat mengakses root rclone. Periksa izin dan koneksi remote.',
    RCLONE_FINGERPRINT_MISSING: 'Bukti akses root rclone tidak lengkap.',
    RCLONE_DESTINATION_CHANGED: 'Root rclone berubah sejak Scan Profil terakhir.',
    UTILITY_COMMAND_MISSING: 'Perintah pendukung Utility tidak tersedia pada worker.',
    UTILITY_SCRIPT_MISSING: 'Script Utility tidak ditemukan pada worker.',
    UTILITY_SCRIPT_UNREADABLE: 'Script Utility tidak dapat dibaca pada worker.',
    UTILITY_WORKSPACE_UNAVAILABLE: 'Workspace Utility tidak tersedia atau tidak dapat ditulis.',
    UTILITY_RUNTIME_UNAVAILABLE: 'Runtime Utility tidak tersedia pada worker.',
    UTILITY_FINGERPRINT_MISSING: 'Fingerprint runtime Utility tidak tersedia.',
    TTS_CHAT_UNAVAILABLE: 'Chat tujuan TTS belum dikonfigurasi.',
    TTS_HELPER_UNAVAILABLE: 'Helper TTS atau jalur Tor belum siap.',
    TTS_RUNTIME_UNAVAILABLE: 'Runtime helper TTS tidak tersedia.',
    TTS_FINGERPRINT_MISSING: 'Fingerprint kesiapan TTS tidak tersedia.',
    TDL_ACCESS_TARGET_UNAVAILABLE: 'Tujuan Storage belum dikonfigurasi.',
    STORAGE_EVIDENCE_INCOMPLETE: 'Bukti lane Upload atau akses Storage belum lengkap.',
    STORAGE_FINGERPRINT_MISSING: 'Fingerprint kesiapan Storage tidak tersedia.',
    PROFILE_UPLOAD_SESSION_CHANGED: 'Sesi Upload berubah sejak Scan Profil terakhir.',
    QUICK_MODE_RUNTIME_UNAVAILABLE: 'Runtime Quick Mode belum siap pada worker.',
    QUICK_MODE_FINGERPRINT_MISSING: 'Fingerprint runtime Quick Mode tidak tersedia.',
    QUICK_MODE_EVIDENCE_INCOMPLETE: 'Snapshot Upload Quick Mode belum lengkap.',
    RCLONE_RUNTIME_UNAVAILABLE: 'Remote atau konfigurasi rclone belum siap.',
    TDL_ACCESS_NOT_VERIFIED: 'Bukti akses kirim tidak ada atau sudah stale. Jalankan Scan Profil untuk memperbarui status.',
    TDL_SESSION_UNAUTHORIZED: 'Sesi TDL tidak terotorisasi untuk mengirim.',
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

  const exportReadinessLabels = {
    ready: 'Siap',
    not_ready: 'Tidak siap',
    offline: 'Worker offline',
    disabled: 'Worker nonaktif',
    unscanned: 'Belum dipindai'
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

  function normalizeScanOperation(value: unknown): ProfileScanOperation | null {
    if (!value || typeof value !== 'object') return null;
    const payload = value as Record<string, unknown>;
    if (typeof payload.id !== 'string' || !['queued', 'running', 'succeeded', 'failed'].includes(String(payload.status))) return null;
    const rawProgress = payload.progress && typeof payload.progress === 'object'
      ? payload.progress as Record<string, unknown>
      : {};
    const workers = Array.isArray(rawProgress.workers) ? rawProgress.workers.flatMap((rawWorker) => {
      if (!rawWorker || typeof rawWorker !== 'object') return [];
      const worker = rawWorker as Record<string, unknown>;
      const checks = worker.checks && typeof worker.checks === 'object'
        ? Object.fromEntries(Object.entries(worker.checks as Record<string, unknown>).flatMap(([runtime, rawCheck]) => {
          if (!rawCheck || typeof rawCheck !== 'object') return [];
          const check = rawCheck as Record<string, unknown>;
          return [[runtime, { ready: check.ready === true, reason_code: String(check.reason_code || '') }]];
        })) as Record<string, { ready: boolean; reason_code: string }>
        : undefined;
      const profiles = Array.isArray(worker.profiles) ? worker.profiles.flatMap((rawProfile) => {
        if (!rawProfile || typeof rawProfile !== 'object') return [];
        const profile = rawProfile as Record<string, unknown>;
        if (typeof profile.name !== 'string') return [];
        return [{
          name: profile.name,
          status: String(profile.status || 'queued'),
          phase: String(profile.phase || ''),
          error_code: String(profile.error_code || '')
        }];
      }) : [];
      if (typeof worker.name !== 'string') return [];
      return [{
        name: worker.name,
        status: String(worker.status || 'queued'),
        phase: String(worker.phase || ''),
        error_code: String(worker.error_code || ''),
        profiles,
        runtime: String(worker.runtime || ''),
        checks
      }];
    }) : [];
    const count = (value: unknown) => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    const rawTarget = payload.target && typeof payload.target === 'object'
      ? payload.target as Record<string, unknown>
      : null;
    const targetWorker = String(rawTarget?.worker || '').trim().toLowerCase();
    const targetRuntime = String(rawTarget?.runtime || '').trim().toLowerCase();
    const targetProfile = String(rawTarget?.profile || '').trim().toLowerCase();
    const target = rawTarget?.kind === 'worker_runtime' && targetWorker && targetRuntime
      ? { kind: 'worker_runtime' as const, worker: targetWorker, runtime: targetRuntime }
      : rawTarget?.kind === 'profile_runtime' && targetWorker && targetProfile && targetRuntime
        ? { kind: 'profile_runtime' as const, worker: targetWorker, profile: targetProfile, runtime: targetRuntime }
        : undefined;
    return {
      id: payload.id,
      status: String(payload.status),
      target,
      progress: {
        workers,
        total_workers: count(rawProgress.total_workers),
        completed_workers: count(rawProgress.completed_workers),
        total_profiles: count(rawProgress.total_profiles),
        completed_profiles: count(rawProgress.completed_profiles)
      },
      error_code: String(payload.error_code || ''),
      created_at: String(payload.created_at || ''),
      updated_at: String(payload.updated_at || ''),
      finished_at: String(payload.finished_at || '')
    };
  }

  function scanOperationIsActive(operation: ProfileScanOperation | null) {
    return operation !== null && ['queued', 'running'].includes(operation.status);
  }

  function scanOperationStatusLabel(status: string) {
    return ({
      queued: 'Dalam antrean',
      running: 'Berjalan',
      succeeded: 'Scan selesai',
      failed: 'Scan gagal'
    } as Record<string, string>)[status] || 'Status tidak diketahui';
  }

  function progressStatusLabel(status: string) {
    return ({
      queued: 'Menunggu',
      running: 'Memeriksa',
      succeeded: 'Selesai',
      failed: 'Gagal',
      disabled: 'Nonaktif'
    } as Record<string, string>)[status] || status;
  }

  function scanPhaseLabel(phase: string) {
    return ({
      queued: 'Menunggu worker',
      inventory: 'Membaca profil',
      runtime_probe: 'Memeriksa runtime dan profil',
      session_probe: 'Memeriksa sesi TDL',
      export_canary: 'Menguji Export',
      download_canary: 'Menguji Download',
      upload_storage: 'Mengirim canary ke Storage',
      verify_storage: 'Memverifikasi canary Storage',
      upload_tts: 'Mengirim canary ke TTS',
      verify_tts: 'Memverifikasi canary TTS',
      cleanup: 'Membersihkan canary',
      complete: 'Pemeriksaan selesai',
      failed: 'Pemeriksaan gagal',
      interrupted: 'Terhenti saat backend dimulai ulang',
      not_scanned: 'Tidak dipindai'
    } as Record<string, string>)[phase] || phase;
  }

  function readinessStatusLabel(status: string) {
    return ({
      ready: 'Siap',
      not_ready: 'Tidak siap',
      offline: 'Worker offline',
      disabled: 'Worker nonaktif',
      unscanned: 'Belum dipindai'
    } as Record<string, string>)[status] || 'Belum dipindai';
  }

  function readinessTone(status: string) {
    if (status === 'ready') return 'font-bold text-emerald-600';
    if (['not_ready', 'offline', 'disabled'].includes(status)) return 'font-bold text-rose-600';
    return 'muted font-bold';
  }

  function normalizeProfileCatalog(value: unknown): LocalProfileCatalog {
    const payload = value && typeof value === 'object' ? value as Record<string, unknown> : {};
    if (Array.isArray(payload.workers) && Array.isArray(payload.inventories)) {
      return {
        checked_at: String(payload.checked_at || ''),
        workers: payload.workers as ScanWorker[],
        inventories: payload.inventories as Inventory[],
        runtime_readiness: normalizeRuntimeReadiness(payload.runtime_readiness)
      };
    }
    // Older worker snapshots are accepted while a mixed-version deployment rolls forward.
    if (typeof payload.worker === 'string' && Array.isArray(payload.items)) {
      const checked_at = String(payload.checked_at || '');
      const worker = payload.worker;
      return {
        checked_at,
        workers: [{ name: worker, status: 'success', checked_at, error_code: '' }],
        inventories: [{ worker, checked_at, items: payload.items as LocalProfile[] }],
        runtime_readiness: normalizeRuntimeReadiness(undefined)
      };
    }
    return { checked_at: '', workers: [], inventories: [], runtime_readiness: normalizeRuntimeReadiness(undefined) };
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

  function stopScanPolling() {
    if (scanPollTimer !== undefined) clearTimeout(scanPollTimer);
    scanPollTimer = undefined;
  }

  function scheduleScanPolling(operationId: string) {
    stopScanPolling();
    scanPollTimer = setTimeout(() => void refreshScanOperation(operationId), 900);
  }

  async function finishScanOperation(operation: ProfileScanOperation) {
    scanning = false;
    stopScanPolling();
    if (operation.id === handledScanOperationId) return;
    handledScanOperationId = operation.id;
    if (operation.status !== 'succeeded') {
      failure = codeMessage(operation.error_code || 'WORKER_SCAN_FAILED');
      return;
    }
    await loadProfileCatalog();
    await session.refreshProfileCatalog();
    if (operation.target?.kind === 'worker_runtime') {
      const result = runtimeReadinessFor(
        profileCatalog?.runtime_readiness || normalizeRuntimeReadiness(undefined),
        null,
        operation.target.worker,
        operation.target.runtime
      );
      const serviceLabel = workerRuntimeLabel(operation.target.runtime);
      notice = `${serviceLabel} pada worker ${operation.target.worker}: ${readinessStatusLabel(result.status)}${result.reason_code ? ` · ${codeMessage(result.reason_code)}` : ''}.`;
      return;
    }
    if (operation.target?.kind === 'profile_runtime') {
      const target = operation.target;
      const result = runtimeReadinessFor(
        profileCatalog?.runtime_readiness || normalizeRuntimeReadiness(undefined),
        target.profile || '',
        target.worker,
        target.runtime
      );
      notice = `${workerRuntimeLabel(target.runtime)} profil ${target.profile} pada worker ${target.worker}: ${readinessStatusLabel(result.status)}${result.reason_code ? ` · ${codeMessage(result.reason_code)}` : ''}.`;
      return;
    }
    inventory = selectedWorker
      ? profileCatalog?.inventories.find((item) => item.worker === selectedWorker) || null
      : null;
    const successful = profileCatalog?.workers.filter((worker) => worker.status === 'success').length || 0;
    const failed = profileCatalog?.workers.filter((worker) => worker.status === 'failed').length || 0;
    const disabled = profileCatalog?.workers.filter((worker) => worker.status === 'disabled').length || 0;
    notice = `Scan selesai: ${successful} worker berhasil, ${failed} gagal, ${disabled} nonaktif.`;
    if (selectedWorker && inventory) {
      const generation = progressGeneration;
      await refreshDeleteOperations(selectedWorker, generation);
      await refreshVaultProfiles(selectedWorker, generation);
      scheduleProgressRefresh();
    }
  }

  async function refreshScanOperation(operationId?: string) {
    if (scanPollRequestActive) {
      if (operationId && scanOperation?.id === operationId && scanOperationIsActive(scanOperation)) {
        scheduleScanPolling(operationId);
      }
      return;
    }
    scanPollRequestActive = true;
    try {
      const path = operationId
        ? `/profiles/local/scan/${encodeURIComponent(operationId)}`
        : '/profiles/local/scan';
      const payload = await api<unknown>(path);
      const raw = operationId
        ? payload
        : payload && typeof payload === 'object'
          ? (payload as Record<string, unknown>).operation
          : null;
      const operation = normalizeScanOperation(raw);
      if (!operation) return;
      scanOperation = operation;
      scanning = scanOperationIsActive(operation);
      if (scanning) scheduleScanPolling(operation.id);
      else if (operation.status === 'succeeded' || operation.status === 'failed') {
        await finishScanOperation(operation);
      }
    } catch {
      // Keep the persisted operation visible and retry transient polling failures.
      if (operationId && scanOperation?.id === operationId && scanOperationIsActive(scanOperation)) {
        scheduleScanPolling(operationId);
      }
    } finally {
      scanPollRequestActive = false;
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
    stopScanPolling();
    stopProgressRefresh();
    catalogGeneration += 1;
    const generation = progressGeneration;
    scanning = true;
    failure = '';
    notice = '';
    try {
      const payload = await post<unknown>('/profiles/local/scan');
      if (generation !== progressGeneration) return;
      catalogFailure = '';
      const operation = normalizeScanOperation(payload);
      if (operation) {
        scanOperation = operation;
        scanning = scanOperationIsActive(operation);
        if (scanning) scheduleScanPolling(operation.id);
        else await finishScanOperation(operation);
      } else {
        // Accept the previous synchronous response during a mixed-version rollout.
        profileCatalog = normalizeProfileCatalog(payload);
        await session.refreshProfileCatalog();
        inventory = selectedWorker
          ? profileCatalog.inventories.find((item) => item.worker === selectedWorker) || null
          : null;
        const successful = profileCatalog.workers.filter((worker) => worker.status === 'success').length;
        const failed = profileCatalog.workers.filter((worker) => worker.status === 'failed').length;
        const disabled = profileCatalog.workers.filter((worker) => worker.status === 'disabled').length;
        notice = `Scan selesai: ${successful} worker berhasil, ${failed} gagal, ${disabled} nonaktif.`;
        if (selectedWorker && inventory) {
          await refreshDeleteOperations(selectedWorker, generation);
          await refreshVaultProfiles(selectedWorker, generation);
          scheduleProgressRefresh();
        }
      }
    } catch (cause) {
      if (generation !== progressGeneration) return;
      const error = cause as { code?: string; message?: string };
      failure = error.message || 'Scan profil lokal semua worker gagal. Katalog sebelumnya dipertahankan.';
    } finally {
      if (!scanOperationIsActive(scanOperation)) scanning = false;
    }
  }

  function workerRuntimeLabel(runtime: string) {
    return ({
      resolver: 'Resolver',
      tts_helper: 'TorTTS',
      quick_mode_runtime: 'Quick Mode runtime',
      rclone_storage: 'Storage rclone',
      export: 'Export',
      download: 'Download',
      upload: 'Upload',
      storage: 'Storage',
      tts: 'TTS',
      quick_mode: 'Quick Mode'
    } as Record<string, string>)[runtime] || runtime;
  }

  async function scanWorkerRuntime(worker: string, runtime: string) {
    if (scanning || loadingWorkers || !worker || !runtime) return;
    stopScanPolling();
    stopProgressRefresh();
    catalogGeneration += 1;
    const generation = progressGeneration;
    scanning = true;
    failure = '';
    notice = '';
    try {
      const payload = await post<unknown>('/profiles/local/scan/runtime', { worker, runtime });
      if (generation !== progressGeneration) return;
      const operation = normalizeScanOperation(payload);
      if (!operation) throw new Error('Operation scan runtime tidak valid.');
      scanOperation = operation;
      scanning = scanOperationIsActive(operation);
      if (scanning) scheduleScanPolling(operation.id);
      else if (operation.status === 'succeeded' || operation.status === 'failed') {
        await finishScanOperation(operation);
      }
    } catch (cause) {
      if (generation !== progressGeneration) return;
      const error = cause as { message?: string };
      failure = error.message || `Scan ${workerRuntimeLabel(runtime)} pada worker ${worker} gagal.`;
      scanning = false;
    }
  }

  async function scanProfileRuntime(worker: string, profile: string, runtime: string) {
    if (scanning || loadingWorkers || !worker || !profile || !runtime) return;
    stopScanPolling();
    stopProgressRefresh();
    catalogGeneration += 1;
    const generation = progressGeneration;
    scanning = true;
    failure = '';
    notice = '';
    try {
      const payload = await post<unknown>('/profiles/local/scan/service', { worker, profile, runtime });
      if (generation !== progressGeneration) return;
      const operation = normalizeScanOperation(payload);
      if (!operation) throw new Error('Operation scan layanan profil tidak valid.');
      scanOperation = operation;
      scanning = scanOperationIsActive(operation);
      if (scanning) scheduleScanPolling(operation.id);
      else if (operation.status === 'succeeded' || operation.status === 'failed') {
        await finishScanOperation(operation);
      }
    } catch (cause) {
      if (generation !== progressGeneration) return;
      const error = cause as { message?: string };
      failure = error.message || `Scan ${workerRuntimeLabel(runtime)} profil ${profile} pada worker ${worker} gagal.`;
      scanning = false;
    }
  }

  function openRuntimeLog(worker: string, runtime: string, attempt?: RuntimeReadinessAttempt, profile?: string) {
    runtimeLogDialog = { worker, profile, runtime, attempt };
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

  function deletionIsActive(profile: string, worker = selectedWorker) {
    return deleteOperations.some((operation) => operation.target.worker === worker
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

  async function deleteProfile(profile: LocalProfile, worker = selectedWorker) {
    if (!worker || !profile.deletable || deletionIsActive(profile.name, worker)) return;
    if (typeof window !== 'undefined' && !window.confirm(`Hapus seluruh data profil "${profile.name}" dari worker "${worker}"? Bundle Vault tidak ikut dihapus.`)) return;
    if (selectedWorker !== worker) selectWorker(worker);
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
    void refreshScanOperation();
    void loadProvisioningWorkers();
    onJobFinished = () => {
      void loadProfileCatalog();
      void session.refreshProfileCatalog();
    };
    window.addEventListener('tme3:job-finished', onJobFinished);
  });

  onDestroy(() => {
    if (onJobFinished) window.removeEventListener('tme3:job-finished', onJobFinished);
    stopScanPolling();
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
  {#if scanOperation}
    <section class="mt-4 rounded-xl border border-[var(--line)] p-3" aria-label="Progress Scan Profil" role="status">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-extrabold">{scanOperationStatusLabel(scanOperation.status)}</h2>
        {#if scanOperation.progress.total_profiles > 0}
          <span class="muted text-xs">Profil {scanOperation.progress.completed_profiles}/{scanOperation.progress.total_profiles} · Worker {scanOperation.progress.completed_workers}/{scanOperation.progress.total_workers}</span>
        {:else}
          <span class="muted text-xs">Worker {scanOperation.progress.completed_workers}/{scanOperation.progress.total_workers}</span>
        {/if}
      </div>
      {#if scanOperation.target?.kind === 'worker_runtime'}
        <p class="muted mt-1 text-xs">{workerRuntimeLabel(scanOperation.target.runtime)} · worker {scanOperation.target.worker}</p>
      {:else if scanOperation.target?.kind === 'profile_runtime'}
        <p class="muted mt-1 text-xs">{workerRuntimeLabel(scanOperation.target.runtime)} · profil {scanOperation.target.profile} · worker {scanOperation.target.worker}</p>
      {/if}
      {#if scanOperation.error_code}
        <p class="mt-2 text-xs text-rose-600">{codeMessage(scanOperation.error_code)}</p>
      {/if}
      <div class="mt-3 grid gap-2 sm:grid-cols-2">
        {#each scanOperation.progress.workers as progressWorker (progressWorker.name)}
          <article class="rounded-lg bg-[var(--panel)] p-3" aria-label={`Progress worker ${progressWorker.name}`}>
            <div class="flex items-center justify-between gap-2 text-sm">
              <span class="font-bold">{progressWorker.name}</span>
              <span class={readinessTone(progressWorker.status === 'succeeded' ? 'ready' : progressWorker.status === 'failed' ? 'not_ready' : progressWorker.status === 'disabled' ? 'disabled' : 'unscanned')}>{progressStatusLabel(progressWorker.status)}</span>
            </div>
            {#if progressWorker.phase}<p class="muted mt-1 text-xs">{scanPhaseLabel(progressWorker.phase)}</p>{/if}
            {#if progressWorker.error_code}<p class="mt-1 text-xs text-rose-600">{codeMessage(progressWorker.error_code)}</p>{/if}
            {#if progressWorker.runtime && progressWorker.checks?.[progressWorker.runtime]}
              {@const runtimeCheck = progressWorker.checks[progressWorker.runtime]}
              <p class="mt-1 text-xs">{workerRuntimeLabel(progressWorker.runtime)}: {runtimeCheck.ready ? 'Siap' : codeMessage(runtimeCheck.reason_code || 'RUNTIME_NOT_READY')}</p>
            {/if}
            {#if progressWorker.profiles.length}
              <div class="mt-2 space-y-1 border-l border-[var(--line)] pl-3">
                {#each progressWorker.profiles as progressProfile (`${progressWorker.name}:${progressProfile.name}`)}
                  <div class="flex items-center justify-between gap-2 text-xs" aria-label={`Progress profil ${progressProfile.name} pada ${progressWorker.name}`}>
                    <span>{progressProfile.name}</span>
                    <span class={readinessTone(progressProfile.status === 'succeeded' ? 'ready' : progressProfile.status === 'failed' ? 'not_ready' : 'unscanned')}>{progressStatusLabel(progressProfile.status)}</span>
                  </div>
                  {#if progressProfile.checks}
                    <div class="grid gap-1 pl-2 text-[11px] sm:grid-cols-2">
                      {#each Object.entries(progressProfile.checks) as [runtime, check] (runtime)}
                        <div class="flex items-center justify-between gap-2">
                          <span class="capitalize">{runtime === 'tts' ? 'TTS' : runtime}</span>
                          <span class={readinessTone(check.ready ? 'ready' : 'not_ready')}>{check.ready ? 'Siap' : check.reason_code || 'Tidak siap'}</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                  {#if progressProfile.cleanup && progressProfile.cleanup.status !== 'not_needed'}
                    <p class={`pl-2 text-[11px] ${progressProfile.cleanup.status === 'failed' ? 'text-amber-600' : 'text-emerald-600'}`}>
                      Cleanup canary: {progressProfile.cleanup.status === 'succeeded' ? 'berhasil' : `gagal pada ${progressProfile.cleanup.items.filter((item) => item.status === 'failed').length} pesan`}
                    </p>
                  {/if}
                {/each}
              </div>
            {/if}
          </article>
        {/each}
      </div>
    </section>
  {/if}

{#if runtimeLogDialog}
  <div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4">
    <dialog
      open
      class="relative inset-auto m-0 max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-5 shadow-2xl"
      aria-modal="true"
      aria-labelledby="runtime-scan-log-title"
    >
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="eyebrow">LOG UJI TERAKHIR</p>
          <h2 id="runtime-scan-log-title" class="mt-1 text-lg font-extrabold">Log uji {workerRuntimeLabel(runtimeLogDialog.runtime)}{#if runtimeLogDialog.profile}{' '}profil {runtimeLogDialog.profile}{/if} worker {runtimeLogDialog.worker}</h2>
        </div>
        <button class="button secondary" onclick={() => runtimeLogDialog = null} aria-label="Tutup log uji"><X size={16}/></button>
      </div>
      {#if runtimeLogDialog.attempt}
        {@const attempt = runtimeLogDialog.attempt}
        <dl class="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt class="muted text-xs">Target</dt><dd class="mt-1 font-semibold">{#if attempt.target.profile}Profil {attempt.target.profile} · {/if}Worker {attempt.target.worker} · {workerRuntimeLabel(attempt.target.runtime)}</dd></div>
          <div><dt class="muted text-xs">Waktu</dt><dd class="mt-1 font-semibold">{checkedAt(attempt.checked_at)}</dd></div>
          <div><dt class="muted text-xs">Fase terakhir</dt><dd class="mt-1 font-semibold">{attempt.phase || '—'}</dd></div>
          <div><dt class="muted text-xs">Hasil</dt><dd class={`mt-1 font-semibold ${attempt.status === 'ready' ? 'text-emerald-600' : 'text-rose-600'}`}>{attempt.status === 'ready' ? 'Siap' : 'Tidak siap'}{#if attempt.reason_code} · {codeMessage(attempt.reason_code)} <span class="font-mono text-xs">({attempt.reason_code})</span>{/if}</dd></div>
        </dl>
        <section class="mt-4 rounded-xl border border-[var(--line)] p-3" aria-label="Pemeriksaan runtime">
          <h3 class="text-sm font-bold">Pemeriksaan</h3>
          {#if attempt.checks.length}
            <ul class="mt-2 space-y-1 text-sm">
              {#each attempt.checks as check (`${check.name}:${check.status}`)}
                <li class="flex items-start justify-between gap-3"><span>{workerRuntimeLabel(check.name)}</span><span class="text-right">{check.status === 'ready' ? 'Siap' : check.reason_code ? `${codeMessage(check.reason_code)} (${check.reason_code})` : 'Tidak siap'}</span></li>
              {/each}
            </ul>
          {:else}
            <p class="muted mt-2 text-sm">Tidak ada rincian pemeriksaan.</p>
          {/if}
        </section>
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <div class="rounded-xl border border-[var(--line)] p-3"><p class="muted text-xs">Dependency diuji</p><p class="mt-1 text-sm">{attempt.dependencies.length ? attempt.dependencies.map(workerRuntimeLabel).join(', ') : 'Tidak ada'}</p></div>
          <div class="rounded-xl border border-[var(--line)] p-3"><p class="muted text-xs">Cleanup</p><p class="mt-1 text-sm">{attempt.cleanup.status === 'not_needed' ? 'Tidak diperlukan' : attempt.cleanup.status === 'succeeded' ? 'Berhasil' : `Gagal${attempt.cleanup.reason_code ? ` · ${codeMessage(attempt.cleanup.reason_code)} (${attempt.cleanup.reason_code})` : ''}`}</p></div>
        </div>
      {:else}
        <p class="muted mt-4 rounded-xl border border-dashed border-[var(--line)] p-4 text-sm">Belum ada log uji untuk runtime ini.</p>
      {/if}
      <div class="mt-5 flex justify-end"><button class="button" onclick={() => runtimeLogDialog = null}>Tutup</button></div>
    </dialog>
  </div>
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
      <section class="mt-5 border-t border-[var(--line)] pt-4" aria-label="Kesiapan per worker dan profil">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-extrabold">Kesiapan layanan per worker dan profil</h3>
          <span class="muted text-xs">Worker → profil</span>
        </div>
        <div class="mt-3 space-y-3">
          {#each profileCatalog.workers as worker (worker.name)}
            {@const workerInventory = profileCatalog.inventories.find((item) => item.worker === worker.name)}
            {@const resolver = runtimeReadinessFor(profileCatalog.runtime_readiness, null, worker.name, 'resolver')}
            {@const ttsHelper = runtimeReadinessFor(profileCatalog.runtime_readiness, null, worker.name, 'tts_helper')}
            {@const quickRuntime = runtimeReadinessFor(profileCatalog.runtime_readiness, null, worker.name, 'quick_mode_runtime')}
            {@const rcloneStorage = runtimeReadinessFor(profileCatalog.runtime_readiness, null, worker.name, 'rclone_storage')}
            {@const workerServices = [
              { name: 'Resolver', runtime: 'resolver', result: resolver },
              { name: 'TorTTS', runtime: 'tts_helper', result: ttsHelper },
              { name: 'Storage rclone', runtime: 'rclone_storage', result: rcloneStorage },
              { name: 'Quick Mode runtime', runtime: 'quick_mode_runtime', result: quickRuntime },
            ]}
            <article class="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3" aria-label={`Worker ${worker.name}`}>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h4 class="font-extrabold">Worker {worker.name}</h4>
                <span class={worker.status === 'success' ? 'font-bold text-emerald-600' : worker.status === 'failed' ? 'font-bold text-rose-600' : 'muted font-bold'}>{workerScanLabel(worker)}</span>
              </div>
              <div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {#each workerServices as service (service.name)}
                  <div class="rounded-lg border border-[var(--line)] bg-[var(--panel-strong)] px-3 py-2 text-sm" aria-label={`${service.name} worker ${worker.name}`}>
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-semibold">{service.name}</span>
                      <div class="flex items-center gap-1.5">
                        <span class={readinessTone(service.result.status)}>{readinessStatusLabel(service.result.status)}</span>
                        <button
                          class="rounded p-1 text-violet-700 hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-violet-200 dark:hover:bg-violet-950"
                          onclick={() => scanWorkerRuntime(worker.name, service.runtime)}
                          disabled={scanning || loadingWorkers || workers.find((item) => item.name === worker.name)?.enabled === false}
                          aria-label={`Scan ${service.name} worker ${worker.name}`}
                          title="Scan runtime ini"
                        ><RefreshCw size={14}/></button>
                        <button
                          class="rounded p-1 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                          onclick={() => openRuntimeLog(worker.name, service.runtime, service.result.last_attempt)}
                          aria-label={`Lihat log uji ${service.name} worker ${worker.name}`}
                          title="Lihat log uji terakhir"
                        ><CircleAlert size={14}/></button>
                      </div>
                    </div>
                    {#if service.result.status !== 'ready' && service.result.reason_code}
                      <p class="muted mt-1 text-xs">{codeMessage(service.result.reason_code)}</p>
                    {/if}
                  </div>
                {/each}
              </div>
              {#if workerInventory}
                <div class="mt-3 space-y-2 border-l-2 border-[var(--line)] pl-3">
                  {#each workerInventory.items as profile (profile.name)}
                    {@const profileServices = [
                      { name: 'Export', runtime: 'export', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'export'), scannable: true },
                      { name: 'Download', runtime: 'download', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'download'), scannable: true },
                      { name: 'Upload', runtime: 'upload', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'upload'), scannable: false },
                      { name: 'Storage', runtime: 'storage', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'storage'), scannable: true },
                      { name: 'TTS', runtime: 'tts', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'tts'), scannable: true },
                      { name: 'Quick Mode', runtime: 'quick_mode', result: runtimeReadinessFor(profileCatalog.runtime_readiness, profile.name, worker.name, 'quick_mode'), scannable: true },
                    ]}
                    <section class="rounded-lg border border-[var(--line)] bg-[var(--panel-strong)] p-3" aria-label={`Profil ${profile.name} pada worker ${worker.name}`}>
                      <div class="flex flex-wrap items-center justify-between gap-2">
                        <h5 class="font-bold">Profil {profile.name}</h5>
                        <div class="flex flex-wrap items-center gap-2">
                          <span class={profile.ready ? 'font-semibold text-emerald-600' : 'font-semibold text-rose-600'}>{profile.ready ? 'Sesi tersedia' : 'Sesi perlu diperiksa'}</span>
                          {#if profile.deletable}
                            <button class="button secondary" onclick={() => deleteProfile(profile, worker.name)} disabled={deletionIsActive(profile.name, worker.name)} aria-label={`Hapus profil ${profile.name} dari ${worker.name}`}>
                              <Trash2 size={15}/>{deletionIsActive(profile.name, worker.name) ? 'Menghapus...' : 'Hapus profil'}
                            </button>
                          {/if}
                        </div>
                      </div>
                      <div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {#each profileServices as service (service.name)}
                          <div class="rounded-md bg-[var(--panel)] px-2 py-1.5 text-xs" aria-label={`${service.name} profil ${profile.name} worker ${worker.name}`}>
                            <div class="flex items-center justify-between gap-2">
                              <span>{service.name}</span>
                              <div class="flex items-center gap-1.5">
                                <span class={readinessTone(service.result.status)}>{readinessStatusLabel(service.result.status)}</span>
                                {#if service.scannable}
                                  <button
                                    class="rounded p-1 text-violet-700 hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-violet-200 dark:hover:bg-violet-950"
                                    onclick={() => scanProfileRuntime(worker.name, profile.name, service.runtime)}
                                    disabled={scanning || loadingWorkers || workers.find((item) => item.name === worker.name)?.enabled === false}
                                    aria-label={`Scan ${service.name} profil ${profile.name} worker ${worker.name}`}
                                    title={service.runtime === 'quick_mode' ? 'Hitung dari bukti tersimpan' : 'Scan layanan profil ini'}
                                  ><RefreshCw size={13}/></button>
                                {/if}
                                <button
                                  class="rounded p-1 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                                  onclick={() => openRuntimeLog(worker.name, service.runtime, service.result.last_attempt, profile.name)}
                                  aria-label={`Lihat log uji ${service.name} profil ${profile.name} worker ${worker.name}`}
                                  title="Lihat log uji terakhir"
                                ><CircleAlert size={13}/></button>
                              </div>
                            </div>
                            {#if service.result.status !== 'ready' && service.result.reason_code}
                              <p class="muted mt-1">{codeMessage(service.result.reason_code)}</p>
                            {/if}
                          </div>
                        {/each}
                      </div>
                    </section>
                  {/each}
                </div>
              {:else if worker.status === 'success'}
                <p class="muted mt-3 border-l-2 border-[var(--line)] pl-3 text-xs">Worker ini belum mengembalikan profil lokal.</p>
              {/if}
            </article>
          {/each}
        </div>
      </section>
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
          {@const exportReadiness = runtimeReadinessFor(profileCatalog?.runtime_readiness || normalizeRuntimeReadiness(undefined), profile.name, inventory.worker)}
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
            <section class={`mt-4 rounded-xl border p-3 ${exportReadiness.status === 'ready' ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100' : exportReadiness.status === 'offline' || exportReadiness.status === 'not_ready' ? 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-100' : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100'}`} aria-label={`Kesiapan Export ${profile.name} pada ${inventory.worker}`} role="status">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="text-sm font-bold">Kesiapan runtime Export · {exportReadinessLabels[exportReadiness.status]}</p>
                {#if exportReadiness.checked_at}<span class="text-xs opacity-75">{checkedAt(exportReadiness.checked_at)}</span>{/if}
              </div>
              {#if exportReadiness.status === 'ready'}
                <p class="mt-1 text-xs">Sesi TDL pada worker ini lolos scan terakhir. Export dapat dikirim tanpa verifikasi ulang.</p>
              {:else if exportReadiness.status === 'unscanned'}
                <p class="mt-1 text-xs">Jalankan Scan semua worker untuk menyimpan kesiapan Export.</p>
              {:else}
                <p class="mt-1 text-xs">{codeMessage(exportReadiness.reason_code || 'PROFILE_SESSION_UNAVAILABLE')}. Jalankan Scan semua worker setelah sesi diperbaiki.</p>
              {/if}
            </section>
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
