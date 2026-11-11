<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api, patch, post } from "../lib/api";
import { formatBytes, formatDate } from "../../../src/lib/presentation";
import { session, sessionActions } from "../session";
import WorkspaceExplorer from "../components/WorkspaceExplorer.vue";
import JobMonitor from "../components/JobMonitor.vue";

type Folder = { id: number; parent_id: number | null; name: string; path: string; file_count?: number; folder_count?: number; size_bytes?: number; size_complete?: boolean; status?: string };
type StorageItem = { id: number; display_name: string; original_name: string; folder?: string; folder_id?: number | null; keywords?: string; file_size?: number; mime_type?: string; owner_profile?: string; uploaded_at?: string; status?: string; caption_sync_status?: string; recovered_at?: string | null; recovered_from_profile?: string | null };
type Browser = { current_folder: Folder | null; breadcrumbs: { id: number; name: string }[]; folders: Folder[]; items: StorageItem[]; total_folders: number; total_items: number };
type RemoteEntry = { id?: string; ambiguous?: boolean; name: string; path: string; is_dir: boolean; size: number | null; updated_at: string; file_count?: number; folder_count?: number; size_bytes?: number; size_complete?: boolean };
type Remote = { path: string; breadcrumbs: string[]; items: RemoteEntry[]; total: number; limit: number; offset: number; trash_supported?: boolean; permanent_delete_supported?: boolean };
type PublicLink = { id: string; worker: string; relative_path: string; file_name: string; provider: string; job_id: string; created_at: string; url: string };
type ReadinessProfile = { profile: string; ready: boolean; error_code?: string };
type ScanOperation = { operation_id: string; status: string; phase: string; progress?: Record<string, unknown>; error?: { message?: string } | null };
type ReadinessCell = { worker: string; profile: string | null; runtime: string; status: string; reason_code?: string; checked_at?: string };

const provider = ref<"telegram" | "rclone">("telegram");
const workers = ref<{ name: string; enabled?: boolean; public_url?: string }[]>([]);
const worker = ref("");
const scope = ref<"current" | "global" | "recent" | "trash">("current");
const folderId = ref<number | null>(null);
const query = ref("");
const sort = ref("name");
const order = ref("asc");
const view = ref<"list" | "grid">("list");
const browser = ref<Browser>({ current_folder: null, breadcrumbs: [], folders: [], items: [], total_folders: 0, total_items: 0 });
const folderTree = ref<Folder[]>([]);
const remote = ref<Remote>({ path: "", breadcrumbs: [], items: [], total: 0, limit: 100, offset: 0 });
const remotePath = ref("");
const remoteTarget = ref("");
const remoteTargetSelected = ref(false);
const remoteQuery = ref("");
const remoteSort = ref("name");
const remoteOrder = ref("asc");
const remoteOffset = ref(0);
const remoteView = ref<"active" | "trash">("active");
const summaries = ref<Record<string, { file_count: number; folder_count: number; size_bytes: number; size_complete: boolean }>>({});
const summaryLoading = ref(false);
const summaryFailed = ref(false);
const selectedItems = ref<number[]>([]);
const selectedFolders = ref<number[]>([]);
const selectedRemote = ref<RemoteEntry[]>([]);
const publicLinks = ref<PublicLink[]>([]);
const syncProfiles = computed(() => session.current.profiles || []);
const syncProfile = ref("");
const scanProfiles = ref<ReadinessProfile[]>([]);
const scanStatus = ref("idle");
const scanMessage = ref("");
const scanError = ref("");
const scanOperationId = ref("");
const readinessCells = ref<ReadinessCell[]>([]);
const syncJobId = ref("");
const downloadJobWorkers = ref<Record<string, string>>({});
const detailPanel = ref<HTMLElement | null>(null);
const detailCloseButton = ref<HTMLButtonElement | null>(null);
const detailTrigger = ref<HTMLElement | null>(null);
const message = ref("");
const error = ref("");
const loading = ref(false);
const remoteLoading = ref(false);
const uploadOpen = ref(false);
const downloadOpen = ref(false);
const createOpen = ref(false);
const moveOpen = ref(false);
const renameItem = ref<StorageItem | null>(null);
const renameFolder = ref<Folder | null>(null);
const renameRemote = ref<RemoteEntry | null>(null);
const detailItem = ref<StorageItem | null>(null);
const confirmTrash = ref<"trash" | "purge" | null>(null);
const manageRemote = ref<"copy" | "move" | "trash" | "restore" | "purge" | null>(null);
const revokeLink = ref<PublicLink | null>(null);
const workspaceFolders = ref<string[]>([]);
const downloadDestination = ref<string[]>([]);
const downloadProfile = ref("");
const publishLinks = ref(false);
const transferMode = ref<"copy" | "move">("copy");
const moveConfirmed = ref(false);
const keywords = ref("");
const newName = ref("");
const editKeywords = ref("");
const purgeText = ref("");
const moveAccepted = ref(false);
const destinationId = ref<number | null>(null);
const downloadBusy = ref(false);
const saving = ref(false);
const linksLoading = ref(false);
const remoteManageBusy = ref(false);
const scanBusy = computed(() => ["queued", "running"].includes(scanStatus.value));
const activeSelectionCount = computed(() => provider.value === "telegram" ? selectedItems.value.length + selectedFolders.value.length : selectedRemote.value.length);
const enabledWorker = computed(() => workers.value.some((item) => item.name === worker.value && item.enabled !== false));
const isTrash = computed(() => scope.value === "trash");
const currentFolderName = computed(() => browser.value.current_folder?.name || (scope.value === "trash" ? "Recycle Bin" : scope.value === "recent" ? "Recent" : scope.value === "global" ? "All Files" : "My Drive"));
const workerStorageCells = computed(() => readinessCells.value.filter((cell) => cell.worker === worker.value && cell.runtime === "storage"));
const storageReadinessLabel = computed(() => !enabledWorker.value ? "Worker nonaktif" : workerStorageCells.value.some((cell) => cell.status === "ready") ? "Storage siap" : workerStorageCells.value.some((cell) => cell.status === "not_ready" || cell.status === "offline") ? "Storage belum siap" : "Belum di-scan");

let listGeneration = 0;
let remoteGeneration = 0;
let summaryGeneration = 0;
let scanTimer: ReturnType<typeof setTimeout> | undefined;
let jobFinishedHandler: ((event: Event) => void) | undefined;

function clearTelegramSelection() { selectedItems.value = []; selectedFolders.value = []; }
function clearRemoteSelection() { selectedRemote.value = []; }
function persistLocation() {
  const params = new URLSearchParams(location.search);
  if (scope.value === "current" && folderId.value !== null) params.set("folder", String(folderId.value));
  else params.delete("folder");
  history.replaceState({}, "", `${location.pathname}${params.size ? `?${params}` : ""}`);
}

async function loadTelegram() {
  const request = ++listGeneration;
  loading.value = true;
  error.value = "";
  const params = new URLSearchParams({ folder_id: folderId.value === null ? "root" : String(folderId.value), scope: scope.value, q: query.value, sort: sort.value, order: order.value, limit: "100", offset: "0" });
  try {
    const [result, tree] = await Promise.all([
      api<Browser>(`/storage/browser?${params}`),
      api<{ items?: Folder[] }>("/storage/folders/tree"),
    ]);
    if (request !== listGeneration || provider.value !== "telegram") return;
    browser.value = result;
    folderTree.value = Array.isArray(tree.items) ? tree.items : [];
    persistLocation();
  } catch (cause) {
    if (request === listGeneration) error.value = cause instanceof Error ? cause.message : "Storage tidak dapat dimuat.";
  } finally { if (request === listGeneration) loading.value = false; }
}

async function loadLinks() {
  if (!worker.value) { publicLinks.value = []; return; }
  const target = worker.value;
  linksLoading.value = true;
  try {
    const result = await api<{ items?: PublicLink[] }>(`/storage/download-links?worker=${encodeURIComponent(target)}`);
    if (worker.value === target) publicLinks.value = Array.isArray(result.items) ? result.items : [];
  } catch (cause) {
    if (worker.value === target) error.value = cause instanceof Error ? cause.message : "Daftar link publik tidak dapat dimuat.";
  } finally { linksLoading.value = false; }
}

