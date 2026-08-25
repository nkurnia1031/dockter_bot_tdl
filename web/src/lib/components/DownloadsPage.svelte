<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, post, remove } from '$lib/api';
  import { formatBytes, formatDate } from '$lib/presentation';
  import { session } from '$lib/session.svelte';
  import JobTable from './JobTable.svelte';
  import { Archive, Boxes, CheckSquare, Download, FastForward, History, Play, RefreshCw, RotateCcw, Trash2 } from '@lucide/svelte';

  type Artifact = {
    id:string; filename:string; profile?:string; worker?:string; status:string; chat_ref?:string; label?:string;
    message_count?:number; media_count?:number; photo_count?:number; video_count?:number;
    json_bytes?:number; expected_media_bytes?:number; actual_downloaded_bytes?:number;
    error?:string; created_at?:string; completed_at?:string; archived_at?:string;
    available?:boolean|number; missing_at?:string;
  };
  type Tab = 'pending'|'processing'|'history'|'archived';
  const tabs: Array<{key:Tab;label:string}> = [{key:'pending',label:'Pending'}, {key:'processing',label:'Sedang diproses'}, {key:'history',label:'History'}, {key:'archived',label:'Archived'}];
  const terminal = ['downloaded','failed','deleted'];
  const wait = (milliseconds:number) => new Promise(resolve => setTimeout(resolve, milliseconds));

  let activeTab = $state<Tab>('pending');
  let artifacts = $state<Artifact[]>([]);
  let selected = $state<string[]>([]);
  let pending = $state(false);
  let syncing = $state(false);
  let message = $state('');
  let profileFilter = $state('');
  let workerFilter = $state('');
  let confirm = $state<'delete'|'purge'|null>(null);
  let generation = 0;
  let profileOptions = $derived([...new Set([...session.current.profiles, ...artifacts.map(item => item.profile).filter(Boolean) as string[]])].sort());
  let workerOptions = $derived([...new Set([...session.workers.map(item => item.name), ...artifacts.map(item => item.worker || 'local')])].sort());
  let filtered = $derived(artifacts.filter(item => (!profileFilter || item.profile === profileFilter) && (!workerFilter || (item.worker || 'local') === workerFilter)));
  let visible = $derived(filtered.filter(item => activeTab === 'pending'
    ? Boolean(item.available ?? true) && ['pending','failed'].includes(item.status)
    : activeTab === 'processing'
      ? Boolean(item.available ?? true) && item.status === 'processing'
      : activeTab === 'history'
        ? !item.archived_at && (terminal.includes(item.status) || item.available === false || item.available === 0)
        : Boolean(item.archived_at) || item.status === 'archived'));
  let selectable = $derived(visible.filter(item => Boolean(item.available ?? true) && ['pending','failed'].includes(item.status)));
  let selectedItems = $derived(artifacts.filter(item => selected.includes(item.id)));
  let allVisibleSelected = $derived(selectable.length > 0 && selectable.every(item => selected.includes(item.id)));

  async function loadArtifacts(archived:boolean, request:number):Promise<Artifact[]> {
    const params = new URLSearchParams({scope:'global', limit:'200', offset:'0', archived:String(archived)});
    if (profileFilter) params.set('profile', profileFilter);
    if (workerFilter) params.set('worker', workerFilter);
    const page = await api<{items:Artifact[]; total?:number}>(`/downloads/artifacts?${params}`);
    if (request !== generation) return [];
    return page.items || [];
  }
  async function load(request = generation) {
    const [current, archived] = await Promise.all([loadArtifacts(false, request), loadArtifacts(true, request)]);
    if (request !== generation) return;
    artifacts = [...current, ...archived.filter(item => !current.some(other => other.id === item.id))];
    selected = selected.filter(id => artifacts.some(item => item.id === id));
  }
  function selectAll() {
    selected = allVisibleSelected ? selected.filter(id => !selectable.some(item => item.id === id)) : [...new Set([...selected, ...selectable.map(item => item.id)])];
  }
  function toggle(item:Artifact) {
    if (!(item.available ?? true) || !['pending','failed'].includes(item.status)) return;
    selected = selected.includes(item.id) ? selected.filter(id => id !== item.id) : [...selected, item.id];
  }
  async function start(ids:string[], priority:'normal'|'next' = 'normal') {
    if (!ids.length) return;
    pending = true;
    try {
      const result = await post<{groups?:Array<{profile:string;worker:string;job_id:string}>}>('/downloads/batch', {artifact_ids:ids, priority});
      selected = [];
      message = `${ids.length} artifact dikelompokkan otomatis berdasarkan profile-worker dan masuk antrean.${result.groups?.length ? ` ${result.groups.length} job dibuat.` : ''}`;
      await load();
    } catch (cause) { message = cause instanceof Error ? cause.message : 'Download gagal dibuat.'; }
    finally { pending = false; }
  }
  async function startAll() { await start(selectable.map(item => item.id)); }
  async function deleteSelected() {
    if (!selected.length) return;
    pending = true;
    try { await post('/downloads/artifacts/actions/delete', {artifact_ids:selected}); message = `${selected.length} artifact dipindahkan dari antrean.`; selected=[]; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Artifact gagal dihapus.'; }
    finally { pending=false; }
  }
  async function clearFailed() {
    pending=true;
    try { const result = await post<{jobs?: unknown[]}>('/downloads/clear-failed?scope=global'); message=`Artifact failed dibersihkan pada ${result.jobs?.length || 0} origin.`; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Clear failed gagal.'; }
    finally { pending=false; }
  }
  async function reconcile() {
    const request = ++generation;
    syncing=true; pending=true; artifacts=[]; selected=[]; message='Menyinkronkan inventory seluruh profile-worker...';
    try {
      const result = await post<{jobs?:Array<{id:string}>; id?:string}>('/downloads/artifacts/reconcile', {scope:'global', profile:profileFilter || null, worker:workerFilter || null});
      const jobs = result.jobs || (result.id ? [{id:result.id}] : []);
      while (jobs.length && request === generation) {
        const states = await Promise.all(jobs.map(item => api<{status:string;error?:{message?:string}}>(`/jobs/${item.id}`)));
        const finished = states.filter(item => ['succeeded','failed','cancelled'].includes(item.status));
        if (finished.length === states.length) {
          const failed = finished.find(item => item.status !== 'succeeded');
          if (failed) throw new Error(failed.error?.message || 'Inventory worker gagal.');
          break;
        }
        await wait(800);
      }
      await load(request); if (request === generation) message='';
    } catch (cause) { if (request === generation) message = cause instanceof Error ? cause.message : 'Inventory gagal disinkronkan.'; }
    finally { if (request === generation) { syncing=false; pending=false; } }
  }
  async function archive(item:Artifact) { await post(`/downloads/artifacts/${item.id}/archive`); await load(); }
  async function restore(item:Artifact) { await post(`/downloads/artifacts/${item.id}/restore`); await load(); }
  async function destructive() {
    if (confirm === 'delete') await deleteSelected();
    if (confirm === 'purge') for (const item of selectedItems) await remove(`/downloads/artifacts/${item.id}`);
    confirm=null; selected=[]; await load();
  }
  function changeFilter() { generation += 1; selected=[]; reconcile(); }
  onMount(() => { reconcile(); return () => { generation += 1; }; });
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">DOWNLOAD</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Download manager</h1><p class="muted mt-2">Semua artifact lintas profile dan worker. Origin artifact menentukan runtime download secara otomatis.</p></div><div class="page-icon"><Boxes size={23}/></div></header>
<section class="card mt-7 overflow-hidden">
  <div class="border-b border-[var(--line)] p-4 sm:p-5">
    <div class="flex flex-wrap items-center justify-between gap-3"><div class="flex max-w-full gap-1 overflow-x-auto rounded-xl bg-[var(--brand-soft)] p-1">{#each tabs as tab}<button class={`rounded-lg px-3 py-2 text-sm font-bold ${activeTab===tab.key?'bg-[var(--panel-strong)] shadow-sm':'muted'}`} onclick={() => {activeTab=tab.key;selected=[];}}>{tab.label}</button>{/each}</div><div class="flex flex-wrap gap-2"><button class="button secondary" onclick={reconcile} disabled={pending}><RefreshCw class={syncing?'animate-spin':''} size={15}/>Reconcile global</button>{#if activeTab==='pending'}<button class="button secondary" onclick={clearFailed} disabled={pending||syncing}><Trash2 size={15}/>Clear failed</button><button class="button secondary" onclick={startAll} disabled={pending||syncing||!selectable.length}><Play size={15}/>Mulai semua</button>{/if}</div></div>
    <div class="mt-4 grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><label class="text-xs font-bold uppercase text-[var(--muted)]">Profile<select class="field mt-1" bind:value={profileFilter} onchange={changeFilter}><option value="">Semua profile</option>{#each profileOptions as value}<option value={value}>{value}</option>{/each}</select></label><label class="text-xs font-bold uppercase text-[var(--muted)]">Worker / VPS<select class="field mt-1" bind:value={workerFilter} onchange={changeFilter}><option value="">Semua worker</option>{#each workerOptions as value}<option value={value}>{value}</option>{/each}</select></label><button class="button secondary self-end" onclick={selectAll} disabled={pending||syncing||!selectable.length}><CheckSquare size={15}/>{allVisibleSelected?'Clear selection':'Select all'}</button></div>
  </div>
  {#if selected.length}<div class="flex flex-wrap items-center gap-2 border-b border-[var(--line)] bg-violet-50 p-3 dark:bg-violet-950"><b class="mr-auto text-sm">{selected.length} artifact dipilih</b><button class="button" onclick={() => start(selected)} disabled={pending||syncing}><Download size={15}/>Mulai terpilih</button><button class="button secondary" onclick={() => start(selected,'next')} disabled={pending||syncing}><FastForward size={15}/>Berikutnya</button><button class="button danger" onclick={() => confirm='delete'} disabled={pending||syncing}><Trash2 size={15}/>Hapus terpilih</button></div>{/if}
  {#if message}<p class="m-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
  <div class="overflow-x-auto"><table class="w-full min-w-[980px] text-left text-sm"><thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="p-4">Pilih</th><th>Artifact</th><th>Origin</th><th>Statistik</th><th>Ukuran</th><th>Status</th><th>Waktu</th><th class="pr-4 text-right">Aksi</th></tr></thead><tbody class="divide-y divide-[var(--line)]">
    {#each visible as item}<tr class="hover:bg-[var(--brand-soft)]/35"><td class="p-4"><input type="checkbox" checked={selected.includes(item.id)} disabled={pending||syncing||!(item.available??true)||!['pending','failed'].includes(item.status)} onchange={() => toggle(item)}/></td><td><b>{item.filename}</b><p class="muted mt-1">{item.label||item.chat_ref||'-'}</p>{#if item.error}<p class="mt-1 max-w-72 truncate text-xs text-rose-600">{item.error}</p>{/if}</td><td><span class="badge">{item.profile||'-'}</span><br/><span class="muted text-xs">{item.worker||'local'}</span></td><td>{item.message_count??'?'} pesan<br/><span class="muted">{item.photo_count??'?'} foto · {item.video_count??'?'} video · {item.media_count??'?'} media</span></td><td>{formatBytes(item.actual_downloaded_bytes??item.expected_media_bytes??item.json_bytes)}</td><td><span class={`badge ${item.status}`}>{item.status}</span>{#if !(item.available??true)}<span class="badge failed ml-1">File tidak tersedia</span>{/if}</td><td>{formatDate(item.completed_at||item.created_at)}</td><td class="pr-4"><div class="flex justify-end gap-1">{#if activeTab==='archived'}<button class="button secondary" onclick={() => restore(item)}><RotateCcw size={14}/>Restore</button><button class="button danger" onclick={() => {selected=[item.id];confirm='purge'}}><Trash2 size={14}/>Purge</button>{:else if activeTab==='history'&&item.status==='downloaded'}<button class="button secondary" onclick={() => archive(item)}><Archive size={14}/>Archive</button>{:else if ['pending','failed'].includes(item.status)&&Boolean(item.available??true)}<button class="button secondary" onclick={() => start([item.id])} disabled={pending||syncing}><Play size={14}/>Mulai</button>{:else}<span class="muted text-xs">Tidak ada aksi</span>{/if}</div></td></tr>{:else}<tr><td colspan="8" class="py-14 text-center"><History class="mx-auto mb-2 text-violet-400"/><b>Tidak ada artifact pada tab ini.</b></td></tr>{/each}
  </tbody></table></div>
</section>
<JobTable kind="download" title="Progress & riwayat download" scope="global" />
<Modal open={Boolean(confirm)} onclose={() => confirm=null} title={confirm==='purge'?'Purge metadata?':'Hapus file artifact terpilih?'} size="sm"><p>{confirm==='purge'?'Metadata akan dihapus permanen.':'File JSON pending/failed pada worker asal akan dihapus, metadata history tetap dipertahankan.'}</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => confirm=null}>Batal</button><button class="button danger" onclick={destructive}>Lanjutkan</button></div></Modal>
