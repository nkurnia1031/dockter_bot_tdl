<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api, post, remove } from "../lib/api";
import { sessionActions } from "../session";
import {
  normalizeRuntimeReadiness,
  runtimeReadinessFor,
  type RuntimeReadinessAttempt,
  type RuntimeReadinessSnapshot,
  type RuntimeReadinessResult,
} from "../../../src/lib/profile-catalog";

type Worker = { name: string; enabled: boolean; selected?: boolean };
type ProvisioningWorker = {
  name: string;
  enabled: boolean;
  online: boolean;
  secure: boolean;
};
type ProfileCheck = { name: string; ready: boolean; code: string };
type UploadLane = {
  status: string;
  phase: string;
  progress: number;
  code: string;
  updated_at: string;
};
type LocalProfile = {
  name: string;
  ready: boolean;
  deletable?: boolean;
  reason_codes: string[];
  checks: ProfileCheck[];
  upload_lane: UploadLane;
};
type IdentityCleanup = {
  profile: string;
  status: string;
  deleted_worker: string;
  updated_at: string;
};
type Inventory = {
  worker: string;
  checked_at: string;
  items: LocalProfile[];
  pending_identity_cleanup?: IdentityCleanup[];
};
type ScanWorker = {
  name: string;
  status: "success" | "failed" | "disabled";
  checked_at: string;
  error_code: string;
};
type LocalProfileCatalog = {
  checked_at: string;
  workers: ScanWorker[];
  inventories: Inventory[];
  runtime_readiness: RuntimeReadinessSnapshot;
};
type ScanProfileProgress = {
  name: string;
  status: string;
  phase: string;
  error_code: string;
  checks?: Record<string, { ready: boolean; reason_code: string }>;
  cleanup?: {
    status: "not_needed" | "succeeded" | "failed";
    items: Array<{
      target: string;
      message_id: number;
      status: string;
      error_code: string;
    }>;
  };
};
type ScanWorkerProgress = {
  name: string;
  status: string;
  phase: string;
  error_code: string;
  profiles: ScanProfileProgress[];
  runtime?: string;
  checks?: Record<string, { ready: boolean; reason_code: string }>;
};
type ProfileScanLogEvent = {
  sequence: number;
  worker: string;
  profile: string;
  runtime: string;
  kind: "command" | "output" | "exit" | "error" | "message";
  stream: "system" | "stdout" | "stderr";
  text: string;
  exit_code: number | null;
  created_at: string;
};
type ProfileScanLogPage = {
  events: ProfileScanLogEvent[];
  next_sequence: number;
  has_more: boolean;
};
type ProfileScanTarget =
  | { kind: "worker"; worker: string }
  | { kind: "worker_runtime"; worker: string; runtime: string }
  | {
      kind: "profile_runtime";
      worker: string;
      profile: string;
      runtime: string;
    };
type ProfileScanOperation = {
  id: string;
  status: string;
  target?: ProfileScanTarget;
  progress: {
    workers: ScanWorkerProgress[];
    total_workers: number;
    completed_workers: number;
    total_profiles: number;
    completed_profiles: number;
  };
  error_code: string;
  created_at: string;
  updated_at: string;
  finished_at: string;
};
type WorkerScanLogDialog = { operationId: string; worker: string };
type VaultProfile = {
  name: string;
  vault: boolean;
  status: string;
  source?: string;
  operation_id?: string;
  error?: string;
};
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
type RuntimeLogDialog = {
  worker: string;
  profile?: string;
  runtime: string;
  attempt?: RuntimeReadinessAttempt;
};

const workers = ref<Worker[]>([]);
const selectedWorker = ref("");
const provisioningWorkers = ref<ProvisioningWorker[]>([]);
const provisioningWorker = ref("");
const profileName = ref("");
const provisioningMode = ref<"upload" | "login">("upload");
const loginMethod = ref<"qr" | "code">("qr");
const loginPhone = ref("");
const loginInput = ref("");
const profileArchive = ref<File | null>(null);
const provisioningOperation = ref<ProvisioningOperation | null>(null);
const provisioningLoading = ref(false);
const provisioningFailure = ref("");
const provisioningNotice = ref("");
const inventory = ref<Inventory | null>(null);
const profileCatalog = ref<LocalProfileCatalog | null>(null);
const scanOperation = ref<ProfileScanOperation | null>(null);
const runtimeLogDialog = ref<RuntimeLogDialog | null>(null);
const workerScanLogDialog = ref<WorkerScanLogDialog | null>(null);
const workerScanLogEvents = ref<ProfileScanLogEvent[]>([]);
const workerScanLogCursor = ref(0);
const workerScanLogLoading = ref(false);
const workerScanLogFailure = ref("");
const catalogFailure = ref("");
const vaultProfiles = ref<VaultProfile[]>([]);
const vaultStatusLoaded = ref(false);
const vaultStatusFailure = ref("");
const adoptionOperations = ref<Record<string, AdoptionOperation>>({});
const adoptingProfiles = ref<string[]>([]);
const deleteOperations = ref<DeleteOperation[]>([]);
const loadingWorkers = ref(false);
const scanning = ref(false);
const savingProvisioning = ref(false);
const failure = ref("");
const notice = ref("");
const checkedAt = computed(() =>
  profileCatalog.value?.checked_at
    ? formatDate(profileCatalog.value.checked_at)
    : "",
);
const scanActive = computed(() =>
  Boolean(
    scanOperation.value &&
      ["queued", "running"].includes(scanOperation.value.status),
  ),
);
const availableProvisioningWorkers = computed(() =>
  provisioningWorkers.value.filter((worker) => worker.online && worker.secure),
);
const selectedInventory = computed(() => inventory.value);
const displayedProgressWorkers = computed(
  () => scanOperation.value?.progress.workers || [],
);
const localDeleteOps = computed(() =>
  deleteOperations.value.filter(
    (item) => item.target.worker === selectedWorker.value,
  ),
);

let scanPollTimer: ReturnType<typeof setTimeout> | undefined;
let scanLogPollTimer: ReturnType<typeof setTimeout> | undefined;
let progressTimer: ReturnType<typeof setTimeout> | undefined;
let provisioningTimer: ReturnType<typeof setTimeout> | undefined;
let provisioningRequestActive = false;
let progressRequestActive = false;
let scanPollRequestActive = false;
let scanLogPollRequestActive = false;
let scanLogRefreshPending = false;
let handledScanOperationId = "";
let progressGeneration = 0;
let catalogGeneration = 0;
let mounted = false;

const codeMessages: Record<string, string> = {
  PROFILE_IDENTITY_MISSING: "File identitas tidak ditemukan.",
  PROFILE_IDENTITY_INVALID: "Identitas profil tidak valid.",
  PROFILE_IDENTITY_UNSAFE: "File identitas menggunakan path yang tidak aman.",
  PROFILE_ROOT_SESSION_MISSING: "Sesi lane Download tidak ditemukan.",
  PROFILE_USER1_SESSION_MISSING: "Sesi lane Export tidak ditemukan.",
  PROFILE_ROOT_SESSION_EMPTY: "Data sesi lane Download kosong.",
  PROFILE_USER1_SESSION_EMPTY: "Data sesi lane Export kosong.",
  PROFILE_SESSION_UNSAFE: "Sesi berisi path yang tidak aman.",
  PROFILE_SESSION_UNREADABLE: "Data sesi tidak dapat dibaca.",
  PROFILE_SESSION_BUSY: "Sesi sedang dipakai job.",
  PROFILE_SESSION_UNAVAILABLE: "Pemeriksaan sesi tidak tersedia.",
  PROFILE_SESSION_CHANGED:
    "Scan lama mencatat perubahan sesi; perintah aktual tetap menentukan apakah lane dapat dipakai.",
  PROFILE_SESSION_MISSING: "Sesi profil sudah dihapus dari worker.",
  PROFILE_EXPORT_SESSION_MISSING: "Sesi Export tidak ditemukan.",
  PROFILE_EXPORT_SESSION_UNSAFE: "Sesi Export memiliki file yang tidak aman.",
  PROFILE_EXPORT_SESSION_INVALID: "TDL tidak dapat memakai sesi Export.",
  PROFILE_EXPORT_IDENTITY_MISMATCH:
    "Identitas sesi Export tidak cocok dengan profil.",
  PROFILE_UPLOAD_LANE_UNSAFE: "Folder lane Upload tidak aman.",
  PROFILE_UPLOAD_SESSION_INVALID:
    "TDL tidak dapat memakai salinan sesi Upload.",
  PROFILE_UPLOAD_IDENTITY_MISMATCH:
    "Identitas sesi Upload tidak cocok dengan profil.",
  PROFILE_DEFAULT_PROTECTED: "Profil default tidak dapat dihapus.",
  PROFILE_ROOT_UNSAFE:
    "Folder profil menggunakan path yang tidak aman; tidak ada data dihapus.",
  PROFILE_DELETE_FAILED:
    "Penghapusan gagal. Periksa worker dan scan kembali sebelum mencoba lagi.",
  PROFILE_UPLOAD_PREPARATION_FAILED:
    "Worker gagal menyiapkan lane Upload. Tekan Scan untuk mencoba lagi.",
  PROFILE_UPLOAD_PREPARATION_INTERRUPTED:
    "Pemeriksaan lane Upload belum selesai. Tekan Scan untuk mencoba lagi.",
  WORKER_UNAVAILABLE: "Worker offline atau tidak dapat dijangkau.",
  WORKER_TIMEOUT: "Worker melewati batas waktu pemeriksaan.",
  WORKER_UPDATE_REQUIRED:
    "Worker perlu diperbarui untuk membaca inventaris profil.",
  RESOLVER_RUNTIME_UNAVAILABLE:
    "Addon Resolver tidak dapat digunakan pada worker.",
  RESOLVER_FINGERPRINT_MISSING: "Bukti kesiapan Resolver tidak lengkap.",
  RCLONE_ACCESS_FAILED:
    "Worker tidak dapat mengakses root rclone. Periksa izin dan koneksi remote.",
  RCLONE_FINGERPRINT_MISSING: "Bukti akses root rclone tidak lengkap.",
  RCLONE_DESTINATION_CHANGED: "Root rclone berubah sejak Scan Profil terakhir.",
  UTILITY_COMMAND_MISSING:
    "Perintah pendukung Utility tidak tersedia pada worker.",
  UTILITY_SCRIPT_MISSING: "Script Utility tidak ditemukan pada worker.",
  UTILITY_SCRIPT_UNREADABLE: "Script Utility tidak dapat dibaca pada worker.",
  UTILITY_WORKSPACE_UNAVAILABLE:
    "Workspace Utility tidak tersedia atau tidak dapat ditulis.",
  UTILITY_RUNTIME_UNAVAILABLE: "Runtime Utility tidak tersedia pada worker.",
  UTILITY_FINGERPRINT_MISSING: "Fingerprint runtime Utility tidak tersedia.",
  TTS_CHAT_UNAVAILABLE: "Chat tujuan TTS belum dikonfigurasi.",
  TTS_HELPER_UNAVAILABLE: "Helper TTS atau jalur Tor belum siap.",
  TTS_RUNTIME_UNAVAILABLE: "Runtime helper TTS tidak tersedia.",
  TTS_FINGERPRINT_MISSING: "Fingerprint kesiapan TTS tidak tersedia.",
  TDL_ACCESS_TARGET_UNAVAILABLE: "Tujuan Storage belum dikonfigurasi.",
  STORAGE_EVIDENCE_INCOMPLETE:
    "Bukti lane Upload atau akses Storage belum lengkap.",
  STORAGE_FINGERPRINT_MISSING: "Fingerprint kesiapan Storage tidak tersedia.",
  PROFILE_UPLOAD_SESSION_CHANGED:
    "Scan lama mencatat perubahan sesi; perintah aktual tetap menentukan apakah lane dapat dipakai.",
  QUICK_MODE_RUNTIME_UNAVAILABLE: "Runtime Quick Mode belum siap pada worker.",
  QUICK_MODE_FINGERPRINT_MISSING:
    "Fingerprint runtime Quick Mode tidak tersedia.",
  QUICK_MODE_EVIDENCE_INCOMPLETE: "Snapshot Upload Quick Mode belum lengkap.",
  RCLONE_RUNTIME_UNAVAILABLE: "Remote atau konfigurasi rclone belum siap.",
  TDL_ACCESS_NOT_VERIFIED:
    "Belum ada hasil command aktual untuk akses ini. Job tetap dapat dijalankan.",
  RUNTIME_NOT_SCANNED:
    "Belum ada hasil command terbaru. Job tetap dapat dijalankan.",
  TDL_SESSION_UNAUTHORIZED: "Sesi TDL tidak terotorisasi untuk mengirim.",
  WORKER_SCAN_FAILED: "Worker gagal membaca inventaris profil.",
};
const runtimeNames: Record<string, string> = {
  resolver: "Resolver",
  tts_helper: "TorTTS",
  quick_mode_runtime: "Quick Mode runtime",
  rclone_storage: "Storage rclone",
  export: "Export",
  download: "Download",
  upload: "Upload",
  storage: "Storage",
  tts: "TTS",
  quick_mode: "Quick Mode",
};
const runtimeLabels: Record<string, string> = {
  ready: "Siap",
  not_ready: "Tidak siap",
  offline: "Worker offline",
  disabled: "Worker nonaktif",
  unscanned: "Belum dipindai",
};
const scanPhases: Record<string, string> = {
  queued: "Menunggu worker",
  inventory: "Membaca profil",
  runtime_probe: "Memeriksa runtime dan profil",
  session_probe: "Memeriksa sesi TDL",
  export_canary: "Menguji Export Storage (last 1)",
  download_canary: "Menguji Download (maks. 20 detik)",
  storage_access_canary: "Menguji akses Storage (export last 1)",
  tts_access_canary: "Menguji akses TTS (export last 1)",
  upload_storage: "Canary Storage lama",
  verify_storage: "Verifikasi Storage lama",
  upload_tts: "Canary TTS lama",
  verify_tts: "Verifikasi TTS lama",
  cleanup: "Membersihkan canary",
  complete: "Pemeriksaan selesai",
  failed: "Pemeriksaan gagal",
  interrupted: "Terhenti saat backend dimulai ulang",
  not_scanned: "Tidak dipindai",
};