async function loadReadiness(target = worker.value) {
  if (!target) { readinessCells.value = []; return; }
  try {
    const result = await api<{ runtime_readiness?: { cells?: ReadinessCell[] } }>("/profiles/local");
    if (worker.value === target) readinessCells.value = (result.runtime_readiness?.cells || []).filter((cell) => cell.worker === target);
  } catch {
    if (worker.value === target) readinessCells.value = [];
  }
}

async function loadRemote(refreshSummaries = false) {
  if (!worker.value || provider.value !== "rclone") return;
  const request = ++remoteGeneration;
  const targetWorker = worker.value;
  const targetPath = remotePath.value;
  const targetView = remoteView.value;
  remoteLoading.value = true;
  error.value = "";
  try {
    if (targetView === "trash") {
      const params = new URLSearchParams({ worker: targetWorker, limit: "100", offset: String(remoteOffset.value) });
      const response = await api<{ supported: boolean; permanent_delete_supported?: boolean; items: RemoteEntry[]; total: number; limit: number; offset: number }>(`/storage/rclone/trash?${params}`);
      if (request !== remoteGeneration || worker.value !== targetWorker || remoteView.value !== targetView) return;
      remote.value = { path: "", breadcrumbs: [], items: response.items || [], total: response.total || 0, limit: response.limit || 100, offset: response.offset || 0, trash_supported: response.supported, permanent_delete_supported: response.permanent_delete_supported };
      summaries.value = {};
      return;
    }
    const params = new URLSearchParams({ worker: targetWorker, path: targetPath, q: remoteQuery.value, sort: remoteSort.value, order: remoteOrder.value, limit: "100", offset: String(remoteOffset.value) });
    const response = await api<Remote>(`/storage/rclone/browser?${params}`);
    if (request !== remoteGeneration || worker.value !== targetWorker || remotePath.value !== targetPath || remoteView.value !== targetView) return;
    remote.value = response;
    if (refreshSummaries) void loadSummaries(targetWorker, targetPath);
  } catch (cause) { if (request === remoteGeneration) error.value = cause instanceof Error ? cause.message : "Remote rclone tidak dapat dimuat."; }
  finally { if (request === remoteGeneration) remoteLoading.value = false; }
}

async function loadSummaries(targetWorker: string, path: string) {
  const request = ++summaryGeneration;
  summaries.value = {};
  summaryFailed.value = false;
  summaryLoading.value = true;
  try {
    const params = new URLSearchParams({ worker: targetWorker, path });
    const result = await api<{ summaries?: { path: string; file_count: number; folder_count: number; size_bytes: number; size_complete: boolean }[] }>(`/storage/rclone/folder-summaries?${params}`);
    if (request !== summaryGeneration || worker.value !== targetWorker || remotePath.value !== path) return;
    summaries.value = Object.fromEntries((result.summaries || []).map((entry) => [entry.path, entry]));
  } catch { if (request === summaryGeneration) summaryFailed.value = true; }
  finally { if (request === summaryGeneration) summaryLoading.value = false; }
}

function changeWorker(value: string) {
  if (worker.value === value) return;
  worker.value = value;
  listGeneration++; remoteGeneration++; summaryGeneration++;
  folderId.value = null; scope.value = "current"; remotePath.value = ""; remoteView.value = "active"; remoteOffset.value = 0;
  remote.value = { path: "", breadcrumbs: [], items: [], total: 0, limit: 100, offset: 0 };
  summaries.value = {}; publicLinks.value = []; readinessCells.value = [];
  clearTelegramSelection(); clearRemoteSelection();
  void loadLinks();
  void loadReadiness(value);
}

function setProvider(next: "telegram" | "rclone") {
  if (provider.value === next) return;
  provider.value = next; clearTelegramSelection(); clearRemoteSelection();
  if (next === "rclone") { remotePath.value = ""; remoteView.value = "active"; remoteOffset.value = 0; remoteTarget.value = ""; remoteTargetSelected.value = false; }
}
function openFolder(id: number | null) { folderId.value = id; scope.value = "current"; clearTelegramSelection(); void loadTelegram(); }
function chooseScope(next: typeof scope.value) { scope.value = next; folderId.value = null; clearTelegramSelection(); void loadTelegram(); }
function persistSort() { localStorage.setItem("storage-sort", sort.value); }
function persistView() { localStorage.setItem("storage-view", view.value); }
function openRemote(path: string) { remotePath.value = path; remoteView.value = "active"; remoteOffset.value = 0; remoteTarget.value = path; remoteTargetSelected.value = true; clearRemoteSelection(); void loadRemote(true); }
function toggleItem(id: number) { selectedItems.value = selectedItems.value.includes(id) ? selectedItems.value.filter((value) => value !== id) : [...selectedItems.value, id]; }
function toggleFolder(id: number) { selectedFolders.value = selectedFolders.value.includes(id) ? selectedFolders.value.filter((value) => value !== id) : [...selectedFolders.value, id]; }
function toggleRemote(entry: RemoteEntry) { if (!entry.ambiguous) selectedRemote.value = selectedRemote.value.some((item) => item.path === entry.path) ? selectedRemote.value.filter((item) => item.path !== entry.path) : [...selectedRemote.value, entry]; }
function selectAll() { selectedItems.value = browser.value.items.map((item) => item.id); selectedFolders.value = browser.value.folders.map((folder) => folder.id); }
function selectAllRemote() { selectedRemote.value = [...new Map([...selectedRemote.value, ...remote.value.items.filter((item) => !item.ambiguous)].map((item) => [item.path, item])).values()]; }
function emptyTelegramTrash() {
  selectAll();
  if (selectedItems.value.length || selectedFolders.value.length) confirmTrash.value = "purge";
}
function folderSummary(folder: Folder) { return `${folder.file_count || 0} file · ${folder.folder_count || 0} folder · ${folder.size_complete === false ? "Ukuran tidak lengkap" : formatBytes(folder.size_bytes || 0)}`; }
function remoteSummary(entry: RemoteEntry) { const summary = summaries.value[entry.path]; return summary ? `${summary.file_count} file · ${summary.folder_count} folder · ${summary.size_complete ? formatBytes(summary.size_bytes) : "Ukuran tidak lengkap"}` : summaryLoading.value ? "Menghitung…" : summaryFailed.value ? "Ringkasan gagal dihitung" : "0 file · 0 folder · 0 B"; }

function dragStorage(event: DragEvent, kind: "item" | "folder", id: number) {
  event.dataTransfer?.setData("application/x-tme3-storage", JSON.stringify({ kind, id }));
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
}

async function dropOnFolder(event: DragEvent, destinationFolderId: number | null) {
  event.preventDefault();
  const payload = event.dataTransfer?.getData("application/x-tme3-storage");
  if (!payload) return;
  try {
    const parsed = JSON.parse(payload) as { kind?: string; id?: number };
    if (typeof parsed.id !== "number" || !Number.isSafeInteger(parsed.id) || (parsed.kind !== "item" && parsed.kind !== "folder")) return;
    await post("/storage/actions/move", {
      item_ids: parsed.kind === "item" ? [parsed.id] : [],
      folder_ids: parsed.kind === "folder" ? [parsed.id] : [],
      destination_folder_id: destinationFolderId,
    });
    message.value = "Item dipindahkan.";
    await loadTelegram();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Move gagal.";
  }
}

