<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, put } from '$lib/api';
  import { formatDate } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { Archive, Play, RefreshCw } from '@lucide/svelte';
  let data = $state<any>({items:[]});
  let draft = $state<any>({ enabled: true, schedule: '03:00', timezone: 'Asia/Jakarta', retention: 7, volume_size: '45m', channel: '', storage_trash_retention_days: 30, job_stall_timeout_seconds: 600, job_cancel_grace_seconds: 30 });
  let message = $state('');
  let pending = $state(false);
  let saving = $state(false);
  async function load() {
    try {
      data = await api('/backups/status');
      draft = {
        enabled: data.enabled,
        schedule: data.schedule,
        timezone: data.timezone,
        retention: data.retention,
        volume_size: data.volume_size,
        channel: data.channel || '',
        storage_trash_retention_days: data.storage_trash_retention_days ?? 30,
        job_stall_timeout_seconds: data.job_stall_timeout_seconds ?? 600,
        job_cancel_grace_seconds: data.job_cancel_grace_seconds ?? 30,
      };
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Status backup gagal dimuat.';
    }
  }
  async function run() {
    pending = true;
    try { await post('/backups'); message = 'Backup seluruh node mulai dijalankan.'; await load(); }
    finally { pending = false; }
  }
  async function saveSettings() {
    saving = true;
    try {
      await put('/backups/settings', {
        ...draft,
        retention: Number(draft.retention),
        storage_trash_retention_days: Number(draft.storage_trash_retention_days),
        job_stall_timeout_seconds: Number(draft.job_stall_timeout_seconds),
        job_cancel_grace_seconds: Number(draft.job_cancel_grace_seconds),
      });
      message = 'Pengaturan disimpan dan langsung berlaku.';
      await load();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Pengaturan backup gagal disimpan.';
    } finally { saving = false; }
  }
  onMount(load);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">BACKUP</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Backup terenkripsi</h1><p class="muted mt-2">Status per node, jadwal, dan hasil upload channel.</p></div><div class="page-icon"><Archive size={23}/></div></header>
<section class="card mt-7 p-5 sm:p-6">
  <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-extrabold">Konfigurasi aktif</h2><p class="muted mt-1 text-sm">{data.schedule || '-'} · {data.timezone || '-'} · retensi {data.retention ?? '-'} · volume {data.volume_size || '-'}</p></div><div class="flex gap-2"><button class="button secondary" onclick={load}><RefreshCw size={15}/>Refresh</button><button class="button" onclick={run} disabled={pending || data.enabled === false}><Play size={15}/>{pending ? 'Memulai...' : 'Backup sekarang'}</button></div></div>
  {#if message}<p class="mt-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
  <details class="mt-5 rounded-2xl border border-[var(--line)] p-4"><summary class="cursor-pointer font-bold">Ubah pengaturan backup dan operasi</summary>
    <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <label class="flex items-center gap-2 text-sm font-bold"><input type="checkbox" bind:checked={draft.enabled}/>Jadwal backup aktif</label>
      <label class="text-sm font-bold">Jadwal harian<input class="field mt-2" type="time" bind:value={draft.schedule}/></label>
      <label class="text-sm font-bold">Zona waktu<input class="field mt-2" bind:value={draft.timezone} placeholder="Asia/Jakarta"/></label>
      <label class="text-sm font-bold">Jumlah backup disimpan<input class="field mt-2" type="number" min="1" max="3650" bind:value={draft.retention}/></label>
      <label class="text-sm font-bold">Ukuran setiap arsip<input class="field mt-2" bind:value={draft.volume_size} placeholder="45m"/></label>
      <label class="text-sm font-bold">Tujuan channel backup Telegram<input class="field mt-2" bind:value={draft.channel} placeholder="-100123456789 · @channel · https://t.me/channel"/><span class="muted mt-1 block text-xs">Username atau link publik harus menunjuk channel yang dapat diakses bot. Nomor telepon tidak didukung.</span></label>
      <label class="text-sm font-bold">Retensi Trash Storage (hari)<input class="field mt-2" type="number" min="1" max="3650" bind:value={draft.storage_trash_retention_days}/></label>
      <label class="text-sm font-bold">Timeout job macet (detik)<input class="field mt-2" type="number" min="0" max="86400" bind:value={draft.job_stall_timeout_seconds}/></label>
      <label class="text-sm font-bold">Masa tunggu cancel (detik)<input class="field mt-2" type="number" min="0" max="3600" bind:value={draft.job_cancel_grace_seconds}/></label>
    </div>
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3"><p class="muted text-xs">Pengaturan ini tersimpan di volume backend dan berlaku langsung untuk jadwal serta job baru. Password arsip ada di Pengaturan Utility dan nilainya tidak ditampilkan kembali.</p><button class="button" onclick={saveSettings} disabled={saving}>{saving ? 'Menyimpan...' : 'Simpan pengaturan'}</button></div>
  </details>
  <div class="mt-5 overflow-x-auto"><table class="w-full min-w-[650px] text-left text-sm"><thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="py-3">Node</th><th>Status</th><th>Mulai</th><th>Selesai</th><th>Error</th></tr></thead><tbody class="divide-y border-[var(--line)]">{#each data.items || [] as item}<tr><td class="py-4 font-bold">{item.node_name}</td><td><span class={`badge ${item.status}`}>{item.status}</span></td><td>{formatDate(item.started_at)}</td><td>{formatDate(item.completed_at)}</td><td class="max-w-72 truncate text-rose-600">{item.error || '-'}</td></tr>{:else}<tr><td colspan="5" class="py-10 text-center muted">Belum ada riwayat backup.</td></tr>{/each}</tbody></table></div>
</section>
<JobTable kind="backup_node" title="Job backup"/>