function codeMessage(code?: string) {
  return codeMessages[code || ""] || code || "Status tidak diketahui";
}
function formatDate(value?: string) {
  if (!value) return "Waktu tidak tersedia";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("id-ID");
}
function runtimeName(runtime: string) {
  return runtimeNames[runtime] || runtime.replaceAll("_", " ");
}
function runtimeLogTitle(dialog: RuntimeLogDialog) {
  const profile = dialog.profile ? ` profil ${dialog.profile}` : "";
  return `Log uji ${runtimeName(dialog.runtime)}${profile} worker ${dialog.worker}`;
}
function readinessLabel(status: string) {
  return runtimeLabels[status] || "Belum dipindai";
}
function readinessClass(status: string) {
  return status === "ready"
    ? "status-ready"
    : ["not_ready", "offline"].includes(status)
      ? "status-failed"
      : status === "disabled"
        ? "status-neutral"
        : "status-warning";
}
function cleanupLabel(status: string) {
  return status === "succeeded"
    ? "berhasil"
    : status === "failed"
      ? "gagal"
      : status === "not_needed"
        ? "tidak diperlukan"
        : status;
}
function normalizeProfileCatalog(value: unknown): LocalProfileCatalog {
  const payload =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  if (Array.isArray(payload.workers) && Array.isArray(payload.inventories))
    return {
      checked_at: String(payload.checked_at || ""),
      workers: payload.workers as ScanWorker[],
      inventories: payload.inventories as Inventory[],
      runtime_readiness: normalizeRuntimeReadiness(payload.runtime_readiness),
    };
  if (typeof payload.worker === "string" && Array.isArray(payload.items)) {
    const checked_at = String(payload.checked_at || "");
    return {
      checked_at,
      workers: [
        { name: payload.worker, status: "success", checked_at, error_code: "" },
      ],
      inventories: [
        {
          worker: payload.worker,
          checked_at,
          items: payload.items as LocalProfile[],
        },
      ],
      runtime_readiness: normalizeRuntimeReadiness(undefined),
    };
  }
  return {
    checked_at: "",
    workers: [],
    inventories: [],
    runtime_readiness: normalizeRuntimeReadiness(undefined),
  };
}
function normalizeScanOperation(value: unknown): ProfileScanOperation | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (
    typeof raw.id !== "string" ||
    !["queued", "running", "succeeded", "failed"].includes(String(raw.status))
  )
    return null;
  const progress =
    raw.progress && typeof raw.progress === "object"
      ? (raw.progress as Record<string, unknown>)
      : {};
  const workers = Array.isArray(progress.workers)
    ? progress.workers.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const worker = item as Record<string, unknown>;
        if (typeof worker.name !== "string") return [];
        const profiles = Array.isArray(worker.profiles)
          ? worker.profiles.flatMap((profileValue) => {
              if (
                !profileValue ||
                typeof profileValue !== "object" ||
                typeof (profileValue as Record<string, unknown>).name !==
                  "string"
              )
                return [];
              const profile = profileValue as Record<string, unknown>;
              const checks =
                profile.checks && typeof profile.checks === "object"
                  ? Object.fromEntries(
                      Object.entries(
                        profile.checks as Record<string, unknown>,
                      ).flatMap(([name, value]) =>
                        value && typeof value === "object"
                          ? [
                              [
                                name,
                                {
                                  ready:
                                    (value as Record<string, unknown>).ready ===
                                    true,
                                  reason_code: String(
                                    (value as Record<string, unknown>)
                                      .reason_code || "",
                                  ),
                                },
                              ],
                            ]
                          : [],
                      ),
                    )
                  : undefined;
              return [
                {
                  name: String(profile.name),
                  status: String(profile.status || "queued"),
                  phase: String(profile.phase || ""),
                  error_code: String(profile.error_code || ""),
                  checks,
                },
              ];
            })
          : [];
        const checks =
          worker.checks && typeof worker.checks === "object"
            ? Object.fromEntries(
                Object.entries(
                  worker.checks as Record<string, unknown>,
                ).flatMap(([name, value]) =>
                  value && typeof value === "object"
                    ? [
                        [
                          name,
                          {
                            ready:
                              (value as Record<string, unknown>).ready === true,
                            reason_code: String(
                              (value as Record<string, unknown>).reason_code ||
                                "",
                            ),
                          },
                        ],
                      ]
                    : [],
                ),
              )
            : undefined;
        return [
          {
            name: worker.name,
            status: String(worker.status || "queued"),
            phase: String(worker.phase || ""),
            error_code: String(worker.error_code || ""),
            profiles,
            runtime: String(worker.runtime || ""),
            checks,
          },
        ];
      })
    : [];
  const targetRaw =
    raw.target && typeof raw.target === "object"
      ? (raw.target as Record<string, unknown>)
      : {};
  const worker = String(targetRaw.worker || "")
    .trim()
    .toLowerCase();
  const profile = String(targetRaw.profile || "")
    .trim()
    .toLowerCase();
  const runtime = String(targetRaw.runtime || "")
    .trim()
    .toLowerCase();
  let target: ProfileScanTarget | undefined;
  if (targetRaw.kind === "worker" && worker)
    target = { kind: "worker", worker };
  else if (targetRaw.kind === "worker_runtime" && worker && runtime)
    target = { kind: "worker_runtime", worker, runtime };
  else if (targetRaw.kind === "profile_runtime" && worker && profile && runtime)
    target = { kind: "profile_runtime", worker, profile, runtime };
  const count = (value: unknown) =>
    Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
  return {
    id: raw.id,
    status: String(raw.status),
    target,
    progress: {
      workers,
      total_workers: count(progress.total_workers),
      completed_workers: count(progress.completed_workers),
      total_profiles: count(progress.total_profiles),
      completed_profiles: count(progress.completed_profiles),
    },
    error_code: String(raw.error_code || ""),
    created_at: String(raw.created_at || ""),
    updated_at: String(raw.updated_at || ""),
    finished_at: String(raw.finished_at || ""),
  };
}
function statusLabel(status: string) {
  return (
    (
      {
        queued: "Dalam antrean",
        running: "Berjalan",
        succeeded: "Scan selesai",
        failed: "Scan gagal",
      } as Record<string, string>
    )[status] || "Status tidak diketahui"
  );
}
function progressStatus(status: string) {
  return (
    (
      {
        queued: "Menunggu",
        running: "Memeriksa",
        succeeded: "Selesai",
        failed: "Gagal",
        disabled: "Nonaktif",
      } as Record<string, string>
    )[status] || status
  );
}
function workerStatusLabel(worker: ScanWorker) {
  if (worker.status === "success")
    return `Berhasil · ${profileCatalog.value?.inventories.find((item) => item.worker === worker.name)?.items.length || 0} profil`;
  if (worker.status === "disabled") return "Nonaktif · tidak dipindai";
  return `Gagal · ${codeMessage(worker.error_code || "WORKER_SCAN_FAILED")}`;
}
function workerRuntimeReadiness(worker: string, runtime: string) {
  return runtimeReadinessFor(
    profileCatalog.value?.runtime_readiness ||
      normalizeRuntimeReadiness(undefined),
    null,
    worker,
    runtime,
  );
}
function profileRuntimeReadiness(
  worker: string,
  profile: string,
  runtime: string,
) {
  return runtimeReadinessFor(
    profileCatalog.value?.runtime_readiness ||
      normalizeRuntimeReadiness(undefined),
    profile,
    worker,
    runtime,
  );
}
function isScanActive(operation: ProfileScanOperation | null) {
  return !!operation && ["queued", "running"].includes(operation.status);
}

