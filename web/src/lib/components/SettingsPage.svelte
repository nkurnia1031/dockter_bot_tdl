<script lang="ts">
  import { onMount } from 'svelte';
  import { api, put } from '$lib/api';
  import { HardDrive, Save, Settings2, ShieldCheck } from '@lucide/svelte';

  type Settings = { move_size: string; compress_size: string; rclone_destination: string; compress_password_configured: boolean };
  type Meta = { key: string; label: string; description: string; format: string; examples: string[]; secret: boolean };
  let settings = $state<Settings>({ move_size: '', compress_size: '', rclone_destination: '', compress_password_configured: false });
  let meta = $state<Meta[]>([]);
  let drafts = $state<Record<string,string>>({});
  let storage = $state<any>(null);
  let message = $state('');
  let saving = $state('');

  async function load() {
    try {
      const [valueResult, metaResult, storageResult] = await Promise.all([
        api<Settings>('/utility/settings'), api<{items:Meta[]}>('/utility/settings/meta'), api<any>('/storage/settings').catch(() => null)
      ]);
      settings = valueResult; meta = metaResult.items || []; storage = storageResult;
      drafts = { move_size: settings.move_size, compress_size: settings.compress_size, rclone_destination: settings.rclone_destination, compress_password: '' };
    } catch (cause) { message = cause instanceof Error ? cause.message : 'Pengaturan gagal dimuat.'; }
  }
  async function save(item: Meta) {
    saving = item.key;
    try { await put(`/utility/settings/${item.key}`, { value: drafts[item.key] }); message = `${item.label} berhasil disimpan.`; await load(); }
    catch (cause) { message = cause instanceof Error ? cause.message : 'Pengaturan gagal disimpan.'; }
    finally { saving = ''; }
  }
  const active = (item: Meta) => item.secret ? (settings.compress_password_configured ? 'Sudah diatur' : 'Belum diatur') : (settings as any)[item.key] || '-';
  onMount(load);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">SETTINGS</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Pengaturan</h1><p class="muted mt-2">Default utility dengan format dan batas nilai yang jelas.</p></div><div class="page-icon"><Settings2 size={23}/></div></header>
{#if message}<div class="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-3 text-sm text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-100">{message}</div>{/if}
<div class="mt-7 grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
  <section class="card p-5 sm:p-6"><h2 class="font-extrabold">Default utility</h2><div class="mt-5 space-y-4">
    {#each meta as item}
      <article class="rounded-2xl border border-[var(--line)] p-4">
        <div class="flex flex-wrap justify-between gap-2"><div><h3 class="font-bold">{item.label}</h3><p class="muted mt-1 text-sm">{item.description}</p></div><span class="badge">Aktif: {active(item)}</span></div>
        <div class="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <label class="text-sm font-bold">Nilai baru<input class="field mt-2" type={item.secret ? 'password' : 'text'} bind:value={drafts[item.key]} autocomplete={item.secret ? 'new-password' : 'off'} placeholder={item.examples?.[0] || item.format}/></label>
          <button class="button" onclick={() => save(item)} disabled={!drafts[item.key] || saving === item.key}><Save size={16}/>{saving === item.key ? 'Menyimpan...' : 'Simpan'}</button>
        </div>
        <p class="muted mt-2 text-xs"><b>Format:</b> {item.format}. {item.examples?.length ? `Contoh: ${item.examples.join(', ')}.` : ''}</p>
      </article>
    {:else}<p class="muted">Metadata pengaturan belum tersedia.</p>{/each}
  </div></section>
  <div class="space-y-5">
    <section class="card p-5 sm:p-6"><div class="flex items-center gap-3"><HardDrive class="text-violet-600" size={21}/><h2 class="font-extrabold">Channel storage</h2></div><dl class="mt-4 space-y-3 text-sm"><div><dt class="muted">Nama</dt><dd class="font-bold">{storage?.title || 'Belum dikonfigurasi'}</dd></div><div><dt class="muted">Channel ID</dt><dd class="font-mono">{storage?.channel_id || storage?.channel || '-'}</dd></div></dl></section>
    <section class="card p-5 sm:p-6"><div class="flex items-center gap-3"><ShieldCheck class="text-emerald-600" size={21}/><h2 class="font-extrabold">Keamanan</h2></div><p class="muted mt-3 text-sm">Password hanya dapat diganti. Nilai yang tersimpan tidak pernah dikirim kembali ke browser atau ditampilkan di log.</p></section>
  </div>
</div>
