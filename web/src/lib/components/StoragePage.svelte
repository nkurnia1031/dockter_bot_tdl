<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, patch, post, remove } from '$lib/api';
  import { formatBytes, formatDate } from '$lib/presentation';
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
    updated_at:string; trashed_at?:string|null
  };
  type Item = {
    id:number; display_name:string; original_name:string; folder?:string;
    folder_id?:number|null; keywords?:string; file_size?:number; mime_type?:string;
    owner_user_id?:number; owner_profile?:string; uploaded_at?:string;
    updated_at?:string; status?:string; trashed_at?:string|null;
    caption_sync_status?:string
  };
  type BrowserResponse = {
    current_folder:FolderEntry|null; breadcrumbs:{id:number;name:string}[];
    folders:FolderEntry[]; items:Item[]; total_folders:number; total_items:number
  };

  let folderId = $state<number|null>(null);
  let scope = $state<'current'|'global'|'recent'|'trash'>('current');
  let query = $state('');
  let sort = $state('name');
  let order = $state('asc');
  let view = $state<'list'|'grid'>('grid');
  let data = $state<BrowserResponse>({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0});
  let tree = $state<FolderEntry[]>([]);
  let selectedItems = $state<number[]>([]);
  let selectedFolders = $state<number[]>([]);
  let loading = $state(false);
  let message = $state('');
  let mobileTree = $state(false);
  let createOpen = $state(false);
  let uploadOpen = $state(false);
  let moveOpen = $state(false);
  let editItem = $state<Item|null>(null);
  let editFolder = $state<FolderEntry|null>(null);
  let detail = $state<Item|null>(null);
  let confirmAction = $state<'trash'|'purge'|null>(null);
  let newFolderName = $state('');
  let destinationId = $state<number|null>(null);
  let workspaceFolders = $state<string[]>([]);
  let keywords = $state('');
  let rcloneUpload = $state(false);
  let displayName = $state('');
  let editKeywords = $state('');
  let worker = $state('');
  let verified = $state<any>(null);

  const selectionCount = $derived(selectedItems.length + selectedFolders.length);
  const isTrash = $derived(scope === 'trash');
  const currentName = $derived(data.current_folder?.name || (scope === 'trash' ? 'Recycle Bin' : scope === 'recent' ? 'Recent' : scope === 'global' ? 'All Files' : 'My Drive'));

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
      tree = (await api<{items:FolderEntry[]}>('/storage/folders/tree')).items || [];
      message = '';
      updateUrl();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Storage tidak dapat dimuat.';
    } finally { loading = false; }
  }
  function openFolder(id:number|null) {
    folderId = id; scope = 'current'; clearSelection(); load();
  }
  function chooseScope(next:typeof scope) {
    scope = next; folderId = null; clearSelection(); load();
  }
  function clearSelection() { selectedItems = []; selectedFolders = []; }
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
    await post('/storage/folders', {name:newFolderName,parent_id:folderId});
    createOpen=false; newFolderName=''; await load();
  }
  async function renameFolder() {
    if (!editFolder) return;
    await patch(`/storage/folders/${editFolder.id}`, {name:newFolderName});
    editFolder=null; newFolderName=''; await load();
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
    if (!verified || verified.worker !== worker) { message = 'Verifikasi worker terlebih dahulu.'; return; }
    await post('/storage/uploads', {
      folder_path:workspaceFolders[0], destination_folder_id:destinationId,
      preserve_structure:true, keywords, worker, rclone_upload:rcloneUpload
    });
    uploadOpen=false; workspaceFolders=[]; keywords=''; rcloneUpload=false;
    message='Upload masuk antrean. Struktur subfolder akan dipertahankan.';
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
  function startUpload() { destinationId=folderId; rcloneUpload=false; uploadOpen=true; }
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
    load();
  });
  function setView(next:'list'|'grid') { view=next; localStorage.setItem('storage-view',next); }
  function setSort(next:string) { sort=next; localStorage.setItem('storage-sort',next); load(); }
</script>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">STORAGE</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Cloud Storage</h1><p class="muted mt-2">Kelola katalog Telegram seperti file hosting—folder bersama untuk seluruh user.</p></div>
  <div class="page-icon"><HardDrive size={23}/></div>
</header>

<div class="mt-5"><TargetPicker purpose="storage" requireProfile={false} bind:worker bind:verified /></div>