function stopScanPoll() {
  if (scanPollTimer) clearTimeout(scanPollTimer);
  scanPollTimer = undefined;
}
function scheduleScanPoll(id: string) {
  stopScanPoll();
  scanPollTimer = setTimeout(() => void refreshScanOperation(id), 900);
}
function stopLogPoll() {
  if (scanLogPollTimer) clearTimeout(scanLogPollTimer);
  scanLogPollTimer = undefined;
}
function scheduleLogPoll() {
  stopLogPoll();
  if (workerScanLogDialog.value && isScanActive(scanOperation.value))
    scanLogPollTimer = setTimeout(() => void refreshWorkerScanLogs(), 900);
}
function closeWorkerScanLogs() {
  stopLogPoll();
  workerScanLogDialog.value = null;
  workerScanLogEvents.value = [];
  workerScanLogCursor.value = 0;
  workerScanLogFailure.value = "";
}
async function refreshWorkerScanLogs(force = false) {
  const dialog = workerScanLogDialog.value;
  if (!dialog) return;
  if (scanLogPollRequestActive) {
    if (force) scanLogRefreshPending = true;
    return;
  }
  scanLogPollRequestActive = true;
  workerScanLogLoading.value = workerScanLogEvents.value.length === 0;
  workerScanLogFailure.value = "";
  try {
    let hasMore = true;
    while (
      hasMore &&
      workerScanLogDialog.value?.operationId === dialog.operationId &&
      workerScanLogDialog.value.worker === dialog.worker
    ) {
      const query = new URLSearchParams({
        worker: dialog.worker,
        after_sequence: String(workerScanLogCursor.value),
        limit: "500",
      });
      const page = await api<ProfileScanLogPage>(
        `/profiles/local/scan/${encodeURIComponent(dialog.operationId)}/logs?${query}`,
      );
      if (
        workerScanLogDialog.value?.operationId !== dialog.operationId ||
        workerScanLogDialog.value.worker !== dialog.worker
      )
        return;
      const events = Array.isArray(page.events) ? page.events : [];
      if (events.length) {
        workerScanLogEvents.value = [...workerScanLogEvents.value, ...events];
        workerScanLogCursor.value = Math.max(
          workerScanLogCursor.value,
          Number(page.next_sequence) || 0,
        );
      }
      hasMore = page.has_more === true;
    }
  } catch (cause) {
    if (workerScanLogDialog.value?.operationId === dialog.operationId)
      workerScanLogFailure.value =
        cause instanceof Error ? cause.message : "Log scan gagal dimuat.";
  } finally {
    scanLogPollRequestActive = false;
    workerScanLogLoading.value = false;
    if (scanLogRefreshPending && workerScanLogDialog.value) {
      scanLogRefreshPending = false;
      void refreshWorkerScanLogs(true);
    } else scheduleLogPoll();
  }
}
function openWorkerScanLogs(operation: ProfileScanOperation, worker: string) {
  stopLogPoll();
  workerScanLogDialog.value = { operationId: operation.id, worker };
  workerScanLogEvents.value = [];
  workerScanLogCursor.value = 0;
  workerScanLogFailure.value = "";
  void refreshWorkerScanLogs();
}