async function createFolder() {
  if (!newName.value.trim()) return;
  saving.value = true; error.value = "";
  try {
    if (provider.value === "telegram") await post("/storage/folders", { name: newName.value.trim(), parent_id: folderId.value });
    else await post("/storage/rclone/actions", { worker: worker.value, action: "create_folder", path: remotePath.value, name: newName.value.trim() });
    message.value = "Folder dibuat."; createOpen.value = false; newName.value = "";
    if (provider.value === "telegram") await loadTelegram(); else await loadRemote(true);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Folder gagal dibuat."; }
  finally { saving.value = false; }
}

async function saveRename() {
  if (!newName.value.trim()) return;
  saving.value = true; error.value = "";
  try {
    if (renameItem.value) await patch(`/storage/items/${renameItem.value.id}`, { display_name: newName.value.trim(), keywords: editKeywords.value });
    else if (renameFolder.value) await patch(`/storage/folders/${renameFolder.value.id}`, { name: newName.value.trim() });
    else if (renameRemote.value) await post("/storage/rclone/actions", { worker: worker.value, action: "rename", path: renameRemote.value.path, name: newName.value.trim() });
    message.value = "Perubahan disimpan."; renameItem.value = null; renameFolder.value = null; renameRemote.value = null;
    if (provider.value === "telegram") await loadTelegram(); else await loadRemote(true);
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Rename gagal."; }
  finally { saving.value = false; }
}

async function moveTelegram() {
  saving.value = true;
  try { await post("/storage/actions/move", { item_ids: selectedItems.value, folder_ids: selectedFolders.value, destination_folder_id: destinationId.value }); moveOpen.value = false; clearTelegramSelection(); await loadTelegram(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Move gagal."; }
  finally { saving.value = false; }
}
async function confirmTelegramTrash() {
  if (!confirmTrash.value) return;
  saving.value = true;
  try { await post(confirmTrash.value === "purge" ? "/storage/actions/purge" : "/storage/actions/trash", { item_ids: selectedItems.value, folder_ids: selectedFolders.value }); confirmTrash.value = null; clearTelegramSelection(); await loadTelegram(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Aksi Storage gagal."; }
  finally { saving.value = false; }
}
async function restoreTelegram() {
  saving.value = true;
  try { await post("/storage/actions/restore", { item_ids: selectedItems.value, folder_ids: selectedFolders.value }); clearTelegramSelection(); await loadTelegram(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Restore gagal."; }
  finally { saving.value = false; }
}

function openUpload() { workspaceFolders.value = []; transferMode.value = "copy"; moveConfirmed.value = false; keywords.value = ""; destinationId.value = provider.value === "telegram" ? folderId.value : null; if (provider.value === "rclone" && !remoteTargetSelected.value) { remoteTarget.value = remotePath.value; remoteTargetSelected.value = true; } uploadOpen.value = true; }
async function submitUpload() {
  const folderPath = workspaceFolders.value[0];
  if (!folderPath || !worker.value || !enabledWorker.value || (provider.value === "rclone" && !remoteTargetSelected.value) || (transferMode.value === "move" && !moveConfirmed.value)) return;
  saving.value = true; error.value = "";
  try {
    await post("/storage/uploads", { folder_path: folderPath, destination_folder_id: provider.value === "telegram" ? destinationId.value : null, provider: provider.value, rclone_path: provider.value === "rclone" ? remoteTarget.value : "", transfer_mode: transferMode.value, preserve_structure: true, keywords: keywords.value, worker: worker.value, move_confirmed: transferMode.value === "move" && moveConfirmed.value });
    uploadOpen.value = false; workspaceFolders.value = []; message.value = `Upload ${provider.value === "telegram" ? "Telegram" : "rclone"} masuk antrean sebagai ${transferMode.value}.`;
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Upload gagal dibuat."; }
  finally { saving.value = false; }
}

function openDownload() { downloadDestination.value = []; publishLinks.value = false; downloadProfile.value = session.current.profiles?.[0] || ""; downloadOpen.value = true; }
async function submitDownload() {
  const destination = downloadDestination.value[0];
  if (!worker.value || !enabledWorker.value || !destination || !activeSelectionCount.value) return;
  if (provider.value === "telegram" && !session.current.profiles?.includes(downloadProfile.value)) return;
  downloadBusy.value = true; error.value = "";
  try {
    const body = provider.value === "telegram"
      ? { provider: provider.value, worker: worker.value, profile: downloadProfile.value, item_ids: selectedItems.value, folder_ids: selectedFolders.value, destination_path: destination, publish_public_links: publishLinks.value }
      : { provider: provider.value, worker: worker.value, rclone_sources: selectedRemote.value.map(({ path, is_dir, size }) => ({ path, is_dir, size })), destination_path: destination, publish_public_links: publishLinks.value };
    const job = await post<{ id: string }>("/storage/downloads", body);
    downloadJobWorkers.value = { ...downloadJobWorkers.value, [job.id]: worker.value };
    downloadOpen.value = false; clearTelegramSelection(); clearRemoteSelection(); downloadDestination.value = [];
    message.value = `Unduhan ${job.id} masuk antrean pada ${worker.value}.`;
    window.dispatchEvent(new CustomEvent("tme3:data-mutated"));
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Download gagal dibuat."; }
  finally { downloadBusy.value = false; }
}

async function remoteManage(action: "copy" | "move" | "trash" | "restore" | "purge") {
  if (!selectedRemote.value.length || !worker.value) return;
  if (action === "move" && !moveAccepted.value) return;
  if (action === "purge" && purgeText.value !== "HAPUS") return;
  remoteManageBusy.value = true; error.value = "";
  try {
    const job = await post<{ id: string }>("/storage/rclone/jobs", { worker: worker.value, action, sources: selectedRemote.value.map(({ path, is_dir, id }) => ({ path, is_dir, ...(id ? { id } : {}) })), destination_path: ["copy", "move"].includes(action) ? remotePath.value : "", trashed: remoteView.value === "trash" && ["restore", "purge"].includes(action), confirmed: action === "purge" });
    manageRemote.value = null; clearRemoteSelection(); message.value = `Operasi rclone ${action} masuk Activity sebagai job ${job.id.slice(0, 8)}.`; window.dispatchEvent(new CustomEvent("tme3:data-mutated")); await loadRemote(remoteView.value === "active");
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Operasi rclone gagal dibuat."; }
  finally { remoteManageBusy.value = false; }
}
async function confirmRemoteManage() {
  const action = manageRemote.value;
  if (action) await remoteManage(action);
}

async function syncCatalog() {
  if (!worker.value || !syncProfiles.value.includes(syncProfile.value)) return;
  saving.value = true;
  try { const job = await post<{ id: string }>("/storage/sync", { worker: worker.value, profile: syncProfile.value }); syncJobId.value = job.id; message.value = `Sinkronisasi Telegram masuk antrean sebagai ${job.id}.`; window.dispatchEvent(new CustomEvent("tme3:data-mutated")); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Sinkronisasi gagal dibuat."; }
  finally { saving.value = false; }
}

async function scanStorage() {
  if (!worker.value || !enabledWorker.value || scanBusy.value) return;
  scanStatus.value = "queued"; scanError.value = ""; scanMessage.value = "Menyiapkan pemeriksaan profil Storage…"; scanProfiles.value = [];
  try {
    const requestId = globalThis.crypto?.randomUUID?.() || `storage-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const operation = await api<ScanOperation>("/tdl-access/verification", { method: "POST", headers: { "Idempotency-Key": requestId }, body: JSON.stringify({ purpose: "storage", worker: worker.value }) });
    scanOperationId.value = operation.operation_id; scanStatus.value = operation.status;
    if (["succeeded", "failed", "cancelled"].includes(operation.status)) await refreshScan();
    else pollScan();
  } catch (cause) { scanStatus.value = "failed"; scanError.value = cause instanceof Error ? cause.message : "Scan gagal dimulai."; }
}
async function refreshScan() {
  if (!scanOperationId.value) return;
  try {
    const operation = await api<ScanOperation>(`/operations/${encodeURIComponent(scanOperationId.value)}`);
    scanStatus.value = operation.status;
    const overall = operation.progress?.overall as { current?: number; total?: number } | undefined;
    scanMessage.value = overall?.total ? `${String(operation.progress?.message || operation.phase)}: ${overall.current || 0}/${overall.total} profil` : String(operation.progress?.message || operation.phase || "Memeriksa profil worker…");
    if (["succeeded", "failed", "cancelled"].includes(operation.status)) {
      if (operation.status === "succeeded") {
        const result = await api<{ profiles?: ReadinessProfile[] }>(`/tdl-access/verification?purpose=storage&worker=${encodeURIComponent(worker.value)}`);
        scanProfiles.value = result.profiles || [];
        scanMessage.value = `Pemeriksaan selesai: ${scanProfiles.value.filter((item) => item.ready).length}/${scanProfiles.value.length} profil dapat mengirim ke Storage.`;
        void sessionActions.refreshProfileCatalog();
        void loadReadiness(worker.value);
      } else scanError.value = operation.error?.message || `Pemeriksaan berakhir dengan status ${operation.status}.`;
      return;
    }
    pollScan();
  } catch (cause) { scanError.value = cause instanceof Error ? cause.message : "Progress scan tidak dapat dimuat."; pollScan(); }
}
function pollScan() { if (scanTimer) clearTimeout(scanTimer); scanTimer = setTimeout(() => void refreshScan(), 900); }

async function copyLink(link: PublicLink) { try { await navigator.clipboard.writeText(link.url); message.value = `Link ${link.file_name} disalin.`; } catch { error.value = "Clipboard tidak tersedia."; } }
async function revokePublicLink() {
  if (!revokeLink.value) return;
  saving.value = true;
  try { const link = revokeLink.value; const result = await post<{ cleanup_status: string }>(`/storage/download-links/${encodeURIComponent(link.id)}/revoke?worker=${encodeURIComponent(link.worker)}`, { confirmed: true }); revokeLink.value = null; await loadLinks(); message.value = ["deleted", "already_missing"].includes(result.cleanup_status) ? "Link dicabut dan file worker dihapus." : `Link dicabut; cleanup file berstatus ${result.cleanup_status}.`; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : "Link tidak dapat dicabut."; }
  finally { saving.value = false; }
}
async function deliver(item: StorageItem) { try { await post(`/storage/items/${item.id}/deliveries`, { method: "telegram" }); message.value = `${item.display_name} dikirim ke Telegram.`; } catch (cause) { error.value = cause instanceof Error ? cause.message : "Pengiriman gagal."; } }
async function copyFileCode(item: StorageItem) { try { const result = await api<{ code: string }>(`/storage/items/${item.id}/deep-link`); await navigator.clipboard.writeText(result.code); message.value = `Kode ${item.display_name} disalin.`; } catch (cause) { error.value = cause instanceof Error ? cause.message : "Kode file tidak dapat disalin."; } }

async function handleJobsFinished(event: Event) {
  const ids = (event as CustomEvent<{ jobIds?: string[] }>).detail?.jobIds || [];
  const downloads = ids.filter((id) => Boolean(downloadJobWorkers.value[id]));
  if (downloads.length) {
    const targets = new Set(downloads.map((id) => downloadJobWorkers.value[id]));
    const results = await Promise.all(downloads.map(async (id) => {
      try {
        const job = await api<{ status: string; result?: { value?: { succeeded?: number; failed?: number; cancelled_items?: number; public_links_failed?: number } }; error?: { message?: string } }>(`/jobs/${encodeURIComponent(id)}`);
        const value = job.result?.value;
        return `Unduhan ${job.status}: ${value?.succeeded ?? 0} berhasil, ${value?.failed ?? 0} gagal, ${value?.cancelled_items ?? 0} dibatalkan. Link gagal: ${value?.public_links_failed ?? 0}.${job.error?.message ? ` ${job.error.message}` : ""}`;
      } catch (cause) { return cause instanceof Error ? cause.message : `Hasil unduhan ${id.slice(0, 8)} tidak dapat dimuat.`; }
      finally { const next = { ...downloadJobWorkers.value }; delete next[id]; downloadJobWorkers.value = next; }
    }));
    if (targets.has(worker.value)) await loadLinks();
    message.value = results.join(" ");
  }
  if (!syncJobId.value || !ids.includes(syncJobId.value)) return;
  try {
    const job = await api<{ status: string; result?: { value?: { history_complete?: boolean; catalog?: Record<string, number> } }; error?: { message?: string } }>(`/jobs/${encodeURIComponent(syncJobId.value)}`);
    const catalog = job.result?.value?.catalog;
    if (job.status === "succeeded" && catalog) {
      message.value = `Sinkronisasi selesai: ${catalog.recovered || 0} dipulihkan, ${catalog.updated || 0} diperbarui, ${catalog.restored || 0} dari Trash dipulihkan, ${catalog.deleted || 0} dihapus, ${catalog.deletion_held || 0} penghapusan ditahan. ${job.result?.value?.history_complete ? "Riwayat lengkap." : "Riwayat belum terbukti lengkap; item yang tidak ditemukan dipertahankan."}`;
      await loadTelegram();
    } else message.value = job.error?.message || `Sinkronisasi berakhir dengan status ${job.status}.`;
  } catch (cause) { message.value = cause instanceof Error ? cause.message : "Hasil sinkronisasi tidak dapat dimuat."; }
  finally { syncJobId.value = ""; }
}

function openDetail(item: StorageItem, event: MouseEvent) {
  detailTrigger.value = event.currentTarget as HTMLElement;
  detailItem.value = item;
  void nextTick(() => detailCloseButton.value?.focus());
}
function closeDetail() {
  detailItem.value = null;
  void nextTick(() => {
    if (detailTrigger.value?.isConnected) detailTrigger.value.focus();
    detailTrigger.value = null;
  });
}
function detailKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") { event.preventDefault(); closeDetail(); return; }
  if (event.key !== "Tab" || !detailPanel.value) return;
  const focusable = Array.from(detailPanel.value.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'));
  if (!focusable.length) { event.preventDefault(); detailPanel.value.focus(); return; }
  const first = focusable[0]; const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !detailPanel.value.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !detailPanel.value.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
}

watch([provider, worker], ([nextProvider, nextWorker], [previousProvider, previousWorker]) => {
  if (nextProvider === previousProvider && nextWorker === previousWorker) return;
  if (nextProvider === "telegram") void loadTelegram();
  else void loadRemote(true);
  if (nextWorker !== previousWorker) void loadReadiness(nextWorker);
});
watch(() => session.current.profiles, (profiles) => { if (!profiles.includes(syncProfile.value)) syncProfile.value = profiles[0] || ""; }, { immediate: true });
onMounted(async () => {
  const params = new URLSearchParams(location.search);
  const folder = params.get("folder");
  if (folder && folder !== "root" && Number.isFinite(Number(folder))) folderId.value = Number(folder);
  view.value = (localStorage.getItem("storage-view") as "list" | "grid") || "list";
  sort.value = localStorage.getItem("storage-sort") || "name";
  try {
    const result = await api<{ items?: { name: string; enabled?: boolean; public_url?: string }[] }>("/workers");
    workers.value = result.items || [];
    worker.value = session.current.actor?.worker_route || workers.value.find((item) => item.enabled !== false)?.name || "";
    await loadLinks();
    if (!worker.value) {
      await loadReadiness("");
      if (provider.value === "telegram") await loadTelegram();
      else await loadRemote(true);
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : "Daftar worker gagal dimuat."; }
  jobFinishedHandler = (event) => { void handleJobsFinished(event); };
  window.addEventListener("tme3:job-finished", jobFinishedHandler);
});
onUnmounted(() => { if (scanTimer) clearTimeout(scanTimer); if (jobFinishedHandler) window.removeEventListener("tme3:job-finished", jobFinishedHandler); listGeneration++; remoteGeneration++; summaryGeneration++; });
</script>

<template>
  <main class="page-stack storage-page">
    <header class="page-heading"><div><p class="eyebrow">TRANSFER</p><h1>Cloud Storage</h1><p class="muted">Telegram catalog dan remote rclone pada worker yang dipilih.</p></div><label class="worker-select">Worker<select class="field" aria-label="Worker target" :value="worker" @change="changeWorker(($event.target as HTMLSelectElement).value)"><option v-for="item in workers" :key="item.name" :value="item.name">{{ item.name }}{{ item.enabled === false ? " · nonaktif" : "" }}</option></select></label></header>
    <p v-if="!enabledWorker" class="notice notice-warning" role="status">Worker nonaktif untuk job baru. Link publik lama masih dapat dikelola.</p>
    <p v-if="message" class="notice notice-success" role="status">{{ message }} <button class="button button-secondary button-small" @click="message = ''">Tutup</button></p>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>

    <nav class="provider-tabs" role="tablist" aria-label="Sumber Storage"><button role="tab" :aria-selected="provider === 'telegram'" :class="{ active: provider === 'telegram' }" @click="setProvider('telegram')">Telegram</button><button role="tab" :aria-selected="provider === 'rclone'" :class="{ active: provider === 'rclone' }" @click="setProvider('rclone')">Rclone</button></nav>

    <section class="panel public-links" aria-label="Link publik Storage">
      <header class="panel-heading"><div><h2>Link unduhan publik</h2><p class="muted">Link tidak kedaluwarsa. Mencabut link menghapus file worker.</p></div><button class="button button-secondary button-small" :disabled="linksLoading || !worker" @click="loadLinks">{{ linksLoading ? "Memuat…" : "Refresh link" }}</button></header>
      <div v-if="publicLinks.length" class="link-list"><article v-for="link in publicLinks" :key="link.id" class="link-row"><div class="link-main"><strong>{{ link.file_name }}</strong><small class="muted">{{ link.provider }} · {{ formatDate(link.created_at) }} · {{ link.worker }}</small><small class="muted path-text">{{ link.relative_path }}</small><a :href="link.url" target="_blank" rel="noreferrer">{{ link.url }}</a></div><button class="button button-secondary button-small" @click="copyLink(link)">Salin</button><button class="button button-danger button-small" @click="revokeLink = link">Cabut &amp; hapus file</button></article></div>
      <p v-else class="empty-state">{{ linksLoading ? "Memuat link worker…" : "Belum ada link publik aktif." }}</p>
    </section>

    <section v-if="provider === 'telegram'" class="panel readiness-panel">
      <header class="panel-heading"><div><h2>Kesiapan Storage</h2><p class="muted">Snapshot hanya informasi. Job tetap membuktikan akses lewat command TDL yang dijalankan.</p><span class="status-pill" :class="storageReadinessLabel === 'Storage siap' ? 'status-ready' : storageReadinessLabel === 'Storage belum siap' ? 'status-failed' : 'status-neutral'" role="status">{{ storageReadinessLabel }}</span></div><button class="button button-secondary button-small" :disabled="!enabledWorker || scanBusy" @click="scanStorage">{{ scanBusy ? "Memindai worker…" : "Scan worker" }}</button></header>
      <ul v-if="workerStorageCells.length" class="readiness-list"><li v-for="cell in workerStorageCells" :key="`${cell.worker}:${cell.profile}`"><strong>{{ cell.profile || "Worker" }}</strong><span :class="cell.status === 'ready' ? 'ready' : 'failed'">{{ cell.status === 'ready' ? "Siap" : `${cell.status}${cell.reason_code ? ` · ${cell.reason_code}` : ''}` }}</span></li></ul>
      <div v-if="scanStatus !== 'idle'" class="scan-result" role="status" aria-label="Progress scan Storage"><strong>{{ scanMessage || scanStatus }}</strong><p v-if="scanError" role="alert">{{ scanError }}</p><ul v-if="scanProfiles.length"><li v-for="item in scanProfiles" :key="item.profile"><span>{{ item.profile }}</span><b :class="item.ready ? 'ready' : 'failed'">{{ item.ready ? "Siap" : item.error_code || "Gagal" }}</b></li></ul></div>
      <div class="sync-panel"><div><h3>Sinkronkan katalog dari Telegram</h3><p class="muted">Cocokkan message ID channel dengan katalog; file media tidak diunduh.</p></div><label>Profil sumber<select v-model="syncProfile" class="field" aria-label="Profil sumber"><option v-for="profile in syncProfiles" :key="profile" :value="profile">{{ profile }}</option></select></label><button class="button button-primary" :disabled="saving || !worker || !syncProfiles.includes(syncProfile)" @click="syncCatalog">{{ saving ? "Menyiapkan…" : "Sinkronkan sekarang" }}</button></div>
    </section>

    <section v-if="provider === 'telegram'" class="panel browser-panel" aria-label="Browser Telegram Storage">
      <header class="storage-toolbar"><div class="scope-tabs" aria-label="Lokasi katalog"><button v-for="item in [['current','My Drive'],['global','All Files'],['recent','Recent'],['trash','Recycle Bin']] as const" :key="item[0]" :aria-pressed="scope === item[0]" :class="{ active: scope === item[0] }" @click="chooseScope(item[0])">{{ item[1] }}</button></div><div class="toolbar-actions"><button v-if="scope !== 'trash'" class="button button-secondary button-small" @click="createOpen = true">Folder baru</button><button v-if="scope !== 'trash'" class="button button-primary button-small" :disabled="!enabledWorker" @click="openUpload">Upload</button><button class="button button-secondary button-small" :disabled="loading" @click="loadTelegram">{{ loading ? "Memuat…" : "Refresh" }}</button></div></header>
      <div class="browser-controls"><div class="breadcrumbs"><button @click="openFolder(null)">Drive</button><template v-for="crumb in browser.breadcrumbs" :key="crumb.id"><span>›</span><button @click="openFolder(crumb.id)">{{ crumb.name }}</button></template><strong>{{ currentFolderName }}</strong></div><label class="search-field"><span class="sr-only">Cari file atau folder</span><input v-model="query" class="field" placeholder="Cari file atau folder" @keydown.enter="loadTelegram" /></label><select v-model="sort" class="field compact" aria-label="Urutkan Storage" @change="persistSort(); loadTelegram()"><option value="name">Nama</option><option value="updated_at">Terbaru</option><option value="size">Ukuran</option><option value="type">Tipe</option></select><button class="button button-secondary button-small" @click="order = order === 'asc' ? 'desc' : 'asc'; loadTelegram()">{{ order === "asc" ? "A–Z" : "Z–A" }}</button><button class="button button-secondary button-small" aria-label="Tampilan daftar" :aria-pressed="view === 'list'" @click="view = 'list'; persistView()">Daftar</button><button class="button button-secondary button-small" aria-label="Tampilan grid" :aria-pressed="view === 'grid'" @click="view = 'grid'; persistView()">Grid</button></div>
      <div v-if="activeSelectionCount || (scope === 'trash' && (browser.items.length || browser.folders.length))" class="selection-toolbar">
        <strong>{{ activeSelectionCount }} dipilih</strong>
        <button class="button button-secondary button-small" @click="selectAll">Pilih semua</button>
        <button v-if="scope === 'trash' && activeSelectionCount" class="button button-secondary button-small" @click="restoreTelegram">Restore</button>
        <button v-else-if="scope === 'trash'" class="button button-danger button-small" @click="emptyTelegramTrash">Kosongkan Trash</button>
        <template v-else><button class="button button-secondary button-small" @click="openDownload">Download</button><button class="button button-secondary button-small" @click="moveOpen = true; destinationId = folderId">Move</button><button class="button button-danger button-small" @click="confirmTrash = 'trash'">Trash</button></template>
        <button class="button button-secondary button-small" @click="clearTelegramSelection">Batal pilih</button>
      </div>
      <div v-if="loading && !browser.items.length && !browser.folders.length" class="empty-state">Memuat katalog…</div><div v-else-if="browser.items.length || browser.folders.length" class="telegram-list" :class="`view-${view}`" role="list" @dragover.prevent @drop="dropOnFolder($event, folderId)">
        <article v-for="folder in browser.folders" :key="`f-${folder.id}`" class="storage-entry" role="listitem" draggable="true" @dragstart="dragStorage($event, 'folder', folder.id)" @dragover.prevent @drop.stop="dropOnFolder($event, folder.id)"><input type="checkbox" :checked="selectedFolders.includes(folder.id)" :aria-label="`Pilih folder ${folder.name}`" @change="toggleFolder(folder.id)"/><button class="entry-main" @click="openFolder(folder.id)"><span class="entry-icon">📁</span><span><strong>{{ folder.name }}</strong><small>{{ folderSummary(folder) }}</small></span></button><span class="muted entry-kind">Folder</span><button class="button button-secondary button-small" :aria-label="`Rename folder ${folder.name}`" @click="renameFolder = folder; newName = folder.name">Rename</button></article>
        <article v-for="item in browser.items" :key="`i-${item.id}`" class="storage-entry" role="listitem" draggable="true" @dragstart="dragStorage($event, 'item', item.id)"><input type="checkbox" :checked="selectedItems.includes(item.id)" :aria-label="`Pilih file ${item.display_name}`" @change="toggleItem(item.id)"/><button class="entry-main" @click="openDetail(item, $event)"><span class="entry-icon">{{ item.mime_type?.startsWith("image/") ? "▧" : item.mime_type?.startsWith("video/") ? "▶" : "▤" }}</span><span><strong>{{ item.display_name }}</strong><small>{{ item.original_name }}</small></span></button><span class="muted entry-size">{{ formatBytes(item.file_size) }}</span><span class="muted entry-date">{{ formatDate(item.uploaded_at) }}</span><button class="button button-secondary button-small" :aria-label="`Detail ${item.display_name}`" @click="openDetail(item, $event)">Detail</button></article>
      </div><p v-else class="empty-state">{{ isTrash ? "Trash masih bersih." : "Folder ini kosong. Buat folder atau upload dari Workspace." }}</p>
      <footer class="list-footer">{{ browser.total_folders }} folder · {{ browser.total_items }} file</footer>
    </section>

    <section v-else class="panel browser-panel" aria-label="Browser rclone">
      <header class="storage-toolbar"><div><h2>Remote rclone</h2><p class="muted">Worker {{ worker || "belum dipilih" }} · command rclone menjadi bukti akses sebenarnya.</p></div><div class="toolbar-actions"><button v-if="selectedRemote.length" class="button button-secondary button-small" @click="openDownload">Download {{ selectedRemote.length }} dipilih</button><template v-if="selectedRemote.length && remoteView === 'active'"><button class="button button-secondary button-small" @click="manageRemote='copy'; moveAccepted=false">Copy ke sini</button><button class="button button-secondary button-small" @click="manageRemote='move'; moveAccepted=false">Move ke sini</button><button class="button button-danger button-small" :disabled="!remote.trash_supported && !remote.permanent_delete_supported" @click="manageRemote=remote.trash_supported?'trash':'purge'; purgeText=''">{{ remote.trash_supported ? "Pindahkan ke Trash" : remote.permanent_delete_supported ? "Hapus permanen" : "Hapus tidak didukung" }}</button></template><template v-else-if="selectedRemote.length"><button class="button button-secondary button-small" :disabled="!remote.trash_supported" @click="manageRemote='restore'">Pulihkan</button><button class="button button-danger button-small" :disabled="!remote.permanent_delete_supported" @click="manageRemote='purge'; purgeText=''">Hapus permanen</button></template><button v-if="remoteView === 'active'" class="button button-secondary button-small" @click="createOpen=true; newName=''">Folder baru</button><button v-if="remoteView === 'active'" class="button button-primary button-small" :disabled="!enabledWorker" @click="openUpload">Upload ke folder ini</button></div></header>
      <nav class="scope-tabs" role="tablist" aria-label="Tampilan rclone"><button role="tab" :aria-selected="remoteView==='active'" @click="remoteView='active';remoteOffset=0;clearRemoteSelection();loadRemote(true)">Remote</button><button role="tab" :aria-selected="remoteView==='trash'" @click="remoteView='trash';remoteOffset=0;clearRemoteSelection();loadRemote(false)">Trash</button></nav>
      <div v-if="remote.items.length" class="selection-toolbar"><strong>{{ selectedRemote.length }} dipilih</strong><button class="button button-secondary button-small" @click="selectAllRemote">Pilih semua di halaman</button><button v-if="selectedRemote.length" class="button button-secondary button-small" @click="clearRemoteSelection">Batal pilih</button></div>
      <div class="browser-controls"><div v-if="remoteView==='active'" class="breadcrumbs"><button @click="openRemote('')">Root</button><template v-for="(crumb,index) in remotePath.split('/').filter(Boolean)" :key="crumb"><span>›</span><button @click="openRemote(remotePath.split('/').filter(Boolean).slice(0,index+1).join('/'))">{{ crumb }}</button></template></div><input v-if="remoteView==='active'" v-model="remoteQuery" class="field search-field" placeholder="Cari di folder ini" @keydown.enter="remoteOffset=0;loadRemote()"/><select v-if="remoteView==='active'" v-model="remoteSort" class="field compact" aria-label="Urutkan rclone" @change="remoteOffset=0;loadRemote()"><option value="name">Nama</option><option value="updated_at">Terbaru</option><option value="size">Ukuran</option><option value="type">Tipe</option></select><button class="button button-secondary button-small" @click="remoteOrder=remoteOrder==='asc'?'desc':'asc';loadRemote()">{{ remoteOrder==='asc'?'A–Z':'Z–A' }}</button><button class="button button-secondary button-small" aria-label="Refresh rclone" :disabled="remoteLoading" @click="loadRemote(remoteView==='active')">{{ remoteLoading || summaryLoading ? "Memuat…" : "Refresh" }}</button></div>
      <p v-if="remoteView==='trash' && !remote.trash_supported" class="notice notice-warning">Trash remote tidak tersedia. {{ remote.permanent_delete_supported ? "Penghapusan permanen didukung dengan konfirmasi." : "Semantik hapus permanen tidak dapat dipastikan." }}</p>
      <div class="rclone-list"><article v-for="entry in remote.items" :key="`${entry.path}:${entry.id||entry.name}`" class="storage-entry"><input type="checkbox" :disabled="entry.ambiguous" :checked="selectedRemote.some((item)=>item.path===entry.path)" :aria-label="`Pilih ${entry.is_dir?'folder':'file'} ${entry.name}`" @change="toggleRemote(entry)"/><button v-if="entry.is_dir && remoteView==='active'" class="entry-main" @click="openRemote(entry.path)"><span class="entry-icon">📁</span><span><strong>{{ entry.name }}</strong><small>{{ remoteSummary(entry) }}</small></span></button><span v-else class="entry-main"><span class="entry-icon">▤</span><span><strong>{{ remoteView==='trash'?entry.path:entry.name }}</strong><small>{{ entry.size===null?'Ukuran tidak tersedia':formatBytes(entry.size) }}</small></span></span><button v-if="entry.is_dir && remoteView==='active'" class="button button-secondary button-small" @click="remoteTarget=entry.path;remoteTargetSelected=true;message=`Tujuan upload dipilih: ${entry.path}`">Pilih tujuan</button><span v-if="entry.ambiguous" class="muted">Path ganda; aksi dinonaktifkan</span><button v-if="remoteView==='active'" class="button button-secondary button-small" :aria-label="`Rename ${entry.name}`" @click="renameRemote=entry;newName=entry.name">Rename</button></article><p v-if="!remote.items.length" class="empty-state">{{ remoteLoading?'Memuat remote…':'Folder kosong atau tidak ada hasil.' }}</p></div>
      <footer class="list-footer"><span>{{ remote.total }} entri<span v-if="remoteView==='active'"> · tujuan upload: {{ remoteTargetSelected ? remoteTarget || 'root' : 'belum dipilih' }}</span></span><div class="toolbar-actions"><button class="button button-secondary button-small" :disabled="remoteOffset<=0 || remoteLoading" @click="remoteOffset=Math.max(0,remoteOffset-100);loadRemote()">Sebelumnya</button><span>Halaman {{ Math.floor(remoteOffset / 100)+1 }}</span><button class="button button-secondary button-small" :disabled="remoteOffset+remote.limit>=remote.total || remoteLoading" @click="remoteOffset+=100;loadRemote()">Berikutnya</button></div></footer>
    </section>

    <JobMonitor kind="storage_upload" title="Upload Storage" />
    <JobMonitor kind="storage_download" title="Unduhan Storage" />
    <JobMonitor v-if="provider==='telegram'" kind="storage_sync" title="Sinkronisasi katalog Telegram" />

    <section v-if="uploadOpen" class="modal-backdrop" @click.self="uploadOpen=false"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="upload-title"><header class="modal-heading"><h2 id="upload-title">Upload folder Workspace</h2><button class="icon-button" aria-label="Tutup upload" @click="uploadOpen=false">×</button></header><p class="muted">{{ provider==='telegram'?'Upload mencoba profil lokal worker ini.':'Upload menjalankan rclone pada worker ini.' }} Struktur subfolder dipertahankan.</p><WorkspaceExplorer v-model:selected="workspaceFolders" single :worker="worker"/><label v-if="provider==='telegram'">Folder tujuan Telegram<select v-model.number="destinationId" class="field"><option :value="null">My Drive</option><option v-for="folder in folderTree" :key="folder.id" :value="folder.id">{{ folder.path }}</option></select></label><p v-else class="muted">Tujuan rclone: {{ remoteTargetSelected ? remoteTarget || "root" : "pilih folder di tab Rclone" }}</p><label>Keywords opsional<input v-model="keywords" class="field" placeholder="archive, project" /></label><label>Transfer<select v-model="transferMode" class="field"><option value="copy">Copy · sumber tetap ada</option><option value="move">Move · hapus setelah upload terkonfirmasi</option></select></label><label v-if="transferMode==='move'" class="confirm-line"><input v-model="moveConfirmed" type="checkbox" /> Saya paham file Workspace dihapus per file setelah upload terverifikasi dan metadata sumber cocok.</label><div class="modal-actions"><button class="button button-secondary" @click="uploadOpen=false">Batal</button><button class="button button-primary" :disabled="!workspaceFolders.length || !enabledWorker || (provider==='rclone'&&!remoteTargetSelected) || (transferMode==='move'&&!moveConfirmed) || saving" @click="submitUpload">{{ saving ? "Mengirim…" : "Mulai upload" }}</button></div></div></section>
    <section v-if="downloadOpen" class="modal-backdrop" @click.self="downloadOpen=false"><div class="modal-card modal-wide" role="dialog" aria-modal="true" aria-labelledby="download-title"><header class="modal-heading"><h2 id="download-title">Download ke worker</h2><button class="icon-button" aria-label="Tutup download" @click="downloadOpen=false">×</button></header><label v-if="provider==='telegram'">Profil dengan lane Download<select v-model="downloadProfile" class="field" aria-label="Profil dengan lane Download siap"><option v-for="profile in session.current.profiles" :key="profile" :value="profile">{{ profile }}</option></select></label><p v-if="provider==='telegram'" class="muted">Readiness hanya informasi; download mencoba command TDL aktual.</p><p v-else class="muted">Download memakai worker rclone terpilih.</p><p class="muted">Pilih folder tujuan di /workspace</p><WorkspaceExplorer v-model:selected="downloadDestination" single :worker="worker"/><label class="confirm-line"><input v-model="publishLinks" type="checkbox" />Buat link publik tanpa kedaluwarsa untuk setiap file</label><div class="modal-actions"><button class="button button-secondary" @click="downloadOpen=false">Batal</button><button class="button button-primary" :disabled="!enabledWorker || !downloadDestination.length || !activeSelectionCount || downloadBusy" @click="submitDownload">{{ downloadBusy ? "Membuat job…" : "Mulai download" }}</button></div></div></section>
    <section v-if="createOpen" class="modal-backdrop" @click.self="createOpen=false"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="folder-title"><header class="modal-heading"><h2 id="folder-title">Folder baru</h2><button class="icon-button" aria-label="Tutup folder baru" @click="createOpen=false">×</button></header><label>Nama folder<input v-model="newName" class="field" maxlength="120" aria-label="Nama folder" /></label><p class="muted">Maksimal 120 karakter. Slash, titik tunggal, dan karakter kontrol tidak diperbolehkan.</p><div class="modal-actions"><button class="button button-secondary" @click="createOpen=false">Batal</button><button class="button button-primary" :disabled="!newName.trim() || saving" @click="createFolder">Buat folder</button></div></div></section>
    <section v-if="moveOpen" class="modal-backdrop" @click.self="moveOpen=false"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="move-title"><header class="modal-heading"><h2 id="move-title">Pindahkan ke folder</h2></header><label>Folder tujuan<select v-model.number="destinationId" class="field"><option :value="null">My Drive</option><option v-for="folder in folderTree" :key="folder.id" :value="folder.id">{{ folder.path }}</option></select></label><div class="modal-actions"><button class="button button-secondary" @click="moveOpen=false">Batal</button><button class="button button-primary" :disabled="saving" @click="moveTelegram">Pindahkan</button></div></div></section>
    <section v-if="renameItem || renameFolder || renameRemote" class="modal-backdrop" @click.self="renameItem=null;renameFolder=null;renameRemote=null"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="rename-title"><header class="modal-heading"><h2 id="rename-title">{{ renameItem ? "Metadata file" : renameFolder ? "Rename folder" : "Rename item rclone" }}</h2></header><label>{{ renameItem ? "Nama tampilan" : "Nama baru" }}<input v-model="newName" class="field" aria-label="Nama file atau folder" /></label><label v-if="renameItem">Keywords<input v-model="editKeywords" class="field" /></label><div class="modal-actions"><button class="button button-secondary" @click="renameItem=null;renameFolder=null;renameRemote=null">Batal</button><button class="button button-primary" :disabled="saving || !newName.trim()" @click="saveRename">Simpan</button></div></div></section>
    <section v-if="confirmTrash" class="modal-backdrop"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="trash-title"><header class="modal-heading"><h2 id="trash-title">{{ confirmTrash==='purge'?'Hapus permanen?':'Pindahkan ke Trash?' }}</h2></header><p>{{ confirmTrash==='purge'?'Pesan Telegram dan metadata akan dihapus permanen.':'File dan folder tetap dapat dipulihkan selama item masih tersedia.' }}</p><div class="modal-actions"><button class="button button-secondary" @click="confirmTrash=null">Batal</button><button class="button button-danger" :disabled="saving" @click="confirmTelegramTrash">{{ confirmTrash==='purge'?'Purge permanen':'Pindahkan' }}</button></div></div></section>
    <section v-if="manageRemote" class="modal-backdrop"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="manage-title"><header class="modal-heading"><h2 id="manage-title">{{ manageRemote==='purge'?'Hapus permanen?':manageRemote==='move'?'Pindahkan item rclone?':manageRemote==='trash'?'Pindahkan ke Trash?':manageRemote==='restore'?'Pulihkan item?':'Copy item rclone?' }}</h2></header><p v-if="manageRemote==='restore'" class="notice notice-warning">Google Drive hanya menyediakan restore seluruh item Trash di folder induk secara rekursif. Pilih semua item Trash pada folder induk yang sama dalam satu batch. Jika pilihan tidak mencakup seluruh cakupan, job menolak restore agar item lain tidak ikut berubah. Jika satu item pilihan berbenturan dengan item aktif, seluruh grup folder induk itu dibatalkan; grup folder induk lain tetap diproses.</p><p v-else>{{ selectedRemote.length }} item. Benturan tujuan gagal tanpa overwrite. Perubahan yang berhasil tetap dipertahankan bila job dibatalkan.</p><label v-if="manageRemote==='move'" class="confirm-line"><input v-model="moveAccepted" type="checkbox" />Saya memahami sumber baru dihapus setelah salinan terkonfirmasi.</label><label v-if="manageRemote==='purge'">Ketik HAPUS untuk mengonfirmasi<input v-model="purgeText" class="field" autocomplete="off" /></label><div class="modal-actions"><button class="button button-secondary" :disabled="remoteManageBusy" @click="manageRemote=null">Batal</button><button class="button button-danger" :disabled="remoteManageBusy || (manageRemote==='move'&&!moveAccepted) || (manageRemote==='purge'&&purgeText!=='HAPUS')" @click="confirmRemoteManage">{{ remoteManageBusy?'Membuat job…':manageRemote==='purge'?'Hapus permanen':manageRemote==='move'?'Move':manageRemote==='trash'?'Trash':manageRemote==='restore'?'Pulihkan':'Copy' }}</button></div></div></section>
    <section v-if="revokeLink" class="modal-backdrop"><div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="revoke-title"><header class="modal-heading"><h2 id="revoke-title">Cabut link dan hapus file worker?</h2></header><p>Link {{ revokeLink.file_name }} akan dicabut. File di worker juga akan dihapus.</p><div class="modal-actions"><button class="button button-secondary" @click="revokeLink=null">Batal</button><button class="button button-danger" :disabled="saving" @click="revokePublicLink">Cabut &amp; hapus file</button></div></div></section>
    <section v-if="detailItem" class="modal-backdrop" @click.self="closeDetail"><button class="backdrop-dismiss" aria-label="Tutup detail file melalui latar" @click="closeDetail"></button><div ref="detailPanel" class="modal-card modal-detail" role="dialog" aria-modal="true" aria-label="Detail file" tabindex="-1" @keydown="detailKeydown"><header class="modal-heading sticky-heading"><h2>Detail file</h2><button ref="detailCloseButton" class="icon-button" aria-label="Tutup detail file" @click="closeDetail">×</button></header><div class="detail-name"><span class="entry-icon">▤</span><h3>{{ detailItem.display_name }}</h3><p>{{ detailItem.original_name }}</p></div><dl class="detail-grid"><dt>Lokasi</dt><dd>{{ detailItem.folder || "My Drive" }}</dd><dt>Ukuran</dt><dd>{{ formatBytes(detailItem.file_size) }}</dd><dt>Keywords</dt><dd>{{ detailItem.keywords || "-" }}</dd><dt>Uploader</dt><dd>{{ detailItem.owner_profile || "-" }}</dd><dt>Upload</dt><dd>{{ formatDate(detailItem.uploaded_at) }}</dd><dt>Caption</dt><dd>{{ detailItem.caption_sync_status || "synced" }}</dd><template v-if="detailItem.recovered_at"><dt>Dipulihkan dari</dt><dd>{{ detailItem.recovered_from_profile || "-" }}</dd></template></dl><div class="detail-actions"><button class="button button-primary" @click="deliver(detailItem)">Kirim Telegram</button><button class="button button-secondary" @click="copyFileCode(detailItem)">Salin kode file</button><button class="button button-secondary" @click="renameItem=detailItem;newName=detailItem.display_name;editKeywords=detailItem.keywords||''">Rename / keyword</button><button class="button button-secondary" @click="selectedItems=[detailItem.id];closeDetail();moveOpen=true">Move</button><button class="button button-danger" @click="selectedItems=[detailItem.id];closeDetail();confirmTrash=isTrash?'purge':'trash'">{{ isTrash ? "Purge permanen" : "Pindahkan ke Trash" }}</button></div></div></section>
  </main>
</template>

<style scoped>
.storage-page{--storage-gap:.75rem}.worker-select{display:grid;gap:.25rem;min-width:12rem;font-size:.7rem;font-weight:700}.provider-tabs,.scope-tabs{display:flex;flex-wrap:wrap;gap:.35rem}.provider-tabs button,.scope-tabs button{border:1px solid var(--line);border-radius:.6rem;padding:.45rem .75rem;font-size:.74rem;font-weight:750}.provider-tabs button[aria-selected="true"],.scope-tabs button.active{background:var(--brand-soft);color:var(--brand)}.public-links,.readiness-panel,.browser-panel{padding:.8rem}.link-list,.telegram-list,.rclone-list{display:grid;gap:.35rem}.link-row,.storage-entry,.storage-toolbar,.browser-controls,.list-footer,.selection-toolbar,.sync-panel,.scan-result li{display:flex;align-items:center;gap:.55rem}.link-row,.storage-entry{min-width:0;padding:.6rem;border:1px solid var(--line);border-radius:.65rem}.link-main,.entry-main{display:grid;min-width:0;flex:1;gap:.12rem;text-align:left}.link-main>*{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.link-main a{font-size:.7rem;color:var(--accent)}.link-main small,.entry-main small{font-size:.66rem}.path-text{font-family:ui-monospace,monospace}.panel-heading,.storage-toolbar,.list-footer,.sync-panel{justify-content:space-between;flex-wrap:wrap}.storage-toolbar,.browser-controls{padding:.5rem 0;border-bottom:1px solid var(--line)}.browser-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem}.toolbar-actions,.breadcrumbs,.scope-tabs{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap}.breadcrumbs{min-width:0;flex:1;font-size:.72rem}.breadcrumbs button{font-weight:700}.search-field{min-width:12rem;flex:1}.field.compact{width:auto;min-width:6rem}.entry-main{display:flex;align-items:center;gap:.55rem}.entry-main span:last-child{display:grid;min-width:0}.entry-main strong,.entry-main small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.entry-icon{width:1.7rem;flex:0 0 auto;text-align:center}.entry-size,.entry-date,.entry-kind{font-size:.67rem}.selection-toolbar{position:sticky;top:0;z-index:2;flex-wrap:wrap;padding:.6rem;background:var(--panel-soft);border-bottom:1px solid var(--line)}.list-footer{justify-content:space-between;padding:.6rem 0;font-size:.7rem;color:var(--muted)}.scan-result{margin:.65rem 0;padding:.65rem;border:1px solid var(--line);border-radius:.65rem;font-size:.72rem}.scan-result ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));gap:.35rem;margin-top:.45rem}.scan-result li{justify-content:space-between;padding:.35rem;background:var(--panel-soft);border-radius:.45rem}.ready{color:var(--success)}.failed{color:var(--danger)}.sync-panel{display:flex;align-items:end;gap:.6rem;margin-top:.65rem;padding:.7rem;border:1px solid var(--line);border-radius:.65rem}.sync-panel>div{flex:1}.sync-panel h3{margin:0;font-size:.8rem}.sync-panel p{margin:.2rem 0;font-size:.68rem}.sync-panel label{display:grid;gap:.25rem;font-size:.68rem}.empty-state{padding:1.2rem;text-align:center;color:var(--muted);font-size:.75rem}.modal-backdrop{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:1rem;background:#070b12a6;animation:fade-in .16s ease-out}.modal-card{display:grid;width:min(100%,35rem);max-height:min(90vh,52rem);gap:.8rem;overflow:auto;padding:1rem;border:1px solid var(--line);border-radius:1rem;background:var(--panel);box-shadow:0 24px 80px #0008;animation:modal-in .2s ease-out}.modal-wide{width:min(100%,48rem)}.modal-detail{width:min(100%,38rem)}.modal-heading{display:flex;justify-content:space-between;align-items:center;gap:.5rem}.modal-heading h2{margin:0;font-size:1rem}.modal-card label:not(.confirm-line){display:grid;gap:.3rem;font-size:.72rem;font-weight:700}.modal-actions,.detail-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.45rem;margin-top:.3rem}.confirm-line{display:flex;align-items:flex-start;gap:.5rem;padding:.65rem;border:1px solid var(--line);border-radius:.6rem;font-size:.72rem}.detail-name{text-align:center}.detail-name h3{margin:.4rem 0 0;overflow-wrap:anywhere}.detail-name p{margin:.2rem;color:var(--muted);font-size:.72rem}.detail-grid{display:grid;grid-template-columns:6.5rem minmax(0,1fr);gap:.35rem;margin:0;font-size:.72rem}.detail-grid dt{color:var(--muted)}.detail-grid dd{margin:0;overflow-wrap:anywhere}.sticky-heading{position:sticky;top:-1rem;padding:.7rem 0;background:var(--panel)}.telegram-list.view-grid{grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));padding-top:.5rem}.view-grid .storage-entry{min-height:4.2rem}.notice{padding:.6rem .7rem;border:1px solid var(--line);border-radius:.6rem;font-size:.73rem}.notice-warning{background:var(--warning-soft);color:var(--warning)}.notice-success{background:var(--success-soft);color:var(--success)}.notice-error{background:var(--danger-soft);color:var(--danger)}
@keyframes fade-in{from{opacity:0}to{opacity:1}}@keyframes modal-in{from{opacity:0;transform:translateY(8px) scale(.985)}to{opacity:1;transform:none}}
@media(max-width:700px){.storage-entry{gap:.35rem}.entry-date,.entry-kind{display:none}.link-row{flex-wrap:wrap}.link-main{flex-basis:100%}.sync-panel{align-items:stretch;flex-direction:column}.storage-toolbar{align-items:flex-start}.telegram-list.view-grid{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){.modal-backdrop,.modal-card{animation:none}}
</style>
