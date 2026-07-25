<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, post, remove } from '$lib/api';
  import { formatBytes, formatDate, groupIdsByWorker } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { Archive, Boxes, Download, FastForward, History, Play, RefreshCw, RotateCcw, Trash2 } from '@lucide/svelte';

  type Artifact = {
    id:string; filename:string; worker?:string; status:string; chat_ref?:string; label?:string;
    message_count?:number; media_count?:number; photo_count?:number; video_count?:number;
    json_bytes?:number; expected_media_bytes?:number; actual_downloaded_bytes?:number;
    error?:string; created_at?:string; completed_at?:string; archived_at?:string;
  };
  type Tab = 'pending'|'processing'|'history'|'archived';
  let activeTab = $state<Tab>('pending');
  let artifacts = $state<Artifact[]>([]);
  let selected = $state<string[]>([]);
  let pending = $state(false);
  let message = $state('');
  let confirm = $state<{action:'delete'|'purge'; item:Artifact}|null>(null);
  const tabs: Array<{key:Tab;label:string}> = [{key:'pending',label:'Pending'}, {key:'processing',label:'Sedang diproses'}, {key:'history',label:'History'}, {key:'archived',label:'Archived'}];
  const visible = $derived(artifacts.filter((item) => activeTab === 'pending' ? ['pending','failed'].includes(item.status) : activeTab === 'processing' ? item.status === 'processing' : activeTab === 'history' ? ['downloaded','failed','deleted'].includes(item.status) && !item.archived_at : Boolean(item.archived_at) || item.status === 'archived'));
  const selectedItems = $derived(artifacts.filter((item) => selected.includes(item.id)));
  const selectedWorker = $derived(selectedItems[0]?.worker || '');

  async function load() {
    try {
      const [current, archived] = await Promise.all([
        api<{items:Artifact[]}>('/downloads/artifacts?limit=500&archived=false'),
        api<{items:Artifact[]}>('/downloads/artifacts?limit=500&archived=true')
      ]);
      artifacts = [...(current.items || []), ...(archived.items || []).filter((item) => !(current.items || []).some((other) => other.id === item.id))];
      selected = selected.filter((id) => artifacts.some((item) => item.id === id));
      message = '';
    } catch (cause) { message = cause instanceof Error ? cause.message : 'Artifact gagal dimuat.'; }
  }
  function toggle(item: Artifact) {
    if (selected.includes(item.id)) selected = selected.filter((id) => id !== item.id);
    else if (selectedWorker && selectedWorker !== (item.worker || 'local')) message = `Pilihan terkunci ke worker ${selectedWorker}.`;
    else selected = [...selected, item.id];
  }
  async function start(ids: string[], priority: 'normal'|'next' = 'normal', retry = false) {
    pending = true;
    try { await post(`/downloads${retry ? '?retry_failed=true' : ''}`, { artifact_ids: ids, priority }); selected = []; message = 'Download masuk antrean.'; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Download gagal dibuat.'; }
    finally { pending = false; }
  }
  async function startAll() {
    const groups = groupIdsByWorker(artifacts.filter((item) => item.status === 'pending'));
    pending = true;
    try { for (const ids of groups.values()) await post('/downloads', { artifact_ids: ids, priority: 'normal' }); message = `${groups.size} antrean worker dibuat.`; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Mulai semua gagal.'; }
    finally { pending = false; }
  }
  async function reconcile() { pending = true; try { await post('/downloads/artifacts/reconcile'); await load(); } finally { pending = false; } }
  async function clearFailed() { pending = true; try { await post('/downloads/clear-failed'); message = 'Artifact gagal dibersihkan.'; await load(); } finally { pending = false; } }
  async function archive(item: Artifact) { await post(`/downloads/artifacts/${item.id}/archive`); await load(); }
  async function restore(item: Artifact) { await post(`/downloads/artifacts/${item.id}/restore`); await load(); }
  async function destructive() {
    if (!confirm) return;
    if (confirm.action === 'delete') await post(`/downloads/artifacts/${confirm.item.id}/delete-file`);
    else await remove(`/downloads/artifacts/${confirm.item.id}`);
    confirm = null; await load();
  }
  onMount(load);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">DOWNLOAD</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Download manager</h1><p class="muted mt-2">Kelola JSON per worker, prioritas antrean, dan history tanpa kehilangan metadata.</p></div><div class="page-icon"><Boxes size={23}/></div></header>
<section class="card mt-7 overflow-hidden">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] p-4 sm:p-5">
    <div class="flex max-w-full gap-1 overflow-x-auto rounded-xl bg-[var(--brand-soft)] p-1">{#each tabs as tab}<button class={`rounded-lg px-3 py-2 text-sm font-bold ${activeTab === tab.key ? 'bg-[var(--panel-strong)] shadow-sm' : 'muted'}`} onclick={() => { activeTab = tab.key; selected = []; }}>{tab.label}</button>{/each}</div>
    <div class="flex flex-wrap gap-2"><button class="button secondary" onclick={reconcile} disabled={pending}><RefreshCw size={15}/>Reconcile</button>{#if activeTab === 'pending'}<button class="button secondary" onclick={clearFailed} disabled={pending}><Trash2 size={15}/>Clear failed</button><button class="button secondary" onclick={startAll} disabled={pending}><Play size={15}/>Mulai semua</button>{/if}</div>
  </div>
  {#if activeTab === 'pending' && selected.length}<div class="flex flex-wrap items-center gap-2 border-b border-[var(--line)] bg-violet-50 p-3 dark:bg-violet-950"><b class="mr-auto text-sm">{selected.length} dipilih · {selectedWorker}</b><button class="button" onclick={() => start(selected)}><Download size={15}/>Mulai</button><button class="button secondary" onclick={() => start(selected, 'next')}><FastForward size={15}/>Berikutnya</button>{#if selectedItems.some((item) => item.status === 'failed')}<button class="button secondary" onclick={() => start(selected, 'normal', true)}><RotateCcw size={15}/>Retry</button>{/if}</div>{/if}
  {#if message}<p class="m-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
  <div class="overflow-x-auto"><table class="w-full min-w-[900px] text-left text-sm"><thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="p-4">Pilih</th><th>Artifact</th><th>Statistik</th><th>Ukuran</th><th>Worker/status</th><th>Waktu</th><th class="pr-4 text-right">Aksi</th></tr></thead><tbody class="divide-y divide-[var(--line)]">
    {#each visible as item}<tr class="hover:bg-[var(--brand-soft)]/35"><td class="p-4"><input type="checkbox" disabled={!['pending','failed'].includes(item.status)} checked={selected.includes(item.id)} onchange={() => toggle(item)}/></td><td><b>{item.filename}</b><p class="muted mt-1">{item.label || item.chat_ref || '-'}</p>{#if item.error}<p class="mt-1 max-w-72 truncate text-xs text-rose-600">{item.error}</p>{/if}</td><td>{item.message_count ?? '?'} pesan<br/><span class="muted">{item.photo_count ?? '?'} foto · {item.video_count ?? '?'} video · {item.media_count ?? '?'} media</span></td><td>{formatBytes(item.actual_downloaded_bytes ?? item.expected_media_bytes ?? item.json_bytes)}</td><td><b>{item.worker || 'local'}</b><br/><span class={`badge ${item.status}`}>{item.status}</span></td><td>{formatDate(item.completed_at || item.created_at)}</td><td class="pr-4"><div class="flex justify-end gap-1">{#if ['pending','failed'].includes(item.status)}<button class="button secondary" onclick={() => start([item.id])}><Play size={14}/>Mulai</button><button class="button ghost text-rose-600" onclick={() => confirm = {action:'delete',item}}><Trash2 size={15}/></button>{:else if activeTab === 'archived'}<button class="button secondary" onclick={() => restore(item)}><RotateCcw size={14}/>Restore</button><button class="button danger" onclick={() => confirm = {action:'purge',item}}><Trash2 size={14}/>Purge</button>{:else}<button class="button secondary" onclick={() => archive(item)}><Archive size={14}/>Archive</button>{/if}</div></td></tr>
    {:else}<tr><td colspan="7" class="py-14 text-center"><History class="mx-auto mb-2 text-violet-400"/><b>Tidak ada artifact pada tab ini.</b></td></tr>{/each}
  </tbody></table></div>
</section>
<JobTable kind="download" title="Progress & riwayat download"/>
<Modal open={Boolean(confirm)} onclose={() => confirm = null} title={confirm?.action === 'purge' ? 'Purge metadata?' : 'Hapus file pending?'} size="sm"><p>Aksi pada <b>{confirm?.item.filename}</b> memerlukan konfirmasi.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => confirm = null}>Batal</button><button class="button danger" onclick={destructive}>Lanjutkan</button></div></Modal>