async function loadProfileCatalog() {
  const generation = catalogGeneration;
  catalogFailure.value = "";
  try {
    const result = normalizeProfileCatalog(
      await api<unknown>("/profiles/local"),
    );
    if (generation !== catalogGeneration) return;
    profileCatalog.value = result;
    inventory.value = selectedWorker.value
      ? result.inventories.find(
          (item) => item.worker === selectedWorker.value,
        ) || null
      : null;
  } catch (cause) {
    catalogFailure.value =
      cause instanceof Error
        ? cause.message
        : "Katalog profil lokal gagal dimuat.";
  }
}
async function loadWorkers() {
  loadingWorkers.value = true;
  failure.value = "";
  try {
    const result = await api<{ items: Worker[] }>("/workers");
    workers.value = Array.isArray(result.items) ? result.items : [];
    if (
      selectedWorker.value &&
      !workers.value.some((item) => item.name === selectedWorker.value)
    ) {
      selectWorker("");
    } else if (selectedWorker.value)
      inventory.value =
        profileCatalog.value?.inventories.find(
          (item) => item.worker === selectedWorker.value,
        ) || null;
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Daftar worker gagal dimuat.";
  } finally {
    loadingWorkers.value = false;
  }
}
function stopProgressRefresh() {
  progressGeneration += 1;
  if (progressTimer) clearTimeout(progressTimer);
  progressTimer = undefined;
}
function isDeleteActive(operation: DeleteOperation) {
  return [
    "queued",
    "running",
    "waiting_worker",
    "paused",
    "cancelling",
  ].includes(operation.status);
}
function isAdoptionActive(operation: AdoptionOperation) {
  return ["validating", "distributing"].includes(operation.status);
}
function adoptionIsActive(profile: string) {
  const op = adoptionOperations.value[profile];
  return (
    adoptingProfiles.value.includes(profile) ||
    Boolean(op && isAdoptionActive(op))
  );
}
function isVaulted(profile: string) {
  return vaultProfiles.value.some(
    (item) => item.name === profile && item.vault,
  );
}
function deletionIsActive(profile: string, worker = selectedWorker.value) {
  return deleteOperations.value.some(
    (op) =>
      op.target.worker === worker &&
      op.target.profile === profile &&
      isDeleteActive(op),
  );
}
function scheduleProgressRefresh() {
  stopProgressRefresh();
  if (
    !inventory.value?.items.some(
      (item) => item.upload_lane?.status === "running",
    ) &&
    !deleteOperations.value.some(isDeleteActive) &&
    !Object.values(adoptionOperations.value).some(isAdoptionActive)
  )
    return;
  progressTimer = setTimeout(() => void refreshProgress(), 1500);
}
function selectWorker(value: string) {
  stopProgressRefresh();
  selectedWorker.value = value;
  inventory.value =
    profileCatalog.value?.inventories.find((item) => item.worker === value) ||
    null;
  deleteOperations.value = [];
  vaultProfiles.value = [];
  vaultStatusLoaded.value = false;
  vaultStatusFailure.value = "";
  adoptionOperations.value = {};
  adoptingProfiles.value = [];
  failure.value = "";
  notice.value = "";
  if (value && inventory.value) {
    const generation = progressGeneration;
    scheduleProgressRefresh();
    void refreshDeleteOperations(value, generation);
    void refreshVaultProfiles(value, generation);
  }
}
async function refreshDeleteOperations(
  worker: string,
  generation = progressGeneration,
) {
  try {
    const result = await api<{ items: DeleteOperation[] }>(
      "/operations?limit=100",
    );
    if (generation !== progressGeneration || selectedWorker.value !== worker)
      return;
    const previous = deleteOperations.value;
    deleteOperations.value = (Array.isArray(result.items) ? result.items : [])
      .filter(
        (item) =>
          item.kind === "profile.local_delete" && item.target.worker === worker,
      )
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 10);
    for (const operation of deleteOperations.value.filter(
      (item) =>
        item.status === "succeeded" &&
        previous.some(
          (old) =>
            old.operation_id === item.operation_id && isDeleteActive(old),
        ),
    )) {
      const name = String(operation.target.profile || "");
      if (inventory.value?.worker === worker && name)
        inventory.value = {
          ...inventory.value,
          items: inventory.value.items.filter((item) => item.name !== name),
        };
    }
  } catch {
    /* Keep the latest inventory when operation history is unavailable. */
  }
}
async function refreshVaultProfiles(
  worker: string,
  generation = progressGeneration,
) {
  try {
    const result = await api<{
      items: VaultProfile[];
      workers?: ProvisioningWorker[];
    }>("/profiles/management");
    if (generation !== progressGeneration || selectedWorker.value !== worker)
      return;
    vaultProfiles.value = Array.isArray(result.items) ? result.items : [];
    if (Array.isArray(result.workers)) setProvisioningWorkers(result.workers);
    vaultStatusLoaded.value = true;
    vaultStatusFailure.value = "";
    const next: Record<string, AdoptionOperation> = {};
    for (const item of vaultProfiles.value)
      if (
        item.source === "adoption" &&
        item.operation_id &&
        [
          "validating",
          "distributing",
          "stored",
          "failed",
          "cancelled",
        ].includes(item.status)
      )
        next[item.name] = {
          id: item.operation_id,
          status: item.status,
          error: item.error,
        };
    adoptionOperations.value = { ...adoptionOperations.value, ...next };
  } catch (cause) {
    if (generation !== progressGeneration || selectedWorker.value !== worker)
      return;
    vaultStatusLoaded.value = false;
    vaultStatusFailure.value =
      cause instanceof Error
        ? cause.message
        : "Status Vault belum dapat dimuat.";
  }
}
async function refreshAdoptionOperations() {
  const active = Object.entries(adoptionOperations.value).filter(([, op]) =>
    isAdoptionActive(op),
  );
  if (!active.length) return;
  const results = await Promise.allSettled(
    active.map(async ([profile, op]) => {
      const current = await api<{ id: string; status: string; error?: string }>(
        `/profiles/provisionings/${encodeURIComponent(op.id)}`,
      );
      return {
        profile,
        id: current.id,
        status: current.status,
        error: current.error,
      };
    }),
  );
  const next = { ...adoptionOperations.value };
  for (const result of results)
    if (result.status === "fulfilled") {
      const op = result.value;
      next[op.profile] = { id: op.id, status: op.status, error: op.error };
      if (op.status === "stored") {
        vaultProfiles.value = [
          ...vaultProfiles.value.filter((item) => item.name !== op.profile),
          {
            name: op.profile,
            vault: true,
            status: "stored",
            source: "adoption",
            operation_id: op.id,
          },
        ];
        notice.value = `Profil ${op.profile} tersimpan di Vault. Tidak ada worker lain yang diubah.`;
      }
    }
  adoptionOperations.value = next;
}
async function refreshProgress() {
  if (!selectedWorker.value || !inventory.value || scanning.value) return;
  if (progressRequestActive) {
    progressTimer = setTimeout(() => void refreshProgress(), 250);
    return;
  }
  const worker = selectedWorker.value,
    generation = progressGeneration;
  if (document.visibilityState === "hidden") {
    progressTimer = setTimeout(() => void refreshProgress(), 4000);
    return;
  }
  const refreshInventory =
    inventory.value.items.some(
      (profile) => profile.upload_lane?.status === "running",
    ) || deleteOperations.value.some(isDeleteActive);
  progressRequestActive = true;
  try {
    if (refreshInventory) {
      inventory.value = await api<Inventory>(
        `/workers/${encodeURIComponent(worker)}/profiles/local`,
      );
      if (generation !== progressGeneration || selectedWorker.value !== worker)
        return;
      await refreshDeleteOperations(worker, generation);
    }
    await refreshAdoptionOperations();
    if (generation !== progressGeneration || selectedWorker.value !== worker)
      return;
    failure.value = "";
    scheduleProgressRefresh();
  } catch (cause) {
    if (generation !== progressGeneration || selectedWorker.value !== worker)
      return;
    failure.value = `${cause instanceof Error ? cause.message : "Status tidak dapat dimuat."} Status lane Upload berhenti diperbarui; tekan Scan untuk mencoba lagi.`;
    stopProgressRefresh();
  } finally {
    progressRequestActive = false;
  }
}
function idempotencyKey(prefix = "profile") {
  return (
    globalThis.crypto?.randomUUID?.() ||
    `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}
async function deleteProfile(
  profile: LocalProfile,
  worker = selectedWorker.value,
) {
  if (!worker || !profile.deletable || deletionIsActive(profile.name, worker))
    return;
  if (
    !window.confirm(
      `Hapus seluruh data profil "${profile.name}" dari worker "${worker}"? Bundle Vault tidak ikut dihapus.`,
    )
  )
    return;
  if (selectedWorker.value !== worker) selectWorker(worker);
  failure.value = "";
  notice.value = "";
  try {
    const operation = await api<DeleteOperation>(
      `/workers/${encodeURIComponent(worker)}/profiles/local/${encodeURIComponent(profile.name)}`,
      {
        method: "DELETE",
        headers: { "Idempotency-Key": idempotencyKey("profile-delete") },
      },
    );
    deleteOperations.value = [
      operation,
      ...deleteOperations.value.filter(
        (item) => item.operation_id !== operation.operation_id,
      ),
    ];
    notice.value = `Penghapusan profil ${profile.name} pada worker ${worker} tercatat dan dapat dipantau setelah halaman dibuka ulang.`;
    scheduleProgressRefresh();
  } catch (cause) {
    const error = cause as { code?: string; message?: string };
    if (
      error.code === "PROFILE_NOT_IN_LOCAL_SCAN" &&
      selectedWorker.value === worker &&
      inventory.value?.worker === worker
    ) {
      inventory.value = {
        ...inventory.value,
        items: inventory.value.items.filter(
          (item) => item.name !== profile.name,
        ),
      };
      notice.value = `Profil ${profile.name} tidak ditemukan pada scan terbaru worker ${worker}; entri dihapus dari daftar lokal. Tidak ada file yang dihapus.`;
      return;
    }
    failure.value =
      error.message || `Penghapusan profil ${profile.name} gagal.`;
  }
}
async function adoptProfile(profile: LocalProfile) {
  const worker = selectedWorker.value;
  if (
    !worker ||
    !profile.ready ||
    !vaultStatusLoaded.value ||
    isVaulted(profile.name) ||
    adoptionIsActive(profile.name)
  )
    return;
  if (
    !window.confirm(
      `Adopsi profil "${profile.name}" dari worker "${worker}" ke Vault? Ini hanya menyimpan bundle terenkripsi; sesi worker lain tidak akan diubah.`,
    )
  )
    return;
  adoptingProfiles.value = [...adoptingProfiles.value, profile.name];
  failure.value = "";
  notice.value = "";
  try {
    const operation = await post<{ id: string; status: string }>(
      `/profiles/${encodeURIComponent(profile.name)}/adopt`,
      { worker },
    );
    adoptionOperations.value = {
      ...adoptionOperations.value,
      [profile.name]: { id: operation.id, status: operation.status },
    };
    notice.value = `Adopsi ${profile.name} dimulai dari worker ${worker}. Bundle hanya disimpan di Vault.`;
    await refreshAdoptionOperations();
    scheduleProgressRefresh();
  } catch (cause) {
    const error = cause as { code?: string; message?: string };
    failure.value = error.message || `Adopsi profil ${profile.name} gagal.`;
    if (error.code === "PROFILE_ALREADY_VAULTED")
      await refreshVaultProfiles(worker);
  } finally {
    adoptingProfiles.value = adoptingProfiles.value.filter(
      (name) => name !== profile.name,
    );
  }
}
function identityCleanupLabel(status: unknown) {
  return (
    (
      {
        removed:
          "Mapping identitas dihapus setelah semua worker terverifikasi.",
        local_copy_remaining:
          "Mapping identitas dipertahankan karena masih ada salinan di worker lain.",
        pending_recheck:
          "Mapping identitas dipertahankan; inventaris worker lain menunggu pemeriksaan ulang.",
      } as Record<string, string>
    )[String(status || "")] || ""
  );
}

function setProvisioningWorkers(items: ProvisioningWorker[]) {
  provisioningWorkers.value = Array.isArray(items) ? items : [];
  const available = provisioningWorkers.value.filter(
    (worker) => worker.online && worker.secure,
  );
  if (!available.some((worker) => worker.name === provisioningWorker.value))
    provisioningWorker.value = available[0]?.name || "";
}
async function loadProvisioningWorkers() {
  provisioningLoading.value = true;
  provisioningFailure.value = "";
  try {
    const result = await api<{ workers?: ProvisioningWorker[] }>(
      "/profiles/management",
    );
    setProvisioningWorkers(result.workers || []);
  } catch (cause) {
    provisioningFailure.value =
      cause instanceof Error
        ? cause.message
        : "Worker aman untuk menambah profil belum dapat dimuat.";
  } finally {
    provisioningLoading.value = false;
  }
}
function scheduleProvisioningRefresh(id: string) {
  if (provisioningTimer) clearTimeout(provisioningTimer);
  provisioningTimer = undefined;
  if (
    !provisioningOperation.value ||
    provisioningOperation.value.id !== id ||
    ["active", "failed", "cancelled"].includes(
      provisioningOperation.value.status,
    )
  )
    return;
  provisioningTimer = setTimeout(
    () => void refreshProvisioningOperation(id),
    1500,
  );
}
async function refreshProvisioningOperation(id: string) {
  if (provisioningRequestActive) return;
  provisioningRequestActive = true;
  try {
    const previous = provisioningOperation.value?.status;
    const current = await api<ProvisioningOperation>(
      `/profiles/provisionings/${encodeURIComponent(id)}`,
    );
    if (provisioningOperation.value?.id !== id) return;
    provisioningOperation.value = current;
    provisioningFailure.value = "";
    if (current.status === "active" && previous !== "active") {
      provisioningNotice.value = `Profil ${current.profile} aktif pada worker terpilih; sesi tidak disimpan di Vault.`;
      await sessionActions.refreshProfileCatalog();
      profileName.value = "";
      loginPhone.value = "";
      loginInput.value = "";
      profileArchive.value = null;
    }
  } catch (cause) {
    if (provisioningOperation.value?.id === id)
      provisioningFailure.value =
        cause instanceof Error
          ? cause.message
          : "Status penambahan profil gagal dimuat.";
  } finally {
    provisioningRequestActive = false;
    scheduleProvisioningRefresh(id);
  }
}
async function submitProfileArchive() {
  if (
    !profileArchive.value ||
    !profileName.value.trim() ||
    !provisioningWorker.value ||
    savingProvisioning.value
  )
    return;
  savingProvisioning.value = true;
  provisioningFailure.value = "";
  provisioningNotice.value = "";
  try {
    const query = new URLSearchParams({
      name: profileName.value.trim(),
      worker: provisioningWorker.value,
      local_only: "true",
    });
    const result = await api<{ id: string; status: string }>(
      `/profiles/provisionings/upload?${query}`,
      {
        method: "POST",
        body: profileArchive.value,
        headers: { "content-type": "application/zip" },
      },
    );
    provisioningOperation.value = {
      id: result.id,
      profile: profileName.value.trim(),
      status: result.status,
      source: "upload",
      bootstrap_worker: provisioningWorker.value,
      workers: [],
    };
    provisioningNotice.value = `Sesi valid. Pemasangan dimulai pada worker ${provisioningWorker.value}.`;
    await refreshProvisioningOperation(result.id);
  } catch (cause) {
    provisioningFailure.value =
      cause instanceof Error ? cause.message : "Upload sesi gagal.";
  } finally {
    savingProvisioning.value = false;
  }
}
async function startProfileLogin() {
  if (
    !profileName.value.trim() ||
    !provisioningWorker.value ||
    savingProvisioning.value ||
    (loginMethod.value === "code" && !loginPhone.value.trim())
  )
    return;
  savingProvisioning.value = true;
  provisioningFailure.value = "";
  provisioningNotice.value = "";
  try {
    const result = await post<{ id: string; status: string }>(
      "/profiles/provisionings/login",
      {
        name: profileName.value.trim(),
        worker: provisioningWorker.value,
        method: loginMethod.value,
        phone: loginMethod.value === "code" ? loginPhone.value.trim() : "",
        local_only: true,
      },
    );
    provisioningOperation.value = {
      id: result.id,
      profile: profileName.value.trim(),
      status: result.status,
      source: "login",
      bootstrap_worker: provisioningWorker.value,
      workers: [],
    };
    provisioningNotice.value =
      loginMethod.value === "qr"
        ? "QR sedang disiapkan pada worker."
        : "Menunggu kode verifikasi Telegram.";
    await refreshProvisioningOperation(result.id);
  } catch (cause) {
    provisioningFailure.value =
      cause instanceof Error ? cause.message : "Login TDL gagal dimulai.";
  } finally {
    savingProvisioning.value = false;
  }
}
async function submitLoginInput() {
  if (
    !provisioningOperation.value ||
    !loginInput.value.trim() ||
    savingProvisioning.value
  )
    return;
  const field =
    provisioningOperation.value.login?.step === "password"
      ? "password"
      : "code";
  savingProvisioning.value = true;
  provisioningFailure.value = "";
  try {
    await post(
      `/profiles/provisionings/${encodeURIComponent(provisioningOperation.value.id)}/input`,
      { field, value: loginInput.value },
    );
    loginInput.value = "";
    await refreshProvisioningOperation(provisioningOperation.value.id);
  } catch (cause) {
    provisioningFailure.value =
      cause instanceof Error ? cause.message : "Input login gagal dikirim.";
  } finally {
    savingProvisioning.value = false;
  }
}
async function cancelProfileProvisioning() {
  if (!provisioningOperation.value || savingProvisioning.value) return;
  savingProvisioning.value = true;
  provisioningFailure.value = "";
  try {
    await remove(
      `/profiles/provisionings/${encodeURIComponent(provisioningOperation.value.id)}`,
    );
    if (provisioningTimer) clearTimeout(provisioningTimer);
    provisioningTimer = undefined;
    provisioningOperation.value = null;
    provisioningNotice.value = "Penambahan profil dibatalkan.";
  } catch (cause) {
    provisioningFailure.value =
      cause instanceof Error
        ? cause.message
        : "Penambahan profil tidak dapat dibatalkan.";
  } finally {
    savingProvisioning.value = false;
  }
}

function selectWorkerAction(value: string) {
  stopProgressRefresh();
  selectedWorker.value = value;
  inventory.value =
    profileCatalog.value?.inventories.find((item) => item.worker === value) ||
    null;
  deleteOperations.value = [];
  vaultProfiles.value = [];
  vaultStatusLoaded.value = false;
  vaultStatusFailure.value = "";
  adoptionOperations.value = {};
  adoptingProfiles.value = [];
  failure.value = "";
  notice.value = "";
  if (value && inventory.value) {
    scheduleProgressRefresh();
    const generation = progressGeneration;
    void refreshDeleteOperations(value, generation);
    void refreshVaultProfiles(value, generation);
  }
}
function refreshWorkers() {
  stopProgressRefresh();
  failure.value = "";
  notice.value =
    "Daftar worker diperbarui. Katalog memakai hasil Scan terakhir; tekan Scan untuk memperbaruinya.";
  void loadWorkers();
}
function scanTargetLabel(target?: ProfileScanTarget) {
  if (!target) return "";
  if (target.kind === "worker")
    return `Semua profil dan service/lane · worker ${target.worker}`;
  if (target.kind === "worker_runtime")
    return `${runtimeName(target.runtime)} · worker ${target.worker}`;
  return `${runtimeName(target.runtime)} · profil ${target.profile} · worker ${target.worker}`;
}
function scanRegionLabel(operation: ProfileScanOperation) {
  if (!operation.target) return "Status scan semua worker";
  if (operation.target.kind === "worker")
    return `Status scan ${operation.target.worker}`;
  if (operation.target.kind === "worker_runtime")
    return `Status scan ${operation.target.worker} · ${runtimeName(operation.target.runtime)}`;
  return `Status scan ${operation.target.worker} · ${operation.target.profile}`;
}
async function finishScanOperation(operation: ProfileScanOperation) {
  scanning.value = false;
  stopScanPoll();
  if (operation.id === handledScanOperationId) return;
  handledScanOperationId = operation.id;
  if (operation.target?.kind === "worker") {
    await loadProfileCatalog();
    await sessionActions.refreshProfileCatalog();
    const progress = operation.progress.workers.find(
      (item) => item.name === operation.target?.worker,
    );
    if (operation.status !== "succeeded")
      failure.value = codeMessage(
        operation.error_code || progress?.error_code || "WORKER_SCAN_FAILED",
      );
    notice.value = `Scan worker ${operation.target.worker} selesai: ${progressStatus(progress?.status || "succeeded")}${progress?.error_code ? ` · ${codeMessage(progress.error_code)}` : ""}.`;
    if (selectedWorker.value && inventory.value) {
      const gen = progressGeneration;
      await refreshDeleteOperations(selectedWorker.value, gen);
      await refreshVaultProfiles(selectedWorker.value, gen);
      scheduleProgressRefresh();
    }
    return;
  }
  if (operation.status !== "succeeded") {
    failure.value = codeMessage(operation.error_code || "WORKER_SCAN_FAILED");
    return;
  }
  await loadProfileCatalog();
  await sessionActions.refreshProfileCatalog();
  if (operation.target?.kind === "worker_runtime") {
    const result = runtimeReadinessFor(
      profileCatalog.value?.runtime_readiness ||
        normalizeRuntimeReadiness(undefined),
      null,
      operation.target.worker,
      operation.target.runtime,
    );
    notice.value = `${runtimeName(operation.target.runtime)} pada worker ${operation.target.worker}: ${readinessLabel(result.status)}${result.reason_code ? ` · ${codeMessage(result.reason_code)}` : ""}.`;
    return;
  }
  if (operation.target?.kind === "profile_runtime") {
    const target = operation.target;
    const result = runtimeReadinessFor(
      profileCatalog.value?.runtime_readiness ||
        normalizeRuntimeReadiness(undefined),
      target.profile,
      target.worker,
      target.runtime,
    );
    notice.value = `${runtimeName(target.runtime)} profil ${target.profile} pada worker ${target.worker}: ${readinessLabel(result.status)}${result.reason_code ? ` · ${codeMessage(result.reason_code)}` : ""}.`;
    return;
  }
  inventory.value = selectedWorker.value
    ? profileCatalog.value?.inventories.find(
        (item) => item.worker === selectedWorker.value,
      ) || null
    : null;
  const successful =
      profileCatalog.value?.workers.filter((item) => item.status === "success")
        .length || 0,
    failed =
      profileCatalog.value?.workers.filter((item) => item.status === "failed")
        .length || 0,
    disabled =
      profileCatalog.value?.workers.filter((item) => item.status === "disabled")
        .length || 0;
  notice.value = `Scan selesai: ${successful} worker berhasil, ${failed} gagal, ${disabled} nonaktif.`;
  if (selectedWorker.value && inventory.value) {
    const gen = progressGeneration;
    await refreshDeleteOperations(selectedWorker.value, gen);
    await refreshVaultProfiles(selectedWorker.value, gen);
    scheduleProgressRefresh();
  }
}
async function refreshScanOperation(id?: string) {
  if (scanPollRequestActive) {
    if (
      id &&
      scanOperation.value?.id === id &&
      isScanActive(scanOperation.value)
    )
      scheduleScanPoll(id);
    return;
  }
  scanPollRequestActive = true;
  try {
    const payload = await api<unknown>(
      id
        ? `/profiles/local/scan/${encodeURIComponent(id)}`
        : "/profiles/local/scan",
    );
    const raw = id
      ? payload
      : payload && typeof payload === "object"
        ? (payload as Record<string, unknown>).operation
        : null;
    const operation = normalizeScanOperation(raw);
    if (!operation) return;
    scanOperation.value = operation;
    scanning.value = isScanActive(operation);
    if (scanning.value) scheduleScanPoll(operation.id);
    else if (["succeeded", "failed"].includes(operation.status)) {
      if (workerScanLogDialog.value?.operationId === operation.id)
        void refreshWorkerScanLogs(true);
      await finishScanOperation(operation);
    }
  } catch {
    if (
      id &&
      scanOperation.value?.id === id &&
      isScanActive(scanOperation.value)
    )
      scheduleScanPoll(id);
  } finally {
    scanPollRequestActive = false;
  }
}
async function startScan(path: string, body?: Record<string, string>) {
  if (scanning.value || loadingWorkers.value) return;
  closeWorkerScanLogs();
  stopScanPoll();
  stopProgressRefresh();
  catalogGeneration += 1;
  const generation = progressGeneration;
  scanning.value = true;
  failure.value = "";
  notice.value = "";
  try {
    const payload =
      path === "/profiles/local/scan"
        ? await post<unknown>(path)
        : await post<unknown>(path, body);
    if (generation !== progressGeneration) return;
    catalogFailure.value = "";
    const operation = normalizeScanOperation(payload);
    if (!operation) {
      const legacy = normalizeProfileCatalog(payload);
      profileCatalog.value = legacy;
      await sessionActions.refreshProfileCatalog();
      inventory.value = selectedWorker.value
        ? legacy.inventories.find(
            (item) => item.worker === selectedWorker.value,
          ) || null
        : null;
      const successful = legacy.workers.filter(
          (item) => item.status === "success",
        ).length,
        failed = legacy.workers.filter(
          (item) => item.status === "failed",
        ).length,
        disabled = legacy.workers.filter(
          (item) => item.status === "disabled",
        ).length;
      notice.value = `Scan selesai: ${successful} worker berhasil, ${failed} gagal, ${disabled} nonaktif.`;
      scanning.value = false;
      return;
    }
    scanOperation.value = operation;
    scanning.value = isScanActive(operation);
    if (scanning.value) scheduleScanPoll(operation.id);
    else await finishScanOperation(operation);
  } catch (cause) {
    if (generation !== progressGeneration) return;
    const error = cause as { message?: string };
    failure.value =
      error.message ||
      "Scan profil lokal gagal. Katalog sebelumnya dipertahankan.";
    scanning.value = false;
  }
}
function scanAll() {
  return startScan("/profiles/local/scan");
}
function scanSelectedWorker() {
  if (selectedWorker.value)
    return startScan("/profiles/local/scan/worker", {
      worker: selectedWorker.value,
    });
}
function scanWorkerRuntime(worker: string, runtime: string) {
  return startScan("/profiles/local/scan/runtime", { worker, runtime });
}
function scanProfileRuntime(worker: string, profile: string, runtime: string) {
  return startScan("/profiles/local/scan/service", {
    worker,
    profile,
    runtime,
  });
}
function openRuntimeLog(
  worker: string,
  runtime: string,
  attempt?: RuntimeReadinessAttempt,
  profile?: string,
) {
  runtimeLogDialog.value = { worker, runtime, attempt, profile };
}
function scanWorkerLabel(worker: ScanWorker) {
  return worker.status === "success"
    ? `Berhasil · ${profileCatalog.value?.inventories.find((item) => item.worker === worker.name)?.items.length || 0} profil`
    : worker.status === "disabled"
      ? "Nonaktif · tidak dipindai"
      : `Gagal · ${codeMessage(worker.error_code || "WORKER_SCAN_FAILED")}`;
}
function attemptPhase(attempt?: RuntimeReadinessAttempt) {
  return attempt?.phase
    ? scanPhases[attempt.phase] || attempt.phase
    : "Hasil scan terakhir";
}
function scanProgressStatus(status: string) {
  return (
    (
      {
        queued: "Dalam antrean",
        running: "Berjalan",
        succeeded: "Scan selesai",
        failed: "Scan gagal",
      } as Record<string, string>
    )[status] || status
  );
}
function formatOperationStatus(status: string) {
  return (
    (
      {
        validating: "Memeriksa dan menyimpan bundle terenkripsi ke Vault",
        stored: "Bundle tersimpan di Vault; belum didistribusikan",
        failed: "Adopsi gagal",
        cancelled: "Adopsi dibatalkan",
      } as Record<string, string>
    )[status] || status
  );
}
function deleteStatus(status: string) {
  return (
    (
      {
        queued: "Menunggu diproses",
        running: "Sedang menghapus",
        waiting_worker: "Menunggu worker online",
        succeeded: "Berhasil",
        failed: "Gagal",
        cancelled: "Dibatalkan",
      } as Record<string, string>
    )[status] || status
  );
}
function runtimeMatrix(worker: string, profile?: string) {
  const services = profile
    ? ["export", "download", "upload", "storage", "tts", "quick_mode"]
    : ["resolver", "tts_helper", "rclone_storage", "quick_mode_runtime"];
  return services.map((runtime) => ({
    runtime,
    label: runtimeName(runtime),
    result: profile
      ? profileRuntimeReadiness(worker, profile, runtime)
      : workerRuntimeReadiness(worker, runtime),
    scannable: runtime !== "upload",
  }));
}
function exportReadinessFor(profile: LocalProfile, worker: string) {
  return runtimeReadinessFor(
    profileCatalog.value?.runtime_readiness ||
      normalizeRuntimeReadiness(undefined),
    profile.name,
    worker,
    "export",
  );
}

function onJobFinished() {
  void loadProfileCatalog();
  void sessionActions.refreshProfileCatalog();
}
onMounted(() => {
  mounted = true;
  void loadWorkers();
  void loadProfileCatalog();
  void refreshScanOperation();
  void loadProvisioningWorkers();
  window.addEventListener("tme3:job-finished", onJobFinished);
});
onUnmounted(() => {
  mounted = false;
  window.removeEventListener("tme3:job-finished", onJobFinished);
  stopScanPoll();
  closeWorkerScanLogs();
  stopProgressRefresh();
  if (provisioningTimer) clearTimeout(provisioningTimer);
});
</script>

<template>
  <main class="page-stack profile-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">SESI WORKER</p>
        <h1>Profil lokal</h1>
        <p class="muted">
          Scan satu worker, lihat status runtime dan lane per profil, lalu
          kelola sesi.
        </p>
      </div>
      <div class="heading-actions">
        <RouterLink class="button button-secondary" to="/profiles/vault/"
          >Kelola Vault</RouterLink
        >
      </div>
    </header>
    <div v-if="failure" class="notice notice-error" role="alert">
      {{ failure }}
    </div>
    <p v-if="notice" class="notice notice-success" role="status">
      {{ notice }}
    </p>

    <section class="panel add-profile-panel" aria-label="Tambah profil lokal">
      <header class="panel-heading">
        <div>
          <p class="eyebrow">PENAMBAHAN LOKAL</p>
          <h2>Tambah profil</h2>
        </div>
        <button
          class="button button-secondary button-small"
          type="button"
          :disabled="provisioningLoading"
          @click="loadProvisioningWorkers"
        >
          {{ provisioningLoading ? "Memuat…" : "Muat worker" }}
        </button>
      </header>
      <div class="form-grid">
        <label
          >Worker aman<select
            v-model="provisioningWorker"
            aria-label="Worker untuk menyiapkan sesi"
          >
            <option value="">Pilih worker</option>
            <option
              v-for="worker in availableProvisioningWorkers"
              :key="worker.name"
              :value="worker.name"
            >
              {{ worker.name }}
            </option>
          </select></label
        ><label
          >Nama profil<input
            v-model="profileName"
            aria-label="Nama profil baru"
            autocomplete="off"
            placeholder="mis. profil-baru"
        /></label>
      </div>
      <div class="mode-switch" aria-label="Metode penambahan">
        <button
          type="button"
          :aria-pressed="provisioningMode === 'upload'"
          @click="provisioningMode = 'upload'"
        >
          Upload ZIP</button
        ><button
          type="button"
          :aria-pressed="provisioningMode === 'login'"
          @click="provisioningMode = 'login'"
        >
          Login TDL
        </button>
      </div>
      <div v-if="provisioningMode === 'upload'" class="form-grid">
        <label
          >Arsip sesi<input
            type="file"
            accept=".zip,application/zip"
            aria-label="Arsip sesi profil"
            @change="
              profileArchive =
                ($event.target as HTMLInputElement).files?.[0] || null
            " /></label
        ><button
          class="button button-primary align-end"
          type="button"
          :disabled="
            savingProvisioning ||
            !profileArchive ||
            !profileName.trim() ||
            !provisioningWorker
          "
          @click="submitProfileArchive"
        >
          {{
            savingProvisioning ? "Mengunggah…" : "Validasi dan pasang profil"
          }}
        </button>
      </div>
      <template v-else
        ><div class="mode-switch">
          <button
            type="button"
            :aria-pressed="loginMethod === 'qr'"
            @click="loginMethod = 'qr'"
          >
            QR</button
          ><button
            type="button"
            :aria-pressed="loginMethod === 'code'"
            @click="loginMethod = 'code'"
          >
            Nomor dan kode
          </button>
        </div>
        <div v-if="loginMethod === 'code'" class="form-grid">
          <label
            >Nomor telepon internasional<input
              v-model="loginPhone"
              aria-label="Nomor telepon login TDL"
              placeholder="+62…"
              autocomplete="tel" /></label
          ><button
            class="button button-primary align-end"
            type="button"
            :disabled="
              savingProvisioning ||
              !profileName.trim() ||
              !provisioningWorker ||
              !loginPhone.trim()
            "
            @click="startProfileLogin"
          >
            Mulai login dengan kode
          </button>
        </div>
        <button
          v-else
          class="button button-primary"
          type="button"
          :disabled="
            savingProvisioning || !profileName.trim() || !provisioningWorker
          "
          @click="startProfileLogin"
        >
          Mulai login QR
        </button></template
      >
      <p v-if="provisioningNotice" class="notice notice-success" role="status">
        {{ provisioningNotice }}
      </p>
      <p v-if="provisioningFailure" class="notice notice-error" role="alert">
        {{ provisioningFailure }}
      </p>
      <article
        v-if="provisioningOperation"
        class="provisioning-operation"
        :aria-label="`Penambahan profil ${provisioningOperation.profile}`"
      >
        <div class="operation-heading">
          <div>
            <strong
              >{{ provisioningOperation.profile }} ·
              {{
                provisioningOperation.bootstrap_worker || provisioningWorker
              }}</strong
            >
            <p>{{ formatOperationStatus(provisioningOperation.status) }}</p>
          </div>
          <div class="heading-actions">
            <a
              class="button button-secondary button-small"
              :href="`/api/v1/profiles/provisionings/${encodeURIComponent(provisioningOperation.id)}/logs?limit=500`"
              target="_blank"
              rel="noreferrer"
              >Log JSON</a
            ><button
              class="button button-secondary button-small"
              type="button"
              :disabled="savingProvisioning"
              aria-label="Perbarui status penambahan profil"
              @click="refreshProvisioningOperation(provisioningOperation.id)"
            >
              Perbarui status</button
            ><button
              v-if="
                !['active', 'cancelled'].includes(provisioningOperation.status)
              "
              class="button button-secondary button-small"
              type="button"
              :disabled="savingProvisioning"
              @click="cancelProfileProvisioning"
            >
              Batalkan
            </button>
          </div>
        </div>
        <div
          v-if="
            provisioningOperation.login?.step === 'qr' &&
            provisioningOperation.status === 'authenticating'
          "
          class="qr-login"
        >
          <p>
            Pindai QR dengan Telegram pada perangkat yang ingin ditambahkan.
          </p>
          <pre>{{
            provisioningOperation.login.qr_text || "Menunggu QR dari worker…"
          }}</pre>
        </div>
        <div
          v-if="
            provisioningOperation.login &&
            provisioningOperation.status === 'authenticating' &&
            ['code', 'password'].includes(
              provisioningOperation.login.step || '',
            )
          "
          class="form-grid"
        >
          <label
            >{{
              provisioningOperation.login.step === "password"
                ? "Password 2FA"
                : "Kode Telegram"
            }}<input
              v-model="loginInput"
              :type="
                provisioningOperation.login.step === 'password'
                  ? 'password'
                  : 'text'
              "
              autocomplete="one-time-code" /></label
          ><button
            class="button button-primary align-end"
            type="button"
            :disabled="savingProvisioning || !loginInput.trim()"
            @click="submitLoginInput"
          >
            {{
              provisioningOperation.login.step === "password"
                ? "Kirim password 2FA"
                : "Kirim kode"
            }}
          </button>
        </div>
        <p v-if="provisioningOperation.login?.error" class="failure-code">
          {{ provisioningOperation.login.error }}
        </p>
        <p v-if="provisioningOperation.error" class="failure-code">
          {{ provisioningOperation.error }}
        </p>
        <div v-if="provisioningOperation.workers.length" class="worker-op-list">
          <p
            v-for="target in provisioningOperation.workers"
            :key="target.worker"
          >
            {{ target.worker }} · {{ target.status
            }}<template v-if="target.error"> · {{ target.error }}</template>
          </p>
        </div>
      </article>
    </section>

    <section class="panel scan-panel" aria-label="Profil per worker">
      <header class="panel-heading">
        <div>
          <p class="eyebrow">HASIL SCAN</p>
          <h2>Worker dan layanan</h2>
          <p class="muted">
            Scan worker terpilih menguji profil serta service/lane pada worker
            itu. Scan semua tetap aksi terpisah.
          </p>
        </div>
        <span v-if="checkedAt" class="muted">{{ checkedAt }}</span>
      </header>
      <div class="scan-controls">
        <label
          >Worker untuk rincian<select
            v-model="selectedWorker"
            aria-label="Worker"
            :disabled="loadingWorkers || scanning"
            @change="selectWorkerAction(selectedWorker)"
          >
            <option value="">Pilih worker untuk rincian</option>
            <option
              v-for="worker in workers"
              :key="worker.name"
              :value="worker.name"
            >
              {{ worker.name
              }}{{ worker.enabled ? "" : " · nonaktif untuk job baru" }}
            </option>
          </select></label
        ><button
          class="button button-secondary"
          type="button"
          :disabled="loadingWorkers || scanning"
          aria-label="Muat ulang worker"
          @click="refreshWorkers"
        >
          {{ loadingWorkers ? "Memuat…" : "Muat ulang worker" }}</button
        ><button
          class="button button-secondary"
          type="button"
          :disabled="scanning || loadingWorkers || !selectedWorker"
          @click="scanSelectedWorker"
        >
          {{
            scanning && scanOperation?.target?.kind === "worker"
              ? "Memindai…"
              : "Scan worker terpilih"
          }}</button
        ><button
          class="button button-primary"
          type="button"
          :disabled="scanning || loadingWorkers"
          @click="scanAll"
        >
          {{
            scanning && !scanOperation?.target
              ? "Memindai semua worker…"
              : "Scan semua worker"
          }}
        </button>
      </div>
      <p class="muted scan-explainer">
        Resolver tetap nonaktif. Katalog berubah hanya saat scan dimulai; job
        tetap mengikuti hasil command aktual.
      </p>
      <p v-if="catalogFailure" class="notice notice-error" role="alert">
        {{ catalogFailure }}
      </p>
      <section
        v-if="scanOperation"
        class="scan-progress"
        role="region"
        :aria-label="scanRegionLabel(scanOperation)"
      >
        <div role="status" aria-label="Progress Scan Profil">
        <div class="operation-heading">
          <strong>{{ scanProgressStatus(scanOperation.status) }}</strong
          ><span class="muted"
            ><template v-if="scanOperation.progress.total_profiles"
              >Profil {{ scanOperation.progress.completed_profiles }}/{{
                scanOperation.progress.total_profiles
              }}
              · </template
            >Worker {{ scanOperation.progress.completed_workers }}/{{
              scanOperation.progress.total_workers
            }}</span
          >
        </div>
        <p v-if="scanOperation.target" class="muted">
          {{ scanTargetLabel(scanOperation.target) }}
        </p>
        <p v-if="scanOperation.error_code" class="failure-code">
          {{ codeMessage(scanOperation.error_code) }}
        </p>
        <div class="scan-worker-grid">
          <article
            v-for="progressWorker in displayedProgressWorkers"
            :key="progressWorker.name"
            class="progress-worker"
            :aria-label="`Progress worker ${progressWorker.name}`"
          >
            <div class="operation-heading">
              <strong>{{ progressWorker.name }}</strong>
              <div class="heading-actions">
                <span
                  class="status-pill"
                  :class="
                    progressWorker.status === 'failed'
                      ? 'status-failed'
                      : progressWorker.status === 'succeeded'
                        ? 'status-ready'
                        : 'status-running'
                  "
                  >{{ progressStatus(progressWorker.status) }}</span
                ><button
                  class="button button-secondary button-small"
                  type="button"
                  :aria-label="`Buka log realtime worker ${progressWorker.name}`"
                  @click="
                    openWorkerScanLogs(scanOperation, progressWorker.name)
                  "
                >
                  Log mentah
                </button>
              </div>
            </div>
            <p v-if="progressWorker.phase" class="muted">
              {{ scanPhases[progressWorker.phase] || progressWorker.phase }}
            </p>
            <p v-if="progressWorker.error_code" class="failure-code">
              {{ codeMessage(progressWorker.error_code) }}
            </p>
            <p
              v-if="
                progressWorker.runtime &&
                progressWorker.checks?.[progressWorker.runtime]
              "
              class="muted"
            >
              {{ runtimeName(progressWorker.runtime) }}:
              {{
                progressWorker.checks[progressWorker.runtime].ready
                  ? "Siap"
                  : codeMessage(
                      progressWorker.checks[progressWorker.runtime]
                        .reason_code || "RUNTIME_NOT_SCANNED",
                    )
              }}
            </p>
            <div
              v-for="profile in progressWorker.profiles"
              :key="`${progressWorker.name}:${profile.name}`"
              class="progress-profile"
            >
              <strong>{{ profile.name }}</strong
              ><span
                >{{ progressStatus(profile.status)
                }}<template v-if="profile.phase">
                  · {{ scanPhases[profile.phase] || profile.phase }}</template
                ></span
              ><small v-if="profile.error_code" class="failure-code">{{
                codeMessage(profile.error_code)
              }}</small
              ><small v-for="(check, name) in profile.checks" :key="name"
                >{{ runtimeName(String(name)) }} ·
                {{
                  check.ready ? "Siap" : codeMessage(check.reason_code)
                }}</small
              ><small
                v-if="
                  profile.cleanup && profile.cleanup.status !== 'not_needed'
                "
                >Cleanup canary ·
                {{ cleanupLabel(profile.cleanup.status) }}</small
              >
            </div>
          </article>
        </div>
        </div>
      </section>
      <p v-else-if="!profileCatalog" class="empty-state" role="status">
        Belum ada katalog hasil scan tersimpan.
      </p>
      <p v-if="profileCatalog" class="scan-summary">
        {{ profileCatalog.workers.length }} worker di katalog ·
        {{
          profileCatalog.workers.filter((item) => item.status === "success")
            .length
        }}
        berhasil ·
        {{
          profileCatalog.workers.filter((item) => item.status === "failed")
            .length
        }}
        gagal ·
        {{
          profileCatalog.workers.filter((item) => item.status === "disabled")
            .length
        }}
        nonaktif
      </p>
      <section
        v-if="profileCatalog"
        class="readiness-hierarchy"
        aria-label="Kesiapan per worker dan profil"
      >
        <div class="operation-heading">
          <h3>Kesiapan layanan per worker dan profil</h3>
          <span class="muted">Worker → profil</span>
        </div>
        <article
          v-for="workerResult in profileCatalog.workers"
          :key="workerResult.name"
          class="worker-card"
          :aria-label="`Worker ${workerResult.name}`"
        >
          <div class="operation-heading">
            <strong>Worker {{ workerResult.name }}</strong>{{ " " }}
            <span
              class="status-pill"
              :class="
                workerResult.status === 'success'
                  ? 'status-ready'
                  : workerResult.status === 'failed'
                    ? 'status-failed'
                    : 'status-neutral'
              "
              >{{ workerStatusLabel(workerResult) }}</span
            >
          </div>
          <div class="readiness-grid">
            <div
              v-for="service in runtimeMatrix(workerResult.name)"
              :key="service.runtime"
              class="readiness-cell"
              role="group"
              :aria-label="`Kesiapan ${service.label} pada ${workerResult.name}`"
            >
              <div class="operation-heading">
                <strong>{{ service.label }}</strong>{{ " " }}
                <span
                  class="status-pill"
                  :class="readinessClass(service.result.status)"
                  role="status"
                  :aria-label="`${service.label}: ${readinessLabel(service.result.status)}`"
                  >{{ readinessLabel(service.result.status) }}</span
                >
              </div>
              <p
                v-if="
                  service.result.reason_code &&
                  service.result.status !== 'ready'
                "
                class="muted"
              >
                {{ codeMessage(service.result.reason_code) }}
              </p>
              <div class="cell-actions">
                <button
                  class="icon-button"
                  type="button"
                  :disabled="
                    scanning ||
                    loadingWorkers ||
                    workers.find((item) => item.name === workerResult.name)
                      ?.enabled === false
                  "
                  :aria-label="`Scan ${service.label} worker ${workerResult.name}`"
                  @click="scanWorkerRuntime(workerResult.name, service.runtime)"
                >
                  ↻</button
                ><button
                  class="icon-button"
                  type="button"
                  :aria-label="`Lihat log uji ${service.label} worker ${workerResult.name}`"
                  @click="
                    openRuntimeLog(
                      workerResult.name,
                      service.runtime,
                      service.result.last_attempt,
                    )
                  "
                >
                  !
                </button>
              </div>
            </div>
          </div>
          <div
            v-if="
              profileCatalog.inventories.find(
                (item) => item.worker === workerResult.name,
              )
            "
            class="profile-matrix"
          >
            <section
              v-for="profile in profileCatalog.inventories.find(
                (item) => item.worker === workerResult.name,
              )?.items || []"
              :key="`${workerResult.name}:${profile.name}`"
              class="profile-matrix-card"
              :aria-label="`Profil ${profile.name} pada worker ${workerResult.name}`"
            >
              <div class="operation-heading">
                <strong>Profil {{ profile.name }}</strong>{{ " " }}
                <span
                  class="status-pill"
                  :class="profile.ready ? 'status-ready' : 'status-failed'"
                  >{{
                    profile.ready ? "Sesi tersedia" : "Sesi perlu diperiksa"
                  }}</span
                ><button
                  v-if="profile.deletable"
                  class="button button-danger button-small"
                  type="button"
                  :disabled="deletionIsActive(profile.name, workerResult.name)"
                  :aria-label="`Hapus profil ${profile.name} dari ${workerResult.name}`"
                  @click="deleteProfile(profile, workerResult.name)"
                >
                  {{
                    deletionIsActive(profile.name, workerResult.name)
                      ? "Menghapus…"
                      : "Hapus profil"
                  }}
                </button>
              </div>
              <div class="readiness-grid profile-services">
                <div
                  v-for="service in runtimeMatrix(
                    workerResult.name,
                    profile.name,
                  )"
                  :key="service.runtime"
                  class="readiness-cell"
                  role="group"
                  :aria-label="`Kesiapan ${service.label} ${profile.name} pada ${workerResult.name}`"
                >
                  <div class="operation-heading">
                    <strong>{{ service.label }}</strong>{{ " " }}
                    <span
                      class="status-pill"
                      :class="readinessClass(service.result.status)"
                      role="status"
                      :aria-label="`${service.label} ${profile.name}: ${readinessLabel(service.result.status)}`"
                      >{{ readinessLabel(service.result.status) }}</span
                    >
                  </div>
                  <p
                    v-if="
                      service.result.reason_code &&
                      service.result.status !== 'ready'
                    "
                    class="muted"
                  >
                    {{ codeMessage(service.result.reason_code) }}
                  </p>
                  <div class="cell-actions">
                    <button
                      v-if="service.scannable"
                      class="icon-button"
                      type="button"
                      :disabled="
                        scanning ||
                        loadingWorkers ||
                        workers.find((item) => item.name === workerResult.name)
                          ?.enabled === false
                      "
                      :aria-label="`Scan ${service.label} profil ${profile.name} worker ${workerResult.name}`"
                      @click="
                        scanProfileRuntime(
                          workerResult.name,
                          profile.name,
                          service.runtime,
                        )
                      "
                    >
                      ↻</button
                    ><button
                      class="icon-button"
                      type="button"
                      :aria-label="`Lihat log uji ${service.label} profil ${profile.name} worker ${workerResult.name}`"
                      @click="
                        openRuntimeLog(
                          workerResult.name,
                          service.runtime,
                          service.result.last_attempt,
                          profile.name,
                        )
                      "
                    >
                      !
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </div>
          <p v-else-if="workerResult.status === 'success'" class="muted">
            Worker ini belum mengembalikan profil lokal.
          </p>
        </article>
      </section>
      <p v-if="notice" class="notice notice-success" role="status">
        {{ notice }}
      </p>
      <p v-if="vaultStatusFailure" class="muted" role="status">
        Status Vault gagal dimuat; adopsi dinonaktifkan.
      </p>
      <div
        v-if="inventory?.pending_identity_cleanup?.length"
        class="notice notice-warning"
        role="status"
      >
        <p
          v-for="item in inventory.pending_identity_cleanup"
          :key="item.profile"
        >
          Mapping identitas profil {{ item.profile }} menunggu pemeriksaan ulang
          setelah penghapusan pada {{ item.deleted_worker }}.
        </p>
      </div>
    </section>

    <section
      v-if="selectedInventory"
      class="panel inventory-panel"
      aria-label="Hasil scan profil lokal"
    >
      <header class="panel-heading">
        <div>
          <p class="eyebrow">{{ inventory?.worker }}</p>
          <h2>Profil lokal</h2>
          <p class="muted">Diperiksa {{ formatDate(inventory?.checked_at) }}</p>
        </div>
        <span class="count-badge"
          >{{ inventory?.items.length || 0 }} profil</span
        >
      </header>
      <div v-if="!inventory?.items.length" class="empty-state">
        Worker ini tidak memiliki profil lokal yang ditemukan.
      </div>
      <div v-else class="inventory-list">
        <article
          v-for="profile in inventory?.items"
          :key="profile.name"
          class="inventory-profile"
        >
          <div class="operation-heading">
            <h3>{{ profile.name }}</h3>
            <div class="heading-actions">
              <span
                class="status-pill"
                :class="profile.ready ? 'status-ready' : 'status-failed'"
                >{{ profile.ready ? "Sesi tersedia" : "Perlu diperiksa" }}</span
              ><span
                v-if="isVaulted(profile.name)"
                class="status-pill status-neutral"
                >Sudah di Vault</span
              ><button
                v-else-if="profile.ready && vaultStatusLoaded"
                class="button button-secondary button-small"
                type="button"
                :disabled="adoptionIsActive(profile.name)"
                :aria-label="`Adopsi profil ${profile.name} dari ${selectedWorker} ke Vault`"
                @click="adoptProfile(profile)"
              >
                {{
                  adoptionIsActive(profile.name)
                    ? "Menyimpan…"
                    : "Adopsi ke Vault"
                }}</button
            </div>
          </div>
          <div class="diagnostic-grid">
            <article v-for="check in profile.checks" :key="check.name">
              <strong
                >{{ check.name.replaceAll("_", " ") }} ·
                {{ check.ready ? "Siap" : "Gagal" }}</strong
              ><span v-if="!check.ready">{{ codeMessage(check.code) }}</span>
            </article>
          </div>
          <p v-if="profile.reason_codes.length" class="failure-code">
            Kode: {{ profile.reason_codes.join(", ") }}
          </p>
          <section
            class="readiness-cell export-readiness"
            role="status"
            :aria-label="`Kesiapan Export ${profile.name} pada ${inventory?.worker || selectedWorker}`"
          >
            <div class="operation-heading">
              <strong
                >Kesiapan runtime Export ·
                {{ readinessLabel(exportReadinessFor(profile, inventory?.worker || selectedWorker).status) }}</strong
              >
              <time
                v-if="exportReadinessFor(profile, inventory?.worker || selectedWorker).checked_at"
                class="muted"
                :datetime="exportReadinessFor(profile, inventory?.worker || selectedWorker).checked_at"
                >{{ formatDate(exportReadinessFor(profile, inventory?.worker || selectedWorker).checked_at) }}</time
              >
            </div>
            <p v-if="exportReadinessFor(profile, inventory?.worker || selectedWorker).status === 'ready'" class="muted">
              Sesi TDL pada worker ini lolos scan terakhir. Export dapat dikirim tanpa verifikasi ulang.
            </p>
            <p v-else class="muted">
              Belum ada hasil command aktual untuk akses ini. Job tetap dapat dijalankan.
            </p>
          </section>
          <div
            class="upload-lane"
            role="region"
            :aria-label="`Lane Upload ${profile.name}`"
          >
            <div class="operation-heading">
              <strong>Lane Upload</strong>{{ " " }}
              <span>{{
                profile.upload_lane?.status === "running"
                  ? "Berjalan"
                  : profile.upload_lane?.status === "ready"
                    ? "Siap"
                    : profile.upload_lane?.status === "failed"
                      ? "Gagal"
                      : "Belum diperiksa"
              }}</span>
            </div>
            <p class="muted">
              {{ profile.upload_lane?.phase || "Belum ada progres"
              }}<template v-if="profile.upload_lane?.code">
                · {{ profile.upload_lane.code }}</template
              >
            </p>
            <progress
              v-if="profile.upload_lane?.status === 'running'"
              :value="profile.upload_lane.progress"
              max="100"
            ></progress>
          </div>
        </article>
      </div>
    </section>

    <section
      v-if="selectedWorker && localDeleteOps.length"
      class="panel delete-operations"
      aria-label="Operasi penghapusan profil"
    >
      <h2>Operasi penghapusan · {{ selectedWorker }}</h2>
      <article
        v-for="operation in localDeleteOps"
        :key="operation.operation_id"
        class="delete-op"
      >
        <div class="operation-heading">
          <strong>{{ operation.target.profile }}</strong
          ><span
            class="status-pill"
            :class="
              operation.status === 'failed'
                ? 'status-failed'
                : operation.status === 'succeeded'
                  ? 'status-ready'
                  : 'status-running'
            "
            >{{ deleteStatus(operation.status) }}</span
          >
        </div>
        <p v-if="operation.status === 'failed'" class="failure-code">
          {{
            codeMessage(
              String(
                operation.progress?.reason_code ||
                  operation.error?.code ||
                  "PROFILE_DELETE_FAILED",
              ),
            )
          }}
        </p>
        <p
          v-if="
            identityCleanupLabel(operation.progress?.identity_mapping_status)
          "
          class="muted"
        >
          {{
            identityCleanupLabel(operation.progress?.identity_mapping_status)
          }}
        </p>
      </article>
    </section>

    <div
      v-if="runtimeLogDialog"
      class="modal-backdrop"
      @click.self="runtimeLogDialog = null"
    >
      <section
        class="modal-card"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        :aria-label="runtimeLogTitle(runtimeLogDialog)"
      >
        <header class="modal-heading">
          <div>
            <p class="eyebrow">LOG UJI TERAKHIR</p>
            <h2>
              {{ runtimeName(runtimeLogDialog.runtime)
              }}<template v-if="runtimeLogDialog.profile">
                · {{ runtimeLogDialog.profile }}</template
              >
              · {{ runtimeLogDialog.worker }}
            </h2>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="Tutup log uji"
            @click="runtimeLogDialog = null"
          >
            ×
          </button>
        </header>
        <div v-if="runtimeLogDialog.attempt" class="modal-body">
          <p class="muted">
            {{ formatDate(runtimeLogDialog.attempt.checked_at) }} ·
            {{ attemptPhase(runtimeLogDialog.attempt) }}
          </p>
          <p>
            <span
              class="status-pill"
              :class="
                runtimeLogDialog.attempt.status === 'ready'
                  ? 'status-ready'
                  : 'status-failed'
              "
              >{{ readinessLabel(runtimeLogDialog.attempt.status) }}</span
            ><span
              v-if="runtimeLogDialog.attempt.reason_code"
              class="failure-code"
            >
              · {{ codeMessage(runtimeLogDialog.attempt.reason_code) }}</span
            >
          </p>
          <h3>Dependency</h3>
          <p>
            {{
              runtimeLogDialog.attempt.dependencies.join(", ") ||
              "Tidak ada dependency tambahan."
            }}
          </p>
          <h3>Hasil pemeriksaan</h3>
          <ul>
            <li
              v-for="check in runtimeLogDialog.attempt.checks"
              :key="check.name"
            >
              {{ runtimeName(check.name) }} · {{ readinessLabel(check.status)
              }}<template v-if="check.reason_code">
                · {{ codeMessage(check.reason_code) }}</template
              >
            </li>
          </ul>
          <h3>Cleanup</h3>
          <p>
            {{ cleanupLabel(runtimeLogDialog.attempt.cleanup.status)
            }}<template v-if="runtimeLogDialog.attempt.cleanup.reason_code">
              ·
              {{
                codeMessage(runtimeLogDialog.attempt.cleanup.reason_code)
              }}</template
            >
          </p>
        </div>
        <div v-else class="empty-state">
          Belum ada hasil scan untuk sel ini.
        </div>
        <footer class="modal-actions">
          <button
            class="button button-secondary"
            type="button"
            @click="runtimeLogDialog = null"
          >
            Tutup
          </button>
        </footer>
      </section>
    </div>

    <div
      v-if="workerScanLogDialog"
      class="modal-backdrop"
      @click.self="closeWorkerScanLogs"
    >
      <section
        class="modal-card scan-log-modal"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        :aria-label="`Worker ${workerScanLogDialog.worker}`"
      >
        <header class="modal-heading">
          <div>
            <p class="eyebrow">LOG SCAN REALTIME</p>
            <h2 id="worker-scan-log-title">
              Worker {{ workerScanLogDialog.worker }}
            </h2>
            <p class="muted">
              Operasi {{ workerScanLogDialog.operationId
              }}<template v-if="scanActive"> · Log diperbarui realtime</template
              ><template v-else> · Log tersimpan</template>
            </p>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="Tutup log worker"
            @click="closeWorkerScanLogs"
          >
            ×
          </button>
        </header>
        <p v-if="workerScanLogFailure" class="notice notice-error" role="alert">
          {{ workerScanLogFailure }}
        </p>
        <div class="raw-log-body">
          <p v-if="workerScanLogLoading" class="muted">Memuat log…</p>
          <pre
            v-for="event in workerScanLogEvents"
            :key="event.sequence"
            :class="`log-${event.stream}`"
          ><small>#{{ event.sequence }} · {{ event.profile||'worker' }} · {{ runtimeName(event.runtime)||'sistem' }} · {{ event.kind }} · {{ formatDate(event.created_at) }}</small>{{ event.text }}<template v-if="event.exit_code!==null"> · exit {{ event.exit_code }}</template></pre>
          <p
            v-if="!workerScanLogEvents.length && !workerScanLogLoading"
            class="empty-state"
          >
            Belum ada log.
          </p>
        </div>
        <footer class="modal-actions">
          <button
            class="button button-secondary"
            type="button"
            :disabled="workerScanLogLoading"
            @click="refreshWorkerScanLogs(true)"
          >
            Refresh log</button
          ><button class="button" type="button" @click="closeWorkerScanLogs">
            Tutup
          </button>
        </footer>
      </section>
    </div>
  </main>
</template>

<style scoped>
.profile-page > .notice {
  margin: 0;
}
.panel {
  padding: 1rem;
}
.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.8rem;
  border-bottom: 1px solid var(--line);
}
.panel-heading h2 {
  margin: 0.2rem 0;
  font-size: 1rem;
}
.panel-heading p {
  margin: 0.25rem 0 0;
}
.eyebrow {
  margin: 0;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
  gap: 0.7rem;
  margin-top: 0.8rem;
}
.form-grid label,
.scan-controls label {
  display: grid;
  gap: 0.3rem;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
}
.form-grid input,
.form-grid select,
.scan-controls select {
  width: 100%;
  padding: 0.58rem 0.65rem;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: var(--panel);
  color: var(--ink);
}
.align-end {
  align-self: end;
  justify-self: start;
}
.mode-switch {
  display: flex;
  gap: 0.4rem;
  margin-top: 0.75rem;
}
.mode-switch button {
  padding: 0.42rem 0.7rem;
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  color: var(--muted);
  font-size: 0.75rem;
}
.mode-switch button[aria-pressed="true"] {
  background: var(--panel-soft);
  color: var(--ink);
}
.provisioning-operation,
.scan-progress,
.worker-card,
.profile-matrix-card,
.inventory-profile,
.delete-op {
  display: grid;
  gap: 0.55rem;
  padding: 0.75rem;
  border: 1px solid var(--line);
  border-radius: 0.7rem;
  background: var(--panel-soft);
}
.provisioning-operation {
  margin-top: 0.8rem;
}
.operation-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.operation-heading h3,
.operation-heading h2 {
  margin: 0;
  font-size: 0.88rem;
}
.operation-heading p {
  margin: 0.2rem 0 0;
  font-size: 0.72rem;
}
.heading-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.scan-controls {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-top: 0.8rem;
}
.scan-controls label {
  min-width: min(100%, 16rem);
  flex: 1;
}
.scan-explainer,
.scan-summary {
  margin: 0.55rem 0 0;
  font-size: 0.7rem;
}
.scan-progress {
  margin-top: 0.8rem;
}
.scan-worker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
  gap: 0.55rem;
  margin-top: 0.5rem;
}
.progress-worker {
  display: grid;
  gap: 0.35rem;
  padding: 0.65rem;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: var(--panel);
}
.progress-profile {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.2rem 0.4rem;
  padding: 0.45rem;
  border-left: 2px solid var(--line);
  font-size: 0.7rem;
}
.progress-profile small {
  grid-column: 1/-1;
}
.readiness-hierarchy {
  display: grid;
  gap: 0.65rem;
  margin-top: 1rem;
}
.readiness-hierarchy > .operation-heading h3 {
  margin: 0;
  font-size: 0.88rem;
}
.worker-card {
  background: var(--panel-soft);
}
.readiness-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 13rem), 1fr));
  gap: 0.45rem;
}
.readiness-cell {
  position: relative;
  display: grid;
  gap: 0.3rem;
  min-height: 4.2rem;
  padding: 0.55rem;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: var(--panel);
}
.readiness-cell strong {
  font-size: 0.7rem;
}
.readiness-cell p {
  margin: 0;
  font-size: 0.66rem;
}
.cell-actions {
  position: absolute;
  right: 0.38rem;
  bottom: 0.35rem;
  display: flex;
  gap: 0.15rem;
}
.cell-actions .icon-button {
  width: 1.55rem;
  height: 1.55rem;
  font-size: 0.8rem;
}
.readiness-cell {
  padding-bottom: 2rem;
}
.profile-matrix {
  display: grid;
  gap: 0.5rem;
  margin-top: 0.5rem;
  padding-left: 0.65rem;
  border-left: 2px solid var(--line);
}
.profile-matrix-card {
  background: var(--panel);
}
.profile-services {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
  margin-top: 0.25rem;
}
.inventory-panel {
  margin-top: 0.8rem;
}
.inventory-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 23rem), 1fr));
  gap: 0.6rem;
  margin-top: 0.8rem;
}
.inventory-profile {
  background: var(--panel-soft);
}
.inventory-profile h3 {
  margin: 0;
  font-size: 0.9rem;
}
.diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr));
  gap: 0.35rem;
}
.diagnostic-grid article {
  display: grid;
  gap: 0.2rem;
  padding: 0.45rem;
  border-radius: 0.45rem;
  background: var(--panel);
  font-size: 0.68rem;
}
.diagnostic-grid article span,
.failure-code {
  color: var(--danger);
  font-size: 0.68rem;
}
.upload-lane {
  padding: 0.6rem;
  border: 1px solid var(--line);
  border-radius: 0.55rem;
  background: var(--panel);
}
.upload-lane p {
  margin: 0.3rem 0 0;
  font-size: 0.68rem;
}
.upload-lane progress {
  width: 100%;
  height: 0.35rem;
}
.delete-operations h2 {
  margin: 0 0 0.7rem;
  font-size: 0.9rem;
}
.delete-operations {
  margin-top: 0.8rem;
}
.delete-op + .delete-op {
  margin-top: 0.4rem;
}
.qr-login {
  display: grid;
  gap: 0.4rem;
  margin-top: 0.7rem;
}
.qr-login p {
  margin: 0;
  font-size: 0.75rem;
}
.qr-login pre {
  max-height: 18rem;
  overflow: auto;
  padding: 0.75rem;
  background: #070d18;
  border-radius: 0.6rem;
  color: #fff;
  font:
    9px/0.9 ui-monospace,
    monospace;
  white-space: pre;
}
.worker-op-list {
  display: grid;
  gap: 0.3rem;
}
.worker-op-list p {
  margin: 0;
  padding: 0.45rem;
  border: 1px solid var(--line);
  border-radius: 0.45rem;
  font-size: 0.7rem;
}
.notice {
  margin: 0.6rem 0;
  padding: 0.6rem 0.75rem;
  border-radius: 0.55rem;
  font-size: 0.75rem;
}
.notice-error {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 9%, var(--panel));
}
.notice-success {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 9%, var(--panel));
}
.notice-warning {
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 9%, var(--panel));
}
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgba(3, 8, 18, 0.72);
  backdrop-filter: blur(4px);
}
.modal-card {
  display: flex;
  flex-direction: column;
  max-height: 88dvh;
  width: min(52rem, 100%);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 0.9rem;
  background: var(--panel);
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.4);
}
.modal-heading {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--line);
}
.modal-heading h2 {
  margin: 0.2rem 0;
  font-size: 1rem;
}
.modal-heading p {
  margin: 0.2rem 0;
}
.modal-body {
  overflow: auto;
  padding: 1rem;
  font-size: 0.78rem;
}
.modal-body h3 {
  margin: 0.8rem 0 0.25rem;
  font-size: 0.78rem;
}
.modal-body ul {
  display: grid;
  gap: 0.2rem;
  margin: 0;
  padding-left: 1.2rem;
  font-size: 0.72rem;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.45rem;
  padding: 0.65rem 0.85rem;
  border-top: 1px solid var(--line);
}
.scan-log-modal {
  width: min(64rem, 100%);
}
.raw-log-body {
  min-height: 12rem;
  overflow: auto;
  padding: 0.75rem;
  background: #07101b;
  color: #d9fbe7;
}
.raw-log-body pre {
  margin: 0;
  padding: 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font:
    0.68rem/1.5 ui-monospace,
    monospace;
}
.raw-log-body pre small {
  display: block;
  color: #8ca0b5;
}
.log-stderr,
.log-error {
  color: #ffabb6;
}
.log-system {
  color: #8bd9ff;
}
.status-pill {
  white-space: nowrap;
}
.empty-state {
  padding: 1.4rem;
  text-align: center;
  color: var(--muted);
}
</style>
