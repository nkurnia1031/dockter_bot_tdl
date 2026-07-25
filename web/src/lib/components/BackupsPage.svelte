<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import { formatDate } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { Archive, Play, RefreshCw } from '@lucide/svelte';
  let data = $state<any>({items:[]}); let message = $state(''); let pending = $state(false);
  async function load() { try { data = await api('/backups/status'); } catch (cause) { message = cause instanceof Error ? cause.message : 'Status backup gagal dimuat.'; } }
  async function run() { pending = true; try { await post('/backups'); message = 'Backup seluruh node mulai dijalankan.'; await load(); } finally { pending = false; } }
  onMount(load);
</script>
<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">BACKUP</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Backup terenkripsi</h1><p class="muted mt-2">Status per node, jadwal, dan hasil upload channel.</p></div><div class="page-icon"><Archive size={23}/></div></header>
<section class="card mt-7 p-5 sm:p-6"><div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-extrabold">Konfigurasi aktif</h2><p class="muted mt-1 text-sm">{data.schedule || '-'} · {data.timezone || '-'} · retensi {data.retention ?? '-'} · volume {data.volume_size || '-'}</p></div><div class="flex gap-2"><button class="button secondary" onclick={load}><RefreshCw size={15}/>Refresh</button><button class="button" onclick={run} disabled={pending || data.enabled === false}><Play size={15}/>{pending ? 'Memulai...' : 'Backup sekarang'}</button></div></div>{#if message}<p class="mt-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
<div class="mt-5 overflow-x-auto"><table class="w-full min-w-[650px] text-left text-sm"><thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="py-3">Node</th><th>Status</th><th>Mulai</th><th>Selesai</th><th>Error</th></tr></thead><tbody class="divide-y divide-[var(--line)]">{#each data.items || [] as item}<tr><td class="py-4 font-bold">{item.node_name}</td><td><span class={`badge ${item.status}`}>{item.status}</span></td><td>{formatDate(item.started_at)}</td><td>{formatDate(item.completed_at)}</td><td class="max-w-72 truncate text-rose-600">{item.error || '-'}</td></tr>{:else}<tr><td colspan="5" class="py-10 text-center muted">Belum ada riwayat backup.</td></tr>{/each}</tbody></table></div></section>
<JobTable kind="backup_node" title="Job backup"/>
