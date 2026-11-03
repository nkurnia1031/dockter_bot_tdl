<script lang="ts">
  import { onMount, tick, untrack } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, patch, post, remove } from '$lib/api';
  import { formatBytes, formatDate } from '$lib/presentation';
  import { session } from '$lib/session.svelte';
  import { runtimeReadinessFor, runtimeReadinessForWorker } from '$lib/profile-catalog';
  import WorkspaceExplorer from './WorkspaceExplorer.svelte';
  import TargetPicker from './TargetPicker.svelte';
  import JobTable from './JobTable.svelte';
  import {
    ArchiveRestore, ArrowUp, ChevronRight, CirclePlus, CloudUpload, Download,
    Copy, File, FileArchive, FileImage, FileText, Film, Folder,
    FolderInput, FolderOpen, Grid2X2, HardDrive, Info, LayoutList, MoreVertical,
    Move, Pencil, RefreshCw, Search, Send, Trash2, X
  } from '@lucide/svelte';

  type FolderEntry = {
    id:number; parent_id:number|null; name:string; path:string; status:string;
    updated_at:string; trashed_at?:string|null; file_count?:number;
    folder_count?:number; size_bytes?:number; size_complete?:boolean
  };
  type Item = {
    id:number; display_name:string; original_name:string; folder?:string;
    folder_id?:number|null; keywords?:string; file_size?:number; mime_type?:string;
    owner_user_id?:number; owner_profile?:string; uploaded_at?:string;
    updated_at?:string; status?:string; trashed_at?:string|null;
    caption_sync_status?:string; recovered_at?:string|null;
    recovered_by_user_id?:number|null; recovered_from_profile?:string|null
  };
  type BrowserResponse = {
    current_folder:FolderEntry|null; breadcrumbs:{id:number;name:string}[];
    folders:FolderEntry[]; items:Item[]; total_folders:number; total_items:number
  };
  type RcloneEntry = {id?:string; ambiguous?:boolean; name:string; path:string; is_dir:boolean; size:number|null; updated_at:string; file_count?:number; folder_count?:number; size_bytes?:number; size_complete?:boolean};
  type RcloneBrowserResponse = {path:string; breadcrumbs:string[]; items:RcloneEntry[]; total:number; limit:number; offset:number; trash_supported?:boolean; permanent_delete_supported?:boolean};
  type RcloneSummary = {path:string; file_count:number; folder_count:number; size_bytes:number; size_complete:boolean};
  type PublicDownloadLink = {id:string; worker:string; relative_path:string; file_name:string; provider:string; job_id:string; created_at:string; url:string};
  type StorageScanOperation = {operation_id:string; status:string; phase:string; progress?:Record<string, any>; job_id?:string|null; error?:{code?:string;message?:string}|null};
  type StorageScanProfile = {profile:string; ready:boolean; error_code?:string; checked_at?:string};

  let provider = $state<'telegram'|'rclone'>('telegram');
  let folderId = $state<number|null>(null);
  let scope = $state<'current'|'global'|'recent'|'trash'>('current');
  let query = $state('');
  let sort = $state('name');
  let order = $state('asc');
  let view = $state<'list'|'grid'>('grid');
  let data = $state<BrowserResponse>({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0});
  let folderOptions = $state<FolderEntry[]>([]);
  let selectedItems = $state<number[]>([]);
  let selectedFolders = $state<number[]>([]);
  let selectedRclone = $state<RcloneEntry[]>([]);
  let loading = $state(false);
  let message = $state('');
  let mobileNavOpen = $state(false);
  let createOpen = $state(false);
  let uploadOpen = $state(false);
  let downloadOpen = $state(false);
  let moveOpen = $state(false);
  let editItem = $state<Item|null>(null);
  let editFolder = $state<FolderEntry|null>(null);
  let editRcloneEntry = $state<RcloneEntry|null>(null);
  let detail = $state<Item|null>(null);
  let detailPanel = $state<HTMLElement | undefined>(undefined);
  let detailCloseButton = $state<HTMLButtonElement | undefined>(undefined);
  let detailTrigger: HTMLElement | null = null;
  let confirmAction = $state<'trash'|'purge'|null>(null);
  let newFolderName = $state('');
  let destinationId = $state<number|null>(null);
  let workspaceFolders = $state<string[]>([]);
  let downloadDestinationFolders = $state<string[]>([]);
  let downloadProfile = $state('');
  let publishPublicLinks = $state(false);
  let downloadSubmitting = $state(false);
  let downloadJobWorkers = $state<Record<string,string>>({});
  let publicLinks = $state<PublicDownloadLink[]>([]);
  let publicLinksLoading = $state(false);
  let linkToRevoke = $state<PublicDownloadLink|null>(null);
  let revokeSubmitting = $state(false);
  let keywords = $state('');
  let rclonePath = $state('');
  let rcloneView = $state<'active'|'trash'>('active');
  let rcloneConfirmAction = $state<'copy'|'move'|'trash'|'restore'|'purge'|null>(null);
  let rcloneManageConfirmed = $state(false);
  let rclonePurgeConfirmation = $state('');
  let rcloneManageSubmitting = $state(false);
  let remoteTarget = $state('');
  let remoteTargetSelected = $state(false);
  let remoteQuery = $state('');
  let remoteSort = $state('name');
  let remoteOrder = $state('asc');
  let remoteOffset = $state(0);
  let remoteLoading = $state(false);
  let rcloneMutationSubmitting = $state(false);
  let remoteSummaryLoading = $state(false);
  let remoteSummaryReady = $state(false);
  let remoteSummaryFailed = $state(false);
  let remoteGeneration = 0;
  let remoteSummaryGeneration = 0;
  let remoteSummaries = $state<Record<string, RcloneSummary>>({});
  let remoteData = $state<RcloneBrowserResponse>({path:'',breadcrumbs:[],items:[],total:0,limit:100,offset:0});
  let transferMode = $state<'copy'|'move'>('copy');
  let confirmMove = $state(false);
  let displayName = $state('');
  let editKeywords = $state('');
  let worker = $state('');
  let syncProfile = $state('');
  let syncJobId = $state('');
  let syncSubmitting = $state(false);
  let storageScanOperationId = $state('');
  let storageScanWorker = $state('');
  let storageScanStatus = $state('idle');
  let storageScanMessage = $state('');
  let storageScanError = $state('');
  let storageScanProfiles = $state<StorageScanProfile[]>([]);
  let storageScanTimer: ReturnType<typeof setTimeout> | undefined;
  let storageScanGeneration = 0;
  let storageScanRequestActive = false;

  const selectionCount = $derived(selectedItems.length + selectedFolders.length);
  const activeSelectionCount = $derived(provider === 'telegram' ? selectionCount : selectedRclone.length);
  const storageReadiness = $derived(
    runtimeReadinessForWorker(session.runtimeReadiness, worker, 'storage')
  );
  const storageReadinessCells = $derived(
    session.runtimeReadiness.cells.filter((cell) =>
      cell.worker === worker && cell.runtime === 'storage'
    )
  );
  const workerAdmissionEnabled = $derived(
    session.workers.some((item) => item.name === worker && item.enabled !== false)
  );
  const storageWorkerAvailable = $derived(workerAdmissionEnabled);
  const storageSyncProfiles = $derived(session.current.profiles);
  const rcloneReadiness = $derived(runtimeReadinessFor(session.runtimeReadiness, null, worker, 'rclone_storage'));
  const rcloneWorkerAvailable = $derived(workerAdmissionEnabled);
  const workerPublicUrl = $derived(session.workers.find((item) => item.name === worker)?.public_url || '');
  const downloadProfiles = $derived(workerAdmissionEnabled ? session.current.profiles : []);
  const downloadReadiness = $derived(
    runtimeReadinessFor(session.runtimeReadiness, downloadProfile || null, worker, 'download')
  );
  const storageReadinessStyle = $derived(
    storageReadiness.status === 'ready'
      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200'
      : storageReadiness.status === 'offline' || storageReadiness.status === 'not_ready'
        ? 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-200'
        : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
  );
  const isTrash = $derived(scope === 'trash');
  const currentName = $derived(data.current_folder?.name || (scope === 'trash' ? 'Recycle Bin' : scope === 'recent' ? 'Recent' : scope === 'global' ? 'All Files' : 'My Drive'));

  function openDetail(item: Item, trigger: HTMLElement) {
    detailTrigger = trigger;
    detail = item;
    void tick().then(() => detailCloseButton?.focus());
  }
  function closeDetail() {
    const trigger = detailTrigger;
    detail = null;
    void tick().then(() => {
      if (trigger?.isConnected) trigger.focus();
      detailTrigger = null;
    });
  }
  function handleDetailKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDetail();
      return;
    }
    if (event.key !== 'Tab' || !detailPanel) return;

    const focusable = Array.from(detailPanel.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((element) => element.getAttribute('aria-hidden') !== 'true');
    if (!focusable.length) {
      event.preventDefault();
      detailPanel.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === detailPanel || !detailPanel.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || active === detailPanel || !detailPanel.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  }

  function urlFolder() {
    const value = new URLSearchParams(location.search).get('folder');
    return value && value !== 'root' ? Number(value) : null;
  }
  function updateUrl() {
    const params = new URLSearchParams(location.search);
    if (scope === 'current' && folderId !== null) params.set('folder', String(folderId));
    else params.delete('folder');
    history.replaceState({}, '', `${location.pathname}${params.size ? `?${params}` : ''}`);
  }
  async function load() {
    loading = true;
    try {
      const params = new URLSearchParams({
        folder_id: folderId === null ? 'root' : String(folderId), scope, q: query,
        sort, order, limit: '100', offset: '0'
      });
      data = await api<BrowserResponse>(`/storage/browser?${params}`);
      folderOptions = (await api<{items:FolderEntry[]}>('/storage/folders/tree')).items || [];
      message = '';
      updateUrl();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Storage tidak dapat dimuat.';
    } finally { loading = false; }
  }
  async function syncTelegramCatalog() {
    if (!worker || !storageSyncProfiles.includes(syncProfile) || syncSubmitting) return;
    syncSubmitting = true;
    message = '';
    try {
      const job = await post<{id:string}>('/storage/sync', {worker, profile:syncProfile});
      syncJobId = job.id;
      message = `Sinkronisasi channel Telegram masuk antrean untuk profil ${syncProfile}.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Sinkronisasi Storage gagal dibuat.';
    } finally {
      syncSubmitting = false;
    }
  }
  function stopStorageScanPolling() {
    if (storageScanTimer !== undefined) clearTimeout(storageScanTimer);
    storageScanTimer = undefined;
    storageScanRequestActive = false;
  }
  function scheduleStorageScanPolling(operationId:string, selectedWorker:string, generation:number) {
    if (storageScanTimer !== undefined) clearTimeout(storageScanTimer);
    storageScanTimer = setTimeout(() => void refreshStorageScan(operationId, selectedWorker, generation), 900);
  }
  async function refreshStorageScan(operationId:string, selectedWorker:string, generation:number) {
    if (storageScanRequestActive) {
      scheduleStorageScanPolling(operationId, selectedWorker, generation);
      return;
    }
    storageScanRequestActive = true;
    try {
      const operation = await api<StorageScanOperation>(`/operations/${encodeURIComponent(operationId)}`);
      if (generation !== storageScanGeneration) return;
      storageScanStatus = operation.status;
      storageScanOperationId = operation.operation_id;
      const overall = operation.progress?.overall && typeof operation.progress.overall === 'object'
        ? operation.progress.overall as Record<string, unknown> : {};
      const current = Number(overall.current || 0);
      const total = Number(overall.total || 0);
      storageScanMessage = total
        ? `${operation.progress?.message || operation.phase}: ${current}/${total} profil`
        : String(operation.progress?.message || operation.phase || 'Memeriksa profil worker…');
      if (['succeeded','failed','cancelled'].includes(operation.status)) {
        if (operation.status === 'succeeded') {
          const result = await api<{profiles?:StorageScanProfile[]}>(`/tdl-access/verification?purpose=storage&worker=${encodeURIComponent(selectedWorker)}`);
          if (generation !== storageScanGeneration) return;
          storageScanProfiles = Array.isArray(result.profiles) ? result.profiles : [];
          storageScanError = '';
          storageScanMessage = `Pemeriksaan selesai: ${storageScanProfiles.filter((item)=>item.ready).length}/${storageScanProfiles.length} profil dapat mengirim ke Storage.`;
          void session.refreshProfileCatalog();
        } else {
          storageScanError = operation.error?.message || `Pemeriksaan berakhir dengan status ${operation.status}.`;
        }
        stopStorageScanPolling();
      } else {
        scheduleStorageScanPolling(operationId, selectedWorker, generation);
      }
    } catch (cause) {
      if (generation === storageScanGeneration) {
        storageScanError = cause instanceof Error ? cause.message : 'Progress scan Storage tidak dapat dimuat.';
        scheduleStorageScanPolling(operationId, selectedWorker, generation);
      }
    } finally {
      storageScanRequestActive = false;
    }
  }
  async function scanStorageWorker() {
    if (!worker || !storageWorkerAvailable || storageScanStatus === 'queued' || storageScanStatus === 'running') return;
    stopStorageScanPolling();
    const selectedWorker = worker;
    const generation = ++storageScanGeneration;
    storageScanWorker = selectedWorker;
    storageScanStatus = 'queued';
    storageScanProfiles = [];
    storageScanError = '';
    storageScanMessage = 'Menyiapkan pemeriksaan profil Storage…';
    try {
      const key = globalThis.crypto?.randomUUID?.() || `storage-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const operation = await api<StorageScanOperation>('/tdl-access/verification', {
        method: 'POST',
        headers: {'Idempotency-Key': key},
        body: JSON.stringify({purpose:'storage',worker:selectedWorker})
      });
      if (generation !== storageScanGeneration) return;
      storageScanOperationId = operation.operation_id;
      storageScanStatus = operation.status;
      if (['succeeded','failed','cancelled'].includes(operation.status)) {
        await refreshStorageScan(operation.operation_id, selectedWorker, generation);
      } else {
        storageScanMessage = 'Scan worker berjalan; menguji profil satu per satu…';
        scheduleStorageScanPolling(operation.operation_id, selectedWorker, generation);
      }
    } catch (cause) {
      if (generation === storageScanGeneration) {
        storageScanStatus = 'failed';
        storageScanError = cause instanceof Error ? cause.message : 'Scan Storage gagal dimulai.';
      }
    }
  }
  async function handleJobFinished(event: Event) {
    void session.refreshProfileCatalog();
    const finishedIds = (event as CustomEvent<{jobIds?:string[]}>).detail?.jobIds || [];
    const finishedDownloads = finishedIds.filter((id) => Boolean(downloadJobWorkers[id]));
    if (finishedDownloads.length) {
      const workersToRefresh = new Set(finishedDownloads.map((id) => downloadJobWorkers[id]));
      const summaries = await Promise.all(finishedDownloads.map(async (id) => {
        try {
          const job = await api<{status:string; result?:{value?:{succeeded?:number;failed?:number;cancelled_items?:number;public_links_failed?:number}}; error?:{message?:string}}>(`/jobs/${encodeURIComponent(id)}`);
          const result = job.result?.value;
          return `Unduhan ${job.status}: ${result?.succeeded ?? 0} berhasil, ${result?.failed ?? 0} gagal, ${result?.cancelled_items ?? 0} dibatalkan. Link gagal: ${result?.public_links_failed ?? 0}.${job.error?.message ? ` ${job.error.message}` : ''}`;
        } catch (cause) {
          return cause instanceof Error ? cause.message : `Hasil unduhan ${id.slice(0, 8)} tidak dapat dimuat.`;
        } finally {
          delete downloadJobWorkers[id];
        }
      }));
      if (workersToRefresh.has(worker)) await loadPublicLinks(worker);
      message = summaries.join(' ');
    }
    if (!syncJobId || !finishedIds.includes(syncJobId)) return;
    const finishedJobId = syncJobId;
    try {
      const job = await api<{status:string; result?:Record<string, any>; error?:{message?:string}}>(`/jobs/${encodeURIComponent(finishedJobId)}`);
      if (job.status === 'succeeded') {
        await load();
        const catalog = job.result?.value?.catalog;
        if (catalog) {
          const historyComplete = job.result?.value?.history_complete === true;
          message = `Sinkronisasi selesai: ${catalog.recovered || 0} dipulihkan, ${catalog.updated || 0} diperbarui, ${catalog.restored || 0} dari Trash dipulihkan, ${catalog.deleted || 0} dihapus, ${catalog.deletion_held || 0} penghapusan ditahan. ${historyComplete ? 'Riwayat lengkap.' : 'Riwayat belum terbukti lengkap; item yang tidak ditemukan dipertahankan.'}`;
        } else {
          message = 'Sinkronisasi katalog Telegram selesai.';
        }
      } else {
        message = job.error?.message || `Sinkronisasi berakhir dengan status ${job.status}.`;
      }
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Hasil sinkronisasi tidak dapat dimuat.';
    }
  }
  function openFolder(id:number|null) {
    folderId = id; scope = 'current'; clearSelection(); load();
  }
  function chooseScope(next:typeof scope) {
    scope = next; folderId = null; clearSelection(); load();
  }
  function clearSelection() { selectedItems = []; selectedFolders = []; }
  function clearRcloneSelection() { selectedRclone = []; }
  function toggleRcloneEntry(entry:RcloneEntry) {
    if (entry.ambiguous) return;
    selectedRclone = selectedRclone.some((item) => item.path === entry.path)
      ? selectedRclone.filter((item) => item.path !== entry.path)
      : [...selectedRclone, entry];
  }
  function selectAllRclone() {
    const selected = new Map(selectedRclone.map((entry) => [entry.path, entry]));
    for (const entry of remoteData.items) if (!entry.ambiguous) selected.set(entry.path, entry);
    selectedRclone = [...selected.values()];
  }
  function toggleItem(id:number) {
    selectedItems = selectedItems.includes(id) ? selectedItems.filter(value => value !== id) : [...selectedItems,id];
  }
  function toggleFolder(id:number) {
    selectedFolders = selectedFolders.includes(id) ? selectedFolders.filter(value => value !== id) : [...selectedFolders,id];
  }
  function selectAll() {
    selectedItems = data.items.map(item => item.id);
    selectedFolders = data.folders.map(folder => folder.id);
  }
  function emptyTrash() {
    selectAll();
    confirmAction='purge';
  }
  async function createFolder() {
    if (provider === 'rclone') {
      if (!worker || !newFolderName.trim()) return;
      await submitRcloneMutation('create_folder', rclonePath, newFolderName);
      createOpen=false; newFolderName='';
      return;
    }
    await post('/storage/folders', {name:newFolderName,parent_id:folderId});
    createOpen=false; newFolderName=''; await load();
  }
  async function renameFolder() {
    if (!editFolder) return;
    await patch(`/storage/folders/${editFolder.id}`, {name:newFolderName});
    editFolder=null; newFolderName=''; await load();
  }
  function beginRcloneRename(entry:RcloneEntry) {
    editRcloneEntry=entry;
    newFolderName=entry.name;
  }
  async function renameRcloneEntry() {
    if (!editRcloneEntry || !newFolderName.trim()) return;
    await submitRcloneMutation('rename', editRcloneEntry.path, newFolderName);
    editRcloneEntry=null; newFolderName='';
  }
  async function submitRcloneMutation(action:'create_folder'|'rename', path:string, name:string) {
    if (!worker || rcloneMutationSubmitting) return;
    rcloneMutationSubmitting=true;
    try {
      const result=await post<{path:string}>('/storage/rclone/actions', {
        worker, action, path, name:name.trim()
      });
      await loadRclone({refreshSummaries:true});
      message=action==='create_folder'
        ? 'Folder rclone dibuat: '+result.path
        : 'Rename rclone berhasil: '+result.path;
    } catch (cause) {
      message=cause instanceof Error?cause.message:'Operasi rclone gagal.';
    } finally {
      rcloneMutationSubmitting=false;
    }
  }
  function openRcloneTrash() {
    rcloneView='trash';
    remoteOffset=0;
    clearRcloneSelection();
    void loadRclone();
  }
  function openRcloneActive() {
    rcloneView='active';
    remoteOffset=0;
    clearRcloneSelection();
    void loadRclone({refreshSummaries:true});
  }
  function requestRcloneManage(action:'copy'|'move'|'trash'|'restore'|'purge') {
    if (!selectedRclone.length || !worker) return;
    rcloneManageConfirmed=false;
    rclonePurgeConfirmation='';
    rcloneConfirmAction=action;
  }
  async function confirmRcloneManage() {
    if (!rcloneConfirmAction || !worker || !selectedRclone.length || rcloneManageSubmitting) return;
    const action=rcloneConfirmAction;
    if (action==='move'&&!rcloneManageConfirmed) return;
    if (action==='purge'&&rclonePurgeConfirmation!=='HAPUS') return;
    rcloneManageSubmitting=true;
    try {
      const job=await post<{id:string}>('/storage/rclone/jobs', {
        worker,
        action,
        sources:selectedRclone.map(({path,is_dir,id})=>({path,is_dir,...(id?{id}:{})})),
        destination_path:['copy','move'].includes(action)?rclonePath:'',
        trashed:rcloneView==='trash' && ['restore','purge'].includes(action),
        confirmed:action==='purge'
      });
      rcloneConfirmAction=null;
      clearRcloneSelection();
      message=`Operasi rclone ${action} masuk Activity sebagai job ${job.id.slice(0,8)}.`;
      window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
      await loadRclone({refreshSummaries:rcloneView==='active'});
    } catch (cause) {
      message=cause instanceof Error?cause.message:'Operasi rclone tidak dapat dibuat.';
    } finally {
      rcloneManageSubmitting=false;
    }
  }
  async function saveItem() {
    if (!editItem) return;
    await patch(`/storage/items/${editItem.id}`, {display_name:displayName,keywords:editKeywords});
    editItem=null; await load();
  }
  async function moveSelection() {
    await post('/storage/actions/move', {
      item_ids:selectedItems,folder_ids:selectedFolders,destination_folder_id:destinationId
    });
    moveOpen=false; clearSelection(); await load();
  }
  async function trashOrPurge() {
    if (confirmAction === 'purge') {
      await post('/storage/actions/purge', {item_ids:selectedItems,folder_ids:selectedFolders});
    } else {
      await post('/storage/actions/trash', {item_ids:selectedItems,folder_ids:selectedFolders});
    }
    confirmAction=null; clearSelection(); await load();
  }
  async function restoreSelection() {
    await post('/storage/actions/restore', {item_ids:selectedItems,folder_ids:selectedFolders});
    clearSelection(); await load();
  }
  async function upload() {
    if (!workspaceFolders[0]) return;
    if (!worker || !workerAdmissionEnabled) {
      message = 'Pilih worker aktif untuk menjalankan upload.';
      return;
    }
    if (provider === 'rclone' && transferMode === 'move' && !confirmMove) return;
    const selectedTransferMode=transferMode;
    await post('/storage/uploads', {
      folder_path:workspaceFolders[0], destination_folder_id:provider==='telegram'?destinationId:null,
      provider, rclone_path:provider==='rclone'?remoteTarget:'', transfer_mode:transferMode,
      preserve_structure:true, keywords, worker, move_confirmed:transferMode==='move'&&confirmMove
    });
    uploadOpen=false; workspaceFolders=[]; keywords=''; transferMode='copy'; confirmMove=false;
    message=`Upload ${provider==='telegram'?'Telegram':'rclone'} masuk antrean sebagai ${selectedTransferMode}. Struktur subfolder akan dipertahankan.`;
  }
  function startDownload() {
    if (provider === 'telegram') downloadProfile = downloadProfiles[0] || '';
    downloadDestinationFolders = [];
    publishPublicLinks = false;
    downloadOpen = true;
  }
  async function downloadSelection() {
    const destinationPath = downloadDestinationFolders[0];
    if (!worker || !destinationPath || downloadSubmitting) return;
    if (!workerAdmissionEnabled) {
      message = 'Pilih worker aktif untuk menjalankan download.';
      return;
    }
    if (provider === 'telegram' && (!downloadProfile || !downloadProfiles.includes(downloadProfile))) {
      message = 'Pilih profil yang dapat Anda gunakan untuk mencoba download.';
      return;
    }
    if (provider === 'rclone' && !selectedRclone.length) {
      message = 'Pilih file atau folder rclone.';
      return;
    }
    downloadSubmitting = true;
    try {
      const body = provider === 'telegram'
        ? {provider, worker, profile:downloadProfile, item_ids:selectedItems, folder_ids:selectedFolders, destination_path:destinationPath, publish_public_links:publishPublicLinks}
        : {provider, worker, rclone_sources:selectedRclone.map(({path,is_dir,size})=>({path,is_dir,size})), destination_path:destinationPath, publish_public_links:publishPublicLinks};
      const job = await post<{id:string}>('/storage/downloads', body);
      downloadJobWorkers = {...downloadJobWorkers, [job.id]:worker};
      downloadOpen = false;
      downloadDestinationFolders = [];
      clearSelection();
      clearRcloneSelection();
      message = `Unduhan masuk antrean pada worker ${worker}. Progress per file tersedia di bawah.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Unduhan Storage gagal dibuat.';
    } finally {
      downloadSubmitting = false;
    }
  }
  async function loadPublicLinks(selectedWorker = worker) {
    if (!selectedWorker) { publicLinks = []; return; }
    publicLinksLoading = true;
    try {
      const result = await api<{items:PublicDownloadLink[]}>(`/storage/download-links?worker=${encodeURIComponent(selectedWorker)}`);
      if (worker === selectedWorker) publicLinks = Array.isArray(result.items) ? result.items : [];
    } catch (cause) {
      if (worker === selectedWorker) {
        publicLinks = [];
        message = cause instanceof Error ? cause.message : 'Daftar link publik tidak dapat dimuat.';
      }
    } finally { publicLinksLoading = false; }
  }
  async function copyPublicLink(link:PublicDownloadLink) {
    await navigator.clipboard.writeText(link.url);
    message = `Link ${link.file_name} disalin.`;
  }
  async function revokePublicLink() {
    if (!linkToRevoke || revokeSubmitting) return;
    revokeSubmitting = true;
    try {
      const link = linkToRevoke;
      const result = await post<{cleanup_status:string}>(`/storage/download-links/${encodeURIComponent(link.id)}/revoke?worker=${encodeURIComponent(link.worker)}`, {confirmed:true});
      linkToRevoke = null;
      await loadPublicLinks(worker);
      message = result.cleanup_status === 'deleted' || result.cleanup_status === 'already_missing'
        ? 'Link dicabut dan file worker dihapus.'
        : `Link dicabut; penghapusan file worker berstatus ${result.cleanup_status}.`;
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Link publik tidak dapat dicabut.';
    } finally { revokeSubmitting = false; }
  }
  async function loadRclone({refreshSummaries=false}:{refreshSummaries?:boolean}={}) {
    if (!worker || provider !== 'rclone' || !rcloneWorkerAvailable) return;
    const request=++remoteGeneration;
    const selectedWorker=worker;
    const selectedPath=rclonePath;
    const selectedView=rcloneView;
    remoteLoading=true;
    try {
      if (selectedView==='trash') {
        const params=new URLSearchParams({worker:selectedWorker,limit:'100',offset:String(remoteOffset)});
        const response=await api<{supported:boolean;permanent_delete_supported?:boolean;items:RcloneEntry[];total:number;limit:number;offset:number}>(`/storage/rclone/trash?${params}`);
        if (request!==remoteGeneration || provider!=='rclone' || worker!==selectedWorker || rcloneView!==selectedView) return;
        remoteData={path:'',breadcrumbs:[],items:response.items||[],total:response.total||0,limit:response.limit||100,offset:response.offset||0,trash_supported:response.supported,permanent_delete_supported:response.permanent_delete_supported};
        remoteSummaries={};
        message=response.supported?'':response.permanent_delete_supported
          ?'Trash remote tidak dapat dikelola dari sini; penghapusan permanen tersedia sebagai tindakan terpisah.'
          :'Trash remote tidak dapat dikelola dari sini dan semantik hapus permanen backend belum dapat dipastikan.';
        return;
      }
      const params=new URLSearchParams({worker:selectedWorker,path:selectedPath,q:remoteQuery,sort:remoteSort,order:remoteOrder,limit:'100',offset:String(remoteOffset)});
      const response=await api<RcloneBrowserResponse>(`/storage/rclone/browser?${params}`);
      if (request!==remoteGeneration || provider!=='rclone' || worker!==selectedWorker || rclonePath!==selectedPath || rcloneView!==selectedView) return;
      remoteData=response;
      message='';
      if (refreshSummaries) void loadRcloneSummaries(selectedWorker, selectedPath);
    } catch (cause) { message=cause instanceof Error?cause.message:'Remote rclone tidak dapat dimuat.'; }
    finally { if (request===remoteGeneration) remoteLoading=false; }
  }
  async function loadRcloneSummaries(selectedWorker:string, selectedPath:string) {
    const request=++remoteSummaryGeneration;
    remoteSummaries={};
    remoteSummaryFailed=false;
    remoteSummaryReady=false;
    remoteSummaryLoading=true;
    try {
      const params=new URLSearchParams({worker:selectedWorker,path:selectedPath});
      const response=await api<{summaries:RcloneSummary[]}>(`/storage/rclone/folder-summaries?${params}`);
      if (request!==remoteSummaryGeneration || provider!=='rclone' || worker!==selectedWorker || rclonePath!==selectedPath) return;
      remoteSummaries=Object.fromEntries((response.summaries||[]).map((item)=>[item.path,item]));
      remoteSummaryReady=true;
    } catch {
      if (request===remoteSummaryGeneration) remoteSummaryFailed=true;
    } finally {
      if (request===remoteSummaryGeneration) remoteSummaryLoading=false;
    }
  }
  function setProvider(next:'telegram'|'rclone') {
    provider=next;
    remoteGeneration++;
    remoteSummaryGeneration++;
    remoteSummaries={};
    remoteSummaryLoading=false;
    remoteSummaryFailed=false;
    remoteSummaryReady=false;
    clearSelection(); clearRcloneSelection();
    if (next==='rclone') { rclonePath=''; rcloneView='active'; remoteOffset=0; remoteTarget=''; remoteTargetSelected=false; }
    else void load();
  }
  function handleWorkerChange() {
    storageScanGeneration++;
    stopStorageScanPolling();
    storageScanOperationId='';
    storageScanWorker='';
    storageScanStatus='idle';
    storageScanMessage='';
    storageScanError='';
    storageScanProfiles=[];
    remoteGeneration++;
    remoteSummaryGeneration++;
    remoteSummaries={};
    remoteSummaryLoading=false;
    remoteSummaryFailed=false;
    remoteSummaryReady=false;
    rclonePath=''; rcloneView='active'; remoteOffset=0; remoteTarget=''; remoteTargetSelected=false;
    clearRcloneSelection();
    publicLinks=[];
    remoteData={path:'',breadcrumbs:[],items:[],total:0,limit:100,offset:0};
  }
  function openRemoteFolder(path:string) {
    rcloneView='active';
    remoteSummaryGeneration++;
    remoteSummaries={};
    remoteSummaryLoading=false;
    remoteSummaryReady=false;
    remoteSummaryFailed=false;
    rclonePath=path;
    remoteOffset=0;
    remoteTarget=path;
    void loadRclone({refreshSummaries:true});
  }
  async function deliver(item:Item) {
    await post(`/storage/items/${item.id}/deliveries`, {method:'telegram'});
    message=`${item.display_name} dikirim ke Telegram.`;
  }
  async function copyFileCode(item:Item) {
    const result=await api<{code:string}>(`/storage/items/${item.id}/deep-link`);
    await navigator.clipboard.writeText(result.code);
    message=`Kode ${item.display_name} disalin. Buka bot, pilih Panggil file dengan kode, lalu tempel kode tersebut.`;
  }
  function startUpload() { if (provider==='telegram') destinationId=folderId; else if (!remoteTargetSelected) {remoteTarget=rclonePath;remoteTargetSelected=true;} transferMode='copy'; confirmMove=false; uploadOpen=true; }
  function startMove() { destinationId=folderId; moveOpen=true; }
  function beginItemEdit(item:Item) {
    editItem=item; displayName=item.display_name; editKeywords=item.keywords || '';
  }
  function beginFolderEdit(folder:FolderEntry) {
    editFolder=folder; newFolderName=folder.name;
  }
  function iconFor(item:Item) {
    if (item.mime_type?.startsWith('image/')) return FileImage;
    if (item.mime_type?.startsWith('video/')) return Film;
    if (/zip|7z|rar|tar|gzip/.test(item.mime_type || item.display_name)) return FileArchive;
    if (/text|json|pdf|document/.test(item.mime_type || '')) return FileText;
    return File;
  }
  function dropOnFolder(event:DragEvent, target:number|null) {
    event.preventDefault();
    const payload=event.dataTransfer?.getData('application/x-tme3-storage');
    if (!payload) return;
    const parsed=JSON.parse(payload);
    post('/storage/actions/move', {
      item_ids:parsed.kind==='item'?[parsed.id]:[],
      folder_ids:parsed.kind==='folder'?[parsed.id]:[],
      destination_folder_id:target
    }).then(load).catch(cause => message=cause instanceof Error?cause.message:'Move gagal.');
  }
  function drag(event:DragEvent,kind:'item'|'folder',id:number) {
    event.dataTransfer?.setData('application/x-tme3-storage',JSON.stringify({kind,id}));
  }

  onMount(() => {
    folderId=urlFolder();
    view=(localStorage.getItem('storage-view') as 'list'|'grid') || 'grid';
    sort=localStorage.getItem('storage-sort') || 'name';
    void session.refreshProfileCatalog();
    window.addEventListener('tme3:job-finished', handleJobFinished);
    load();
    return () => {
      window.removeEventListener('tme3:job-finished', handleJobFinished);
      storageScanGeneration++;
      stopStorageScanPolling();
    };
  });
  $effect(() => {
    if (!storageSyncProfiles.includes(syncProfile)) syncProfile = storageSyncProfiles[0] || '';
  });
  $effect(() => {
    const activeProvider=provider;
    const activeWorker=worker;
    const available=rcloneWorkerAvailable;
    if (activeProvider==='rclone' && activeWorker && available) untrack(() => void loadRclone({refreshSummaries:true}));
  });
  $effect(() => {
    const selectedWorker=worker;
    if (selectedWorker) untrack(() => void loadPublicLinks(selectedWorker));
  });
  function setView(next:'list'|'grid') { view=next; localStorage.setItem('storage-view',next); }
  function setSort(next:string) { sort=next; localStorage.setItem('storage-sort',next); load(); }
</script>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">STORAGE</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Cloud Storage</h1><p class="muted mt-2">{provider==='telegram'?'Kelola katalog Telegram seperti file hosting—folder bersama untuk seluruh user.':'Jelajahi remote rclone pada worker terpilih dan pilih tujuan upload.'}</p></div>
  <div class="page-icon"><HardDrive size={23}/></div>
</header>

<div class="mt-5"><TargetPicker purpose="storage" requireProfile={false} requiresVerification={false} readinessRuntime={provider==='telegram'?'storage':'rclone_storage'} allowDisabledWorkerSelection bind:worker onWorkerChange={handleWorkerChange} /></div>

<div class="mt-4 inline-flex rounded-xl border border-[var(--line)] p-1" role="tablist" aria-label="Sumber Storage">
  <button role="tab" aria-selected={provider==='telegram'} class={`rounded-lg px-4 py-2 text-sm font-bold ${provider==='telegram'?'bg-[var(--brand-soft)] text-[var(--brand)]':''}`} onclick={() => setProvider('telegram')}>Telegram</button>
  <button role="tab" aria-selected={provider==='rclone'} class={`rounded-lg px-4 py-2 text-sm font-bold ${provider==='rclone'?'bg-[var(--brand-soft)] text-[var(--brand)]':''}`} onclick={() => setProvider('rclone')}>Rclone</button>
</div>

<section class="card mt-4 p-4 sm:p-5" aria-label="Link publik Storage">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div><h2 class="font-extrabold">Link unduhan publik</h2><p class="muted mt-1 text-sm">Link aktif tidak kedaluwarsa. Cabut link untuk menonaktifkannya dan menghapus file dari worker.</p></div>
    <button class="button secondary" disabled={!worker || publicLinksLoading} onclick={() => loadPublicLinks()}><RefreshCw size={15} class={publicLinksLoading?'animate-spin':''}/>Refresh link</button>
  </div>
  {#if publicLinks.length}
    <ul class="mt-4 divide-y divide-[var(--line)] rounded-xl border border-[var(--line)]">
      {#each publicLinks as link (link.id)}
        <li class="flex flex-wrap items-center gap-3 p-3 text-sm">
          <div class="min-w-0 flex-1"><b class="block truncate">{link.file_name}</b><span class="muted">{link.provider} · {formatDate(link.created_at)} · {link.worker}</span><span class="muted mt-1 block break-all text-xs">{link.relative_path}</span><a class="mt-1 block truncate text-violet-700 underline dark:text-violet-300" href={link.url} target="_blank" rel="noreferrer">{link.url}</a></div>
          <button class="button secondary" onclick={() => copyPublicLink(link)}><Copy size={15}/>Salin link</button>
          <button class="button danger" onclick={() => linkToRevoke=link}>Cabut & hapus file</button>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted mt-4 rounded-xl border border-dashed border-[var(--line)] p-5 text-center text-sm">{publicLinksLoading?'Memuat link worker…':'Belum ada link publik aktif pada worker ini.'}</p>
  {/if}
</section>

{#if provider==='telegram'}
<section class="card mt-4 p-4 sm:p-5">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div>
      <h2 class="font-extrabold">Kesiapan Storage</h2>
      <p class="muted mt-1 text-sm">Status scan hanya informasi. Upload akan mencoba profil lokal pada worker ini dan menilai hasil command TDL.</p>
    </div>
    <div class="flex items-center gap-2">
    <button class="button secondary" onclick={scanStorageWorker} disabled={!storageWorkerAvailable || storageScanStatus==='queued' || storageScanStatus==='running'}>
      <RefreshCw size={15} class={storageScanStatus==='queued' || storageScanStatus==='running'?'animate-spin':''}/>{storageScanStatus==='queued' || storageScanStatus==='running'?'Memindai worker…':'Scan worker'}
    </button>
    <span class={`rounded-full px-3 py-1 text-xs font-bold ${storageReadinessStyle}`} role="status">
      {storageReadiness.status === 'ready' ? 'Scan: siap' : storageReadiness.status === 'offline' ? 'Scan: worker offline' : storageReadiness.status === 'disabled' ? 'Worker nonaktif' : storageReadiness.status === 'not_ready' ? 'Scan: tidak siap' : 'Belum di-scan'}
    </span>
    </div>
  </div>
  {#if storageScanWorker===worker && storageScanStatus!=='idle'}
    <div class="mt-3 rounded-xl border border-[var(--line)] p-3 text-sm" role="status" aria-label="Progress scan Storage">
      <p>{storageScanMessage || 'Memeriksa worker…'}</p>
      {#if storageScanError}<p class="mt-1 text-rose-700">{storageScanError}</p>{/if}
      {#if storageScanProfiles.length}
        <ul class="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {#each storageScanProfiles as result (result.profile)}
            <li class="flex justify-between gap-2 rounded-md bg-[var(--surface-soft)] px-2 py-1"><span>{result.profile}</span><b class={result.ready?'text-emerald-600':'text-rose-600'}>{result.ready?'Siap':result.error_code || 'Gagal'}</b></li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
  {#if storageReadinessCells.length}
    <ul class="mt-3 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {#each storageReadinessCells as cell (`${cell.worker}:${cell.profile}:${cell.runtime}`)}
        {@const pair = runtimeReadinessFor(session.runtimeReadiness, cell.profile, cell.worker, 'storage')}
        <li class="flex items-center justify-between gap-2 rounded-lg border border-[var(--line)] p-2" aria-label={`Storage ${cell.profile} pada ${cell.worker}`}>
          <b>{cell.profile}</b>
          <span class={pair.status === 'ready' ? 'font-bold text-emerald-600' : pair.status === 'offline' || pair.status === 'not_ready' ? 'font-bold text-rose-600' : 'muted font-bold'}>{pair.status === 'ready' ? 'Scan: siap' : pair.status === 'not_ready' ? `Scan: tidak siap · ${pair.reason_code}` : pair.status === 'offline' ? 'Scan: worker offline' : pair.status === 'disabled' ? 'Worker nonaktif' : 'Belum di-scan'}</span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="muted mt-3 text-sm">Belum ada hasil scan Storage untuk worker ini.</p>
  {/if}
  {#if storageReadiness.status !== 'ready'}
    <p class="muted mt-3 text-xs">Hasil scan hanya informasi. Job tetap dapat dicoba; command TDL aktual menentukan hasilnya.</p>
  {/if}
  <div class="mt-4 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-3 sm:p-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="min-w-[220px] flex-1">
        <h3 class="font-bold">Sinkronkan katalog dari Telegram</h3>
        <p class="muted mt-1 text-sm">Ekspor metadata channel Storage, cocokkan message ID, lalu perbarui katalog. Tidak mengunduh media.</p>
      </div>
      <label class="text-sm font-semibold">Profil sumber
        <select class="field mt-1 min-w-44" bind:value={syncProfile} disabled={!storageSyncProfiles.length}>
          {#each storageSyncProfiles as profile (profile)}<option value={profile}>{profile}</option>{/each}
        </select>
      </label>
      <button class="button" onclick={syncTelegramCatalog} disabled={!worker || !storageSyncProfiles.includes(syncProfile) || syncSubmitting}>
        <RefreshCw size={16} class={syncSubmitting?'animate-spin':''}/>{syncSubmitting?'Menyiapkan…':'Sinkronkan sekarang'}
      </button>
    </div>
    {#if !storageSyncProfiles.length}<p class="muted mt-2 text-xs">Tidak ada profil yang diizinkan untuk akun ini.</p>{/if}
  </div>
</section>
{/if}

{#if message}<div class="mt-5 flex items-center justify-between rounded-2xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-100"><span>{message}</span><button onclick={() => message=''}><X size={16}/></button></div>{/if}

{#if provider==='rclone'}
<section class="card mt-6 overflow-hidden p-4 sm:p-5" aria-label="Browser rclone">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div><h2 class="text-xl font-black">Remote rclone</h2><p class="muted mt-1 text-sm">Worker {worker || 'belum dipilih'} · status {rcloneReadiness.status}</p></div>
    <div class="flex flex-wrap gap-2">
      {#if selectedRclone.length}<button class="button secondary" disabled={!rcloneWorkerAvailable} onclick={startDownload}><Download size={16}/>Download {selectedRclone.length} dipilih</button>{/if}
      {#if selectedRclone.length && rcloneView==='active'}
        <button class="button secondary" disabled={!rcloneWorkerAvailable || rcloneManageSubmitting} onclick={() => requestRcloneManage('copy')}><Copy size={16}/>Copy ke sini</button>
        <button class="button secondary" disabled={!rcloneWorkerAvailable || rcloneManageSubmitting} onclick={() => requestRcloneManage('move')}><Move size={16}/>Move ke sini</button>
        <button class="button danger" disabled={!rcloneWorkerAvailable || rcloneManageSubmitting || (!remoteData.trash_supported&&!remoteData.permanent_delete_supported)} onclick={() => requestRcloneManage(remoteData.trash_supported?'trash':'purge')}><Trash2 size={16}/>{remoteData.trash_supported?'Pindahkan ke Trash':remoteData.permanent_delete_supported?'Hapus permanen':'Hapus tidak didukung'}</button>
      {:else if selectedRclone.length && rcloneView==='trash'}
        <button class="button secondary" disabled={!rcloneWorkerAvailable || rcloneManageSubmitting || !remoteData.trash_supported} onclick={() => requestRcloneManage('restore')}><ArchiveRestore size={16}/>Pulihkan</button>
        <button class="button danger" disabled={!rcloneWorkerAvailable || rcloneManageSubmitting || !remoteData.trash_supported || !remoteData.permanent_delete_supported} onclick={() => requestRcloneManage('purge')}><Trash2 size={16}/>Hapus permanen</button>
      {/if}
      {#if rcloneView==='active'}
        <button class="button secondary" disabled={!rcloneWorkerAvailable || rcloneMutationSubmitting} onclick={() => {newFolderName='';createOpen=true}}><CirclePlus size={16}/>Folder baru</button>
        <button class="button" disabled={!rcloneWorkerAvailable} onclick={startUpload}><CloudUpload size={16}/>Upload ke folder ini</button>
      {/if}
    </div>
  </div>
  {#if rcloneReadiness.status !== 'ready'}<p class="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-100">Hasil scan rclone: {rcloneReadiness.reason_code || rcloneReadiness.status}. Daftar remote akan menguji command rclone aktual.</p>{/if}
  <div class="mt-4 inline-flex rounded-xl border border-[var(--line)] p-1" role="tablist" aria-label="Tampilan rclone">
    <button role="tab" aria-selected={rcloneView==='active'} class={`rounded-lg px-4 py-2 text-sm font-bold ${rcloneView==='active'?'bg-[var(--brand-soft)] text-[var(--brand)]':''}`} onclick={openRcloneActive}>Remote</button>
    <button role="tab" aria-selected={rcloneView==='trash'} class={`rounded-lg px-4 py-2 text-sm font-bold ${rcloneView==='trash'?'bg-[var(--brand-soft)] text-[var(--brand)]':''}`} onclick={openRcloneTrash}>Trash</button>
  </div>
  {#if rcloneView==='trash' && !remoteData.trash_supported}
    <p class="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">{remoteData.permanent_delete_supported?'Trash remote tidak dapat dikelola di sini. Hapus permanen tersedia dengan konfirmasi.':'Trash remote tidak dapat dikelola di sini dan backend belum dapat memastikan penghapusan permanen.'}</p>
  {/if}
  <div class="mt-4 flex flex-wrap items-center gap-2">
    {#if rcloneView==='active'}
    <div class="flex min-w-0 flex-1 items-center gap-1"><button class="button ghost" onclick={() => openRemoteFolder('')}>Root</button>{#each rclonePath.split('/').filter(Boolean) as crumb,index}<ChevronRight size={14}/><button class="max-w-40 truncate rounded px-2 py-1 text-sm font-semibold hover:bg-[var(--brand-soft)]" onclick={() => openRemoteFolder(rclonePath.split('/').filter(Boolean).slice(0,index+1).join('/'))}>{crumb}</button>{/each}</div>
    <input class="field min-w-[180px] flex-1" bind:value={remoteQuery} placeholder="Cari di folder ini" onkeydown={(e)=>e.key==='Enter'&&(remoteOffset=0,loadRclone())}/>
    <select class="field !w-auto" bind:value={remoteSort} onchange={()=>{remoteOffset=0;loadRclone()}}><option value="name">Nama</option><option value="updated_at">Terbaru</option><option value="size">Ukuran</option><option value="type">Tipe</option></select>
    <button class="button ghost" onclick={()=>{remoteOrder=remoteOrder==='asc'?'desc':'asc';loadRclone()}} title="Balik urutan"><ArrowUp class={remoteOrder==='desc'?'rotate-180':''} size={17}/></button>
    {/if}
    <button class="button ghost" disabled={remoteLoading||!rcloneWorkerAvailable} onclick={()=>loadRclone({refreshSummaries:rcloneView==='active'})} aria-label="Refresh rclone"><RefreshCw class={remoteLoading||remoteSummaryLoading?'animate-spin':''} size={17}/></button>
  </div>
  <div class="mt-4 divide-y divide-[var(--line)] rounded-xl border border-[var(--line)]">
    {#each remoteData.items as entry, index (`${entry.path}:${entry.id || index}`)}
      <div class="flex items-center gap-3 p-3 text-sm">
        <input type="checkbox" checked={selectedRclone.some((item)=>item.path===entry.path)} disabled={entry.ambiguous} onchange={()=>toggleRcloneEntry(entry)} aria-label={`Pilih ${entry.is_dir?'folder':'file'} ${entry.name}`}/>
        {#if entry.is_dir}<Folder class="shrink-0 text-amber-500" size={19}/>{#if rcloneView==='active'}<button class="min-w-0 flex-1 truncate text-left font-bold" onclick={()=>openRemoteFolder(entry.path)}><span class="block truncate">{entry.name}</span><small class="muted block truncate font-normal">{#if remoteSummaries[entry.path]}{remoteSummaries[entry.path].file_count} file · {remoteSummaries[entry.path].folder_count} folder · {remoteSummaries[entry.path].size_complete?formatBytes(remoteSummaries[entry.path].size_bytes):'Ukuran tidak lengkap'}{:else if remoteSummaryLoading}Menghitung…{:else if remoteSummaryFailed}Ringkasan gagal dihitung{:else if remoteSummaryReady}0 file · 0 folder · 0 B{:else}Belum dihitung{/if}</small></button><button class="button secondary !py-1" onclick={()=>{remoteTarget=entry.path;remoteTargetSelected=true;message=`Tujuan upload dipilih: ${entry.path}`}}>Pilih tujuan</button>{:else}<span class="min-w-0 flex-1 truncate font-bold">{entry.path}</span>{/if}
        {:else}<File class="shrink-0 text-violet-500" size={19}/><span class="min-w-0 flex-1 truncate">{rcloneView==='trash'?entry.path:entry.name}</span><span class="muted">{entry.size===null?'Ukuran tidak tersedia':formatBytes(entry.size)}</span>{/if}
        {#if entry.ambiguous}<span class="text-xs font-semibold text-amber-700">Path ganda; aksi item dinonaktifkan</span>{/if}
        {#if rcloneView==='active'}<button class="button ghost" disabled={rcloneMutationSubmitting} aria-label={'Rename '+entry.name} onclick={()=>beginRcloneRename(entry)}><Pencil size={15}/></button>{/if}
      </div>
    {/each}
    {#if !remoteData.items.length}<p class="muted p-8 text-center">{remoteLoading?'Memuat remote…':'Folder kosong atau tidak ada hasil.'}</p>{/if}
  </div>
  <div class="mt-3 flex items-center justify-between text-sm"><span class="muted">{remoteData.total} entri{rcloneView==='active'?` · tujuan: ${remoteTargetSelected?(remoteTarget||'root'):'belum dipilih'}`:''}</span><div class="flex gap-2"><button class="button secondary" disabled={remoteOffset<=0||remoteLoading} onclick={()=>{remoteOffset=Math.max(0,remoteOffset-100);loadRclone()}}>Sebelumnya</button><span class="muted self-center">Halaman {Math.floor(remoteOffset/100)+1}</span><button class="button secondary" disabled={remoteOffset+remoteData.limit>=remoteData.total||remoteLoading} onclick={()=>{remoteOffset+=100;loadRclone()}}>Berikutnya</button></div></div>
</section>
{:else}
<section class="card mt-6 overflow-hidden">
  <div class="grid min-h-[650px] lg:grid-cols-[250px_minmax(0,1fr)]">
    <aside class={`${mobileNavOpen ? 'fixed inset-0 z-40 block bg-black/35 lg:static lg:bg-transparent' : 'hidden lg:block'}`}>
      <div class="h-full w-[280px] border-r border-[var(--line)] bg-[var(--panel)] p-4 lg:w-auto">
        <div class="mb-4 flex items-center justify-between"><b class="text-sm">Storage</b><button class="button ghost lg:hidden" onclick={() => mobileNavOpen=false}><X size={17}/></button></div>
        <nav class="space-y-1 text-sm">
          <button class:active={scope==='current'&&folderId===null} class="storage-nav" onclick={() => chooseScope('current')}><HardDrive size={17}/>My Drive</button>
          <button class:active={scope==='global'} class="storage-nav" onclick={() => chooseScope('global')}><FolderOpen size={17}/>All Files</button>
          <button class:active={scope==='recent'} class="storage-nav" onclick={() => chooseScope('recent')}><Download size={17}/>Recent</button>
          <button class:active={scope==='trash'} class="storage-nav text-rose-600" onclick={() => chooseScope('trash')}><Trash2 size={17}/>Recycle Bin</button>
        </nav>
      </div>
    </aside>

    <main class="min-w-0">
      <div class="border-b border-[var(--line)] p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex min-w-0 items-center gap-1">
            <button class="button ghost lg:hidden" onclick={() => mobileNavOpen=true}><Folder size={17}/></button>
            <button class="button ghost !px-2" onclick={() => openFolder(null)}>Drive</button>
            {#each data.breadcrumbs as crumb}
              <ChevronRight class="muted shrink-0" size={15}/><button class="max-w-36 truncate rounded-lg px-2 py-1 text-sm font-bold hover:bg-[var(--brand-soft)]" onclick={() => openFolder(crumb.id)}>{crumb.name}</button>
            {/each}
          </div>
          <div class="flex flex-wrap gap-2">
            {#if !isTrash}<button class="button secondary" onclick={() => createOpen=true}><CirclePlus size={16}/>Folder baru</button><button class="button" onclick={startUpload} disabled={!worker}><CloudUpload size={16}/>Upload</button>
            {:else if data.items.length || data.folders.length}<button class="button danger" onclick={emptyTrash}><Trash2 size={16}/>Kosongkan Trash</button>{/if}
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center gap-2">
          <div class="relative min-w-[190px] flex-1"><Search class="muted absolute left-3 top-1/2 -translate-y-1/2" size={16}/><input class="field !pl-10" bind:value={query} placeholder="Cari file atau folder..." onkeydown={(e)=>e.key==='Enter'&&load()}/></div>
          <select class="field !w-auto" value={sort} onchange={(e)=>setSort(e.currentTarget.value)}><option value="name">Nama</option><option value="updated_at">Terbaru</option><option value="size">Ukuran</option><option value="type">Tipe</option></select>
          <button class="button ghost" onclick={() => {order=order==='asc'?'desc':'asc';load()}} title="Balik urutan"><ArrowUp class={order==='desc'?'rotate-180':''} size={17}/></button>
          <button class:active={view==='list'} class="view-button" aria-label="Tampilan daftar" onclick={() => setView('list')}><LayoutList size={17}/></button>
          <button class:active={view==='grid'} class="view-button" aria-label="Tampilan grid" onclick={() => setView('grid')}><Grid2X2 size={17}/></button>
          <button class="button ghost" onclick={load}><RefreshCw class={loading?'animate-spin':''} size={17}/></button>
        </div>
      </div>

      {#if selectionCount}
        <div class="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-violet-200 bg-violet-50 px-4 py-3 text-sm dark:border-violet-900 dark:bg-violet-950">
          <b>{selectionCount} dipilih</b><button class="button ghost" onclick={selectAll}>Pilih semua</button>
          <span class="flex-1"></span>
          {#if isTrash}<button class="button secondary" onclick={restoreSelection}><ArchiveRestore size={15}/>Restore</button><button class="button danger" onclick={() => confirmAction='purge'}><Trash2 size={15}/>Purge</button>
          {:else}<button class="button secondary" disabled={!downloadProfiles.length || !workerAdmissionEnabled} onclick={startDownload}><Download size={15}/>Download</button><button class="button secondary" onclick={startMove}><Move size={15}/>Move</button><button class="button danger" onclick={() => confirmAction='trash'}><Trash2 size={15}/>Trash</button>{/if}
          <button class="button ghost" onclick={clearSelection}><X size={16}/></button>
        </div>
      {/if}

      <div class="p-4 sm:p-5" role="region" aria-label="Isi folder storage" ondragover={(e)=>e.preventDefault()} ondrop={(e)=>dropOnFolder(e,folderId)}>
        <div class="mb-4 flex items-center justify-between"><div><h2 class="text-xl font-black">{currentName}</h2><p class="muted mt-1 text-xs">{data.total_folders} folder · {data.total_items} file</p></div>{#if data.items.length||data.folders.length}<button class="button ghost text-xs" onclick={selectAll}>Pilih semua</button>{/if}</div>
        {#if view==='grid'}
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
            {#each data.folders as folder}
              <article class:selected={selectedFolders.includes(folder.id)} class="storage-tile group" draggable="true" ondragstart={(e)=>drag(e,'folder',folder.id)} ondragover={(e)=>e.preventDefault()} ondrop={(e)=>{e.stopPropagation();dropOnFolder(e,folder.id)}}>
                <button class="absolute left-3 top-3 size-4 rounded border" class:bg-violet-600={selectedFolders.includes(folder.id)} onclick={() => toggleFolder(folder.id)} aria-label="Pilih folder"></button>
                <button class="w-full pt-5 text-left" ondblclick={() => openFolder(folder.id)} onclick={() => openFolder(folder.id)}>
                  <Folder class="mb-4 text-amber-500 transition-transform group-hover:-translate-y-1" size={42} fill="currentColor"/><b class="block truncate">{folder.name}</b><span class="muted mt-1 block text-xs">Folder</span>
                </button>
                <button class="absolute right-2 top-2 button ghost !p-2" onclick={() => beginFolderEdit(folder)}><MoreVertical size={16}/></button>
              </article>
            {/each}
            {#each data.items as item}
              {@const Icon=iconFor(item)}
              <article class:selected={selectedItems.includes(item.id)} class="storage-tile group" draggable="true" ondragstart={(e)=>drag(e,'item',item.id)}>
                <button class="absolute left-3 top-3 size-4 rounded border" class:bg-violet-600={selectedItems.includes(item.id)} onclick={() => toggleItem(item.id)} aria-label="Pilih file"></button>
                <button class="w-full pt-5 text-left" onclick={(event) => openDetail(item, event.currentTarget)}>
                  <Icon class="mb-4 text-violet-500 transition-transform group-hover:-translate-y-1" size={40}/><b class="block truncate">{item.display_name}</b><span class="muted mt-1 block text-xs">{formatBytes(item.file_size)} · {formatDate(item.uploaded_at)}</span>
                </button>
                <button class="absolute right-2 top-2 button ghost !p-2" aria-label={`Detail ${item.display_name}`} onclick={(event) => openDetail(item, event.currentTarget)}><MoreVertical size={16}/></button>
              </article>
            {/each}
          </div>
        {:else}
          <div class="divide-y divide-[var(--line)] overflow-hidden rounded-2xl border border-[var(--line)]">
            {#each data.folders as folder}
              <div class="storage-row" role="listitem" draggable="true" ondragstart={(e)=>drag(e,'folder',folder.id)} ondragover={(e)=>e.preventDefault()} ondrop={(e)=>dropOnFolder(e,folder.id)}>
                <input type="checkbox" checked={selectedFolders.includes(folder.id)} onchange={() => toggleFolder(folder.id)}/><button class="flex min-w-0 flex-1 items-center gap-3 text-left" onclick={() => openFolder(folder.id)}><Folder class="shrink-0 text-amber-500" size={24} fill="currentColor"/><span class="min-w-0"><b class="block truncate">{folder.name}</b><small class="muted block truncate">{folder.file_count || 0} file · {folder.folder_count || 0} folder · {folder.size_complete === false ? 'Ukuran tidak lengkap' : formatBytes(folder.size_bytes || 0)}</small></span></button><span class="muted hidden text-xs sm:block">Folder</span><button class="button ghost" onclick={() => beginFolderEdit(folder)}><Pencil size={15}/></button>
              </div>
            {/each}
            {#each data.items as item}
              {@const Icon=iconFor(item)}
              <div class="storage-row" role="listitem" draggable="true" ondragstart={(e)=>drag(e,'item',item.id)}>
                <input type="checkbox" checked={selectedItems.includes(item.id)} onchange={() => toggleItem(item.id)}/><button class="flex min-w-0 flex-1 items-center gap-3 text-left" onclick={(event) => openDetail(item, event.currentTarget)}><Icon class="shrink-0 text-violet-500" size={23}/><span class="min-w-0"><b class="block truncate">{item.display_name}</b><small class="muted block truncate">{item.original_name}</small></span></button><span class="muted hidden w-24 text-right text-xs sm:block">{formatBytes(item.file_size)}</span><span class="muted hidden w-32 text-right text-xs md:block">{formatDate(item.uploaded_at)}</span><button class="button ghost" aria-label={`Detail ${item.display_name}`} onclick={(event) => openDetail(item, event.currentTarget)}><MoreVertical size={16}/></button>
              </div>
            {/each}
          </div>
        {/if}
        {#if !data.folders.length&&!data.items.length}<div class="py-24 text-center"><FolderOpen class="mx-auto text-violet-300" size={56}/><h3 class="mt-4 text-lg font-black">Folder ini kosong</h3><p class="muted mt-1 text-sm">{isTrash?'Trash masih bersih.':'Buat folder atau upload dari workspace.'}</p></div>{/if}
      </div>
    </main>
  </div>
</section>
{/if}

<JobTable kind="storage_download" title="Unduhan Storage"/>
<JobTable kind="storage_upload" title="Transfer upload" retryable={true}/>
{#if provider==='telegram'}<JobTable kind="storage_sync" title="Sinkronisasi katalog Telegram"/>{/if}
{#if provider==='rclone'}<JobTable kind="storage_rclone_manage" title="Pengelolaan remote rclone"/>{/if}

<Modal open={downloadOpen} onclose={() => downloadOpen=false} title="Download ke worker" size="lg">
  <p class="muted mb-4 text-sm">{activeSelectionCount} pilihan dari {provider==='telegram'?'Telegram Storage':'rclone'} akan diunduh rekursif ke worker {worker}. File yang sudah ada tidak ditimpa.</p>
  {#if provider==='telegram'}
    <label class="block text-sm font-bold">Profil yang akan dicoba oleh TDL
      <select class="field mt-2" bind:value={downloadProfile} disabled={!downloadProfiles.length}>
        {#each downloadProfiles as profile (profile)}<option value={profile}>{profile}</option>{/each}
      </select>
    </label>
    <p class="muted mt-2 text-xs">Scan terakhir: {downloadReadiness.status === 'ready' ? 'siap' : downloadReadiness.status === 'not_ready' ? `belum siap (${downloadReadiness.reason_code})` : downloadReadiness.status}. Download tetap mencoba command TDL aktual.</p>
    {#if !downloadProfiles.length}<p class="mt-2 text-sm text-rose-700">Tidak ada profil yang diizinkan untuk akun ini.</p>{/if}
  {:else if rcloneReadiness.status !== 'ready'}
    <p class="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Scan terakhir rclone: {rcloneReadiness.reason_code || rcloneReadiness.status}. Download tetap mencoba command rclone aktual.</p>
  {/if}
  <div class="mt-4"><p class="mb-2 text-sm font-bold">Folder tujuan di /workspace</p><WorkspaceExplorer bind:selected={downloadDestinationFolders} single {worker}/></div>
  <label class="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--line)] p-3 text-sm" class:opacity-50={!workerPublicUrl}>
    <input type="checkbox" bind:checked={publishPublicLinks} disabled={!workerPublicUrl}/>
    <span><b>Buat link publik tanpa kedaluwarsa</b><small class="muted mt-1 block">Satu link per file berhasil. Atur domain HTTPS worker di Pengaturan Worker terlebih dahulu. Link dapat dicabut dari daftar di halaman Storage.</small></span>
  </label>
  <div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => downloadOpen=false}>Batal</button><button class="button" disabled={!workerAdmissionEnabled || !downloadDestinationFolders.length || !activeSelectionCount || downloadSubmitting || (provider==='telegram'&&!downloadProfiles.includes(downloadProfile))} onclick={downloadSelection}><Download size={16}/>{downloadSubmitting?'Membuat job…':'Mulai download'}</button></div>
</Modal>

<Modal open={Boolean(linkToRevoke)} onclose={() => !revokeSubmitting&&(linkToRevoke=null)} title="Cabut link dan hapus file worker?" size="sm">
  <p>Link tidak kedaluwarsa, jadi pencabutan menonaktifkannya. File <b>{linkToRevoke?.file_name}</b> akan dihapus dari worker {linkToRevoke?.worker}, termasuk bila file berubah sejak link dibuat.</p>
  <div class="mt-5 flex justify-end gap-2"><button class="button secondary" disabled={revokeSubmitting} onclick={() => linkToRevoke=null}>Batal</button><button class="button danger" disabled={revokeSubmitting} onclick={revokePublicLink}>{revokeSubmitting?'Mencabut…':'Cabut & hapus file'}</button></div>
</Modal>

{#if detail}
  {@const DetailIcon=iconFor(detail)}
  <div class="fixed inset-0 z-40">
    <button type="button" class="absolute inset-0 cursor-default bg-black/25 p-0" aria-label="Tutup detail file melalui latar" onclick={closeDetail}></button>
    <dialog open bind:this={detailPanel} aria-modal="true" aria-labelledby="storage-detail-title" tabindex="-1" onkeydown={handleDetailKeydown} class="absolute inset-y-0 left-auto right-0 m-0 w-full max-w-md overflow-auto border-0 border-l border-solid border-[var(--line)] bg-[var(--panel)] p-6 shadow-2xl">
      <div class="sticky top-0 -mx-6 -mt-6 z-10 flex items-center justify-between border-b border-[var(--line)] bg-[var(--panel)] px-6 py-4"><h2 id="storage-detail-title" class="text-xl font-black">Detail file</h2><button bind:this={detailCloseButton} type="button" class="button ghost" aria-label="Tutup detail file" onclick={closeDetail}><X size={18}/></button></div>
      <div class="my-8 text-center"><DetailIcon class="mx-auto text-violet-500" size={68}/><h3 class="mt-4 break-words text-lg font-black">{detail.display_name}</h3><p class="muted mt-1 text-sm">{detail.original_name}</p></div>
      <dl class="grid grid-cols-[110px_1fr] gap-y-3 text-sm"><dt class="muted">Lokasi</dt><dd>{detail.folder||'My Drive'}</dd><dt class="muted">Ukuran</dt><dd>{formatBytes(detail.file_size)}</dd><dt class="muted">Keywords</dt><dd>{detail.keywords||'-'}</dd><dt class="muted">{detail.recovered_at?'Profil sumber':'Uploader'}</dt><dd>{detail.owner_profile||'-'}</dd><dt class="muted">Upload</dt><dd>{formatDate(detail.uploaded_at)}</dd><dt class="muted">Caption</dt><dd>{detail.caption_sync_status||'synced'}</dd>{#if detail.recovered_at}<dt class="muted">Pemulihan</dt><dd>Dipulihkan dari profil {detail.recovered_from_profile||'-'} oleh operator {detail.recovered_by_user_id||'-'}</dd>{/if}</dl>
      <div class="mt-8 grid grid-cols-2 gap-2"><button class="button" onclick={() => deliver(detail!)}><Send size={15}/>Kirim Telegram</button><button class="button secondary" onclick={() => copyFileCode(detail!)}><Copy size={15}/>Salin kode file</button><button class="button secondary" onclick={() => beginItemEdit(detail!)}><Pencil size={15}/>Rename / keyword</button><button class="button secondary" onclick={() => {selectedItems=[detail!.id];detail=null;startMove()}}><FolderInput size={15}/>Move</button><button class="button danger col-span-2" onclick={() => {selectedItems=[detail!.id];detail=null;confirmAction=isTrash?'purge':'trash'}}><Trash2 size={15}/>{isTrash?'Purge permanen':'Pindahkan ke Trash'}</button></div>
    </dialog>
  </div>
{/if}

<Modal open={createOpen} onclose={() => createOpen=false} title="Folder baru" size="sm"><label class="text-sm font-bold">Nama folder<input class="field mt-2" bind:value={newFolderName} maxlength="120" placeholder="Dokumen 2026"/></label><p class="muted mt-2 text-xs">Maksimal 120 karakter. Slash, titik tunggal, dan karakter kontrol tidak diperbolehkan.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => createOpen=false}>Batal</button><button class="button" disabled={!newFolderName.trim() || rcloneMutationSubmitting} onclick={createFolder}>Buat folder</button></div></Modal>

<Modal open={Boolean(editRcloneEntry)} onclose={() => {editRcloneEntry=null;newFolderName=''}} title="Rename file atau folder rclone" size="sm"><label class="text-sm font-bold">Nama file atau folder<input class="field mt-2" bind:value={newFolderName} maxlength="120" aria-label="Nama file atau folder"/></label><p class="muted mt-2 text-xs">Benturan nama gagal tanpa menimpa item yang ada.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => {editRcloneEntry=null;newFolderName=''}}>Batal</button><button class="button" disabled={!newFolderName.trim() || rcloneMutationSubmitting} onclick={renameRcloneEntry}>Simpan rename</button></div></Modal>

<Modal open={Boolean(rcloneConfirmAction)} onclose={() => !rcloneManageSubmitting&&(rcloneConfirmAction=null)} title={rcloneConfirmAction==='purge'?'Hapus permanen?':rcloneConfirmAction==='move'?'Pindahkan item rclone?':rcloneConfirmAction==='trash'?'Pindahkan ke Trash?':rcloneConfirmAction==='restore'?'Pulihkan item?':'Copy item rclone?'} size="md">
  <p class="text-sm">{#if rcloneConfirmAction==='copy'}{selectedRclone.length} item akan disalin ke <b>{rclonePath||'root remote'}</b>. Item tujuan yang bentrok gagal tanpa overwrite.{:else if rcloneConfirmAction==='move'}{selectedRclone.length} item akan disalin dan diverifikasi sebelum sumber dihapus dari lokasi asal. Jika sumber berubah, sumber tetap dipertahankan; item tujuan mungkin sudah tersalin.{:else if rcloneConfirmAction==='trash'}{selectedRclone.length} item dipindahkan ke Trash. Item dapat dipulihkan selama backend remote mempertahankannya.{:else if rcloneConfirmAction==='restore'}{selectedRclone.length} item akan dipulihkan ke lokasi asal. Benturan dengan item aktif gagal tanpa overwrite. Google Drive hanya menyediakan restore seluruh item Trash di folder induk secara rekursif; pilih semua item Trash pada folder induk yang sama dalam satu batch. Jika pilihan tidak mencakup seluruh cakupan, job menolak restore agar item lain tidak ikut berubah.{:else if rcloneView==='trash'}{selectedRclone.length} item Trash akan dihapus permanen dan tidak dapat dipulihkan.{:else}Backend remote ini tidak menyediakan Trash melalui adapter. {selectedRclone.length} item akan dihapus permanen.{/if}</p>
  {#if rcloneConfirmAction==='move'}<label class="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><input class="mt-1" type="checkbox" bind:checked={rcloneManageConfirmed}/><span>Saya memahami sumber akan dihapus setelah salinan remote terkonfirmasi.</span></label>{/if}
  {#if rcloneConfirmAction==='purge'}<label class="mt-4 block text-sm font-bold">Ketik HAPUS untuk mengonfirmasi<input class="field mt-2" bind:value={rclonePurgeConfirmation} autocomplete="off"/></label>{/if}
  <div class="mt-5 flex justify-end gap-2"><button class="button secondary" disabled={rcloneManageSubmitting} onclick={() => rcloneConfirmAction=null}>Batal</button><button class={`button ${['trash','purge'].includes(rcloneConfirmAction||'')?'danger':''}`} disabled={rcloneManageSubmitting || (rcloneConfirmAction==='move'&&!rcloneManageConfirmed) || (rcloneConfirmAction==='purge'&&rclonePurgeConfirmation!=='HAPUS')} onclick={confirmRcloneManage}>{rcloneManageSubmitting?'Membuat job…':rcloneConfirmAction==='purge'?'Hapus permanen':rcloneConfirmAction==='move'?'Move':rcloneConfirmAction==='trash'?'Pindahkan ke Trash':rcloneConfirmAction==='restore'?'Pulihkan':'Copy'}</button></div>
</Modal>

<Modal open={uploadOpen} onclose={() => uploadOpen=false} title="Upload folder workspace" size="lg">
  <p class="muted mb-4 text-sm">{provider==='telegram'?'Upload akan mencoba profil lokal worker ini.':'Upload akan menjalankan command rclone pada worker ini.'} Semua subfolder sumber dipertahankan.</p><TargetPicker purpose="storage" requireProfile={false} requiresVerification={false} readinessRuntime={provider==='telegram'?'storage':'rclone_storage'} bind:worker onWorkerChange={handleWorkerChange}/><div class="mt-4"><WorkspaceExplorer bind:selected={workspaceFolders} single {worker}/></div>
  <div class="mt-4 grid gap-3 sm:grid-cols-2">{#if provider==='telegram'}<label class="text-sm font-bold">Tujuan<select class="field mt-2" bind:value={destinationId}><option value={null}>My Drive</option>{#each folderOptions as folder}<option value={folder.id}>{folder.path}</option>{/each}</select></label>{:else}<div class="rounded-xl border border-[var(--line)] p-3 text-sm"><b>Tujuan rclone</b><p class="mt-1 break-all">{remoteTargetSelected?(remoteTarget||'root'):'Pilih folder dari tab Rclone'}</p></div>{/if}<label class="text-sm font-bold">Keywords opsional<input class="field mt-2" bind:value={keywords} placeholder="archive, project"/></label></div>
  <label class="mt-4 block text-sm font-bold">Transfer<select class="field mt-2" bind:value={transferMode}><option value="copy">Copy · sumber tetap ada</option><option value="move">Move · hapus sumber setelah upload terkonfirmasi</option></select></label>
  {#if transferMode==='move'}<label class="mt-3 flex cursor-pointer items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"><input class="mt-1" type="checkbox" bind:checked={confirmMove}/><span>Saya memahami file Workspace akan dihapus satu per satu hanya setelah upload terverifikasi dan file sumber tidak berubah.</span></label>{/if}
  <div class="mt-4 flex gap-2 rounded-xl bg-[var(--brand-soft)] p-3 text-sm"><Info class="shrink-0 text-violet-600" size={18}/><p>{provider==='telegram'?'Batch ini hanya dikirim ke Telegram Storage.':'Batch ini hanya dikirim ke rclone; kegagalan tidak dialihkan ke Telegram.'} File yang bertabrakan di remote tidak akan ditimpa.</p></div>
  <div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => uploadOpen=false}>Batal</button><button class="button" disabled={!workspaceFolders.length || !workerAdmissionEnabled || (provider==='rclone'&&!remoteTargetSelected) || (transferMode==='move'&&!confirmMove)} onclick={upload}><CloudUpload size={16}/>Mulai upload</button></div>
</Modal>

<Modal open={moveOpen} onclose={() => moveOpen=false} title="Pindahkan ke folder" size="md"><label class="text-sm font-bold">Folder tujuan<select class="field mt-2" bind:value={destinationId}><option value={null}>My Drive</option>{#each folderOptions as folder}<option value={folder.id}>{folder.path}</option>{/each}</select></label><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => moveOpen=false}>Batal</button><button class="button" onclick={moveSelection}><Move size={16}/>Pindahkan</button></div></Modal>

<Modal open={Boolean(editFolder)} onclose={() => editFolder=null} title="Rename folder" size="sm"><label class="text-sm font-bold">Nama folder<input class="field mt-2" bind:value={newFolderName} maxlength="120"/></label><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => editFolder=null}>Batal</button><button class="button" onclick={renameFolder}>Simpan</button></div></Modal>

<Modal open={Boolean(editItem)} onclose={() => editItem=null} title="Metadata file" size="md"><label class="block text-sm font-bold">Nama tampilan<input class="field mt-2" bind:value={displayName}/></label><label class="mt-4 block text-sm font-bold">Keywords<input class="field mt-2" bind:value={editKeywords} placeholder="keyword, dipisahkan koma"/></label><p class="muted mt-2 text-xs">Lokasi folder diubah melalui aksi Move. Nama file Telegram asli tidak di-upload ulang.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => editItem=null}>Batal</button><button class="button" onclick={saveItem}>Simpan</button></div></Modal>

<Modal open={Boolean(confirmAction)} onclose={() => confirmAction=null} title={confirmAction==='purge'?'Hapus permanen?':'Pindahkan ke Trash?'} size="sm"><p>{confirmAction==='purge'?'Message Telegram dan metadata akan dihapus permanen. Aksi ini tidak dapat dipulihkan.':'File/folder tetap dapat direstore selama 30 hari dan message Telegram belum dihapus.'}</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => confirmAction=null}>Batal</button><button class="button danger" onclick={trashOrPurge}>{confirmAction==='purge'?'Purge permanen':'Pindahkan'}</button></div></Modal>

<style>
  .storage-nav{display:flex;width:100%;align-items:center;gap:.65rem;border-radius:.7rem;padding:.6rem .7rem;text-align:left;font-weight:700;color:var(--muted);transition:background .18s,color .18s}
  .storage-nav:hover,.storage-nav.active{background:var(--brand-soft);color:var(--brand)}
  .view-button{display:grid;height:2.5rem;width:2.5rem;place-items:center;border-radius:.7rem;border:1px solid var(--line);color:var(--muted)}
  .view-button.active{background:var(--brand-soft);color:var(--brand);border-color:transparent}
  .storage-tile{position:relative;min-width:0;border:1px solid var(--line);border-radius:1rem;padding:1rem;background:var(--panel-strong);transition:transform .18s,border-color .18s,box-shadow .18s}
  .storage-tile:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--brand) 35%,var(--line));box-shadow:0 10px 24px #0000000c}
  .storage-tile.selected{border-color:var(--brand);background:var(--brand-soft)}
  .storage-row{display:flex;min-width:0;align-items:center;gap:.8rem;padding:.85rem 1rem;transition:background .15s}
  .storage-row:hover{background:var(--brand-soft)}
  @media(prefers-reduced-motion:reduce){.storage-tile,.storage-nav{transition:none}.storage-tile:hover{transform:none}}
</style>