{#if message}<div class="mt-5 flex items-center justify-between rounded-2xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-100"><span>{message}</span><button onclick={() => message=''}><X size={16}/></button></div>{/if}

<section class="card mt-6 overflow-hidden">
  <div class="grid min-h-[650px] lg:grid-cols-[250px_minmax(0,1fr)]">
    <aside class={`${mobileTree ? 'fixed inset-0 z-40 block bg-black/35 lg:static lg:bg-transparent' : 'hidden lg:block'}`}>
      <div class="h-full w-[280px] border-r border-[var(--line)] bg-[var(--panel)] p-4 lg:w-auto">
        <div class="mb-4 flex items-center justify-between"><b class="text-sm">Storage</b><button class="button ghost lg:hidden" onclick={() => mobileTree=false}><X size={17}/></button></div>
        <nav class="space-y-1 text-sm">
          <button class:active={scope==='current'&&folderId===null} class="storage-nav" onclick={() => chooseScope('current')}><HardDrive size={17}/>My Drive</button>
          <button class:active={scope==='global'} class="storage-nav" onclick={() => chooseScope('global')}><FolderOpen size={17}/>All Files</button>
          <button class:active={scope==='recent'} class="storage-nav" onclick={() => chooseScope('recent')}><Download size={17}/>Recent</button>
          <button class:active={scope==='trash'} class="storage-nav text-rose-600" onclick={() => chooseScope('trash')}><Trash2 size={17}/>Recycle Bin</button>
        </nav>
        <div class="my-4 border-t border-[var(--line)]"></div>
        <p class="muted mb-2 px-2 text-[11px] font-black uppercase tracking-wider">Folder bersama</p>
        <div class="max-h-[55vh] space-y-1 overflow-auto">
          {#each tree as folder}
            <button class:active={folder.id===folderId} class="storage-nav" style={`padding-left:${8 + Math.max(0,folder.path.split('/').length-1)*14}px`} onclick={() => {openFolder(folder.id);mobileTree=false}} ondragover={(e)=>e.preventDefault()} ondrop={(e)=>dropOnFolder(e,folder.id)}>
              <Folder size={16} class="shrink-0 text-amber-500"/><span class="truncate">{folder.name}</span>
            </button>
          {/each}
        </div>
      </div>
    </aside>

    <main class="min-w-0">
      <div class="border-b border-[var(--line)] p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex min-w-0 items-center gap-1">
            <button class="button ghost lg:hidden" onclick={() => mobileTree=true}><Folder size={17}/></button>
            <button class="button ghost !px-2" onclick={() => openFolder(null)}>Drive</button>
            {#each data.breadcrumbs as crumb}
              <ChevronRight class="muted shrink-0" size={15}/><button class="max-w-36 truncate rounded-lg px-2 py-1 text-sm font-bold hover:bg-[var(--brand-soft)]" onclick={() => openFolder(crumb.id)}>{crumb.name}</button>
            {/each}
          </div>
          <div class="flex flex-wrap gap-2">
            {#if !isTrash}<button class="button secondary" onclick={() => createOpen=true}><CirclePlus size={16}/>Folder baru</button><button class="button" onclick={startUpload} disabled={!verified}><CloudUpload size={16}/>Upload</button>
            {:else if data.items.length || data.folders.length}<button class="button danger" onclick={emptyTrash}><Trash2 size={16}/>Kosongkan Trash</button>{/if}
          </div>
        </div>
        <div class="mt-4 flex flex-wrap items-center gap-2">
          <div class="relative min-w-[190px] flex-1"><Search class="muted absolute left-3 top-1/2 -translate-y-1/2" size={16}/><input class="field !pl-10" bind:value={query} placeholder="Cari file atau folder..." onkeydown={(e)=>e.key==='Enter'&&load()}/></div>
          <select class="field !w-auto" value={sort} onchange={(e)=>setSort(e.currentTarget.value)}><option value="name">Nama</option><option value="updated_at">Terbaru</option><option value="size">Ukuran</option><option value="type">Tipe</option></select>
          <button class="button ghost" onclick={() => {order=order==='asc'?'desc':'asc';load()}} title="Balik urutan"><ArrowUp class={order==='desc'?'rotate-180':''} size={17}/></button>
          <button class:active={view==='list'} class="view-button" onclick={() => setView('list')}><LayoutList size={17}/></button>
          <button class:active={view==='grid'} class="view-button" onclick={() => setView('grid')}><Grid2X2 size={17}/></button>
          <button class="button ghost" onclick={load}><RefreshCw class={loading?'animate-spin':''} size={17}/></button>
        </div>
      </div>

      {#if selectionCount}
        <div class="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b border-violet-200 bg-violet-50 px-4 py-3 text-sm dark:border-violet-900 dark:bg-violet-950">
          <b>{selectionCount} dipilih</b><button class="button ghost" onclick={selectAll}>Pilih semua</button>
          <span class="flex-1"></span>
          {#if isTrash}<button class="button secondary" onclick={restoreSelection}><ArchiveRestore size={15}/>Restore</button><button class="button danger" onclick={() => confirmAction='purge'}><Trash2 size={15}/>Purge</button>
          {:else}<button class="button secondary" onclick={startMove}><Move size={15}/>Move</button><button class="button danger" onclick={() => confirmAction='trash'}><Trash2 size={15}/>Trash</button>{/if}
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
                <button class="w-full pt-5 text-left" onclick={() => detail=item}>
                  <Icon class="mb-4 text-violet-500 transition-transform group-hover:-translate-y-1" size={40}/><b class="block truncate">{item.display_name}</b><span class="muted mt-1 block text-xs">{formatBytes(item.file_size)} · {formatDate(item.uploaded_at)}</span>
                </button>
                <button class="absolute right-2 top-2 button ghost !p-2" onclick={() => detail=item}><MoreVertical size={16}/></button>
              </article>
            {/each}
          </div>
        {:else}
          <div class="divide-y divide-[var(--line)] overflow-hidden rounded-2xl border border-[var(--line)]">
            {#each data.folders as folder}
              <div class="storage-row" role="listitem" draggable="true" ondragstart={(e)=>drag(e,'folder',folder.id)} ondragover={(e)=>e.preventDefault()} ondrop={(e)=>dropOnFolder(e,folder.id)}>
                <input type="checkbox" checked={selectedFolders.includes(folder.id)} onchange={() => toggleFolder(folder.id)}/><button class="flex min-w-0 flex-1 items-center gap-3 text-left" onclick={() => openFolder(folder.id)}><Folder class="shrink-0 text-amber-500" size={24} fill="currentColor"/><span class="truncate font-bold">{folder.name}</span></button><span class="muted hidden text-xs sm:block">Folder</span><button class="button ghost" onclick={() => beginFolderEdit(folder)}><Pencil size={15}/></button>
              </div>
            {/each}
            {#each data.items as item}
              {@const Icon=iconFor(item)}
              <div class="storage-row" role="listitem" draggable="true" ondragstart={(e)=>drag(e,'item',item.id)}>
                <input type="checkbox" checked={selectedItems.includes(item.id)} onchange={() => toggleItem(item.id)}/><button class="flex min-w-0 flex-1 items-center gap-3 text-left" onclick={() => detail=item}><Icon class="shrink-0 text-violet-500" size={23}/><span class="min-w-0"><b class="block truncate">{item.display_name}</b><small class="muted block truncate">{item.original_name}</small></span></button><span class="muted hidden w-24 text-right text-xs sm:block">{formatBytes(item.file_size)}</span><span class="muted hidden w-32 text-right text-xs md:block">{formatDate(item.uploaded_at)}</span><button class="button ghost" onclick={() => detail=item}><MoreVertical size={16}/></button>
              </div>
            {/each}
          </div>
        {/if}
        {#if !data.folders.length&&!data.items.length}<div class="py-24 text-center"><FolderOpen class="mx-auto text-violet-300" size={56}/><h3 class="mt-4 text-lg font-black">Folder ini kosong</h3><p class="muted mt-1 text-sm">{isTrash?'Trash masih bersih.':'Buat folder atau upload dari workspace.'}</p></div>{/if}
      </div>
    </main>
  </div>
</section>

<JobTable kind="storage_upload" title="Transfer upload"/>

{#if detail}
  {@const DetailIcon=iconFor(detail)}
  <div class="fixed inset-0 z-40 bg-black/25">
    <aside class="absolute inset-y-0 right-0 w-full max-w-md overflow-auto border-l border-[var(--line)] bg-[var(--panel)] p-6 shadow-2xl">
      <div class="flex items-center justify-between"><h2 class="text-xl font-black">Detail file</h2><button class="button ghost" onclick={() => detail=null}><X size={18}/></button></div>
      <div class="my-8 text-center"><DetailIcon class="mx-auto text-violet-500" size={68}/><h3 class="mt-4 break-words text-lg font-black">{detail.display_name}</h3><p class="muted mt-1 text-sm">{detail.original_name}</p></div>
      <dl class="grid grid-cols-[110px_1fr] gap-y-3 text-sm"><dt class="muted">Lokasi</dt><dd>{detail.folder||'My Drive'}</dd><dt class="muted">Ukuran</dt><dd>{formatBytes(detail.file_size)}</dd><dt class="muted">Keywords</dt><dd>{detail.keywords||'-'}</dd><dt class="muted">Uploader</dt><dd>{detail.owner_profile||'-'}</dd><dt class="muted">Upload</dt><dd>{formatDate(detail.uploaded_at)}</dd><dt class="muted">Caption</dt><dd>{detail.caption_sync_status||'synced'}</dd></dl>
      <div class="mt-8 grid grid-cols-2 gap-2"><button class="button" onclick={() => deliver(detail!)}><Send size={15}/>Kirim Telegram</button><button class="button secondary" onclick={() => copyFileCode(detail!)}><Copy size={15}/>Salin kode file</button><button class="button secondary" onclick={() => beginItemEdit(detail!)}><Pencil size={15}/>Rename / keyword</button><button class="button secondary" onclick={() => {selectedItems=[detail!.id];detail=null;startMove()}}><FolderInput size={15}/>Move</button><button class="button danger col-span-2" onclick={() => {selectedItems=[detail!.id];detail=null;confirmAction=isTrash?'purge':'trash'}}><Trash2 size={15}/>{isTrash?'Purge permanen':'Pindahkan ke Trash'}</button></div>
    </aside>
  </div>
{/if}

<Modal open={createOpen} onclose={() => createOpen=false} title="Folder baru" size="sm"><label class="text-sm font-bold">Nama folder<input class="field mt-2" bind:value={newFolderName} maxlength="120" placeholder="Dokumen 2026"/></label><p class="muted mt-2 text-xs">Maksimal 120 karakter. Slash, titik tunggal, dan karakter kontrol tidak diperbolehkan.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => createOpen=false}>Batal</button><button class="button" disabled={!newFolderName.trim()} onclick={createFolder}>Buat folder</button></div></Modal>

<Modal open={uploadOpen} onclose={() => uploadOpen=false} title="Upload folder workspace" size="lg">
  <p class="muted mb-4 text-sm">Pilih source dari worker yang sudah diverifikasi. Semua subfolder akan dibuat kembali di Storage.</p><TargetPicker purpose="storage" requireProfile={false} bind:worker bind:verified/><div class="mt-4"><WorkspaceExplorer bind:selected={workspaceFolders} single {worker}/></div>
  <div class="mt-4 grid gap-3 sm:grid-cols-2"><label class="text-sm font-bold">Tujuan<select class="field mt-2" bind:value={destinationId}><option value={null}>My Drive</option>{#each tree as folder}<option value={folder.id}>{folder.path}</option>{/each}</select></label><label class="text-sm font-bold">Keywords opsional<input class="field mt-2" bind:value={keywords} placeholder="archive, project"/></label></div>
  <label class="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--line)] p-3 text-sm"><input class="mt-1" type="checkbox" bind:checked={rcloneUpload}/><span><b>Salin juga ke Google Drive</b><small class="muted mt-1 block">Memakai tujuan rclone pada Pengaturan dan konfigurasi <code>/workspace/.config/rclone.conf</code>.</small></span></label>
  <div class="mt-4 flex gap-2 rounded-xl bg-[var(--brand-soft)] p-3 text-sm"><Info class="shrink-0 text-violet-600" size={18}/><p>Destination dipilih dari folder Storage, bukan input teks. Nested dan empty folder dipertahankan.</p></div>
  <div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => uploadOpen=false}>Batal</button><button class="button" disabled={!workspaceFolders.length} onclick={upload}><CloudUpload size={16}/>Mulai upload</button></div>
</Modal>

<Modal open={moveOpen} onclose={() => moveOpen=false} title="Pindahkan ke folder" size="md"><label class="text-sm font-bold">Folder tujuan<select class="field mt-2" bind:value={destinationId}><option value={null}>My Drive</option>{#each tree as folder}<option value={folder.id}>{folder.path}</option>{/each}</select></label><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => moveOpen=false}>Batal</button><button class="button" onclick={moveSelection}><Move size={16}/>Pindahkan</button></div></Modal>

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
