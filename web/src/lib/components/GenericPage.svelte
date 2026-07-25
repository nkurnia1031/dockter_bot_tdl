<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import JobTable from './JobTable.svelte';
  import { Archive, Boxes, FolderCog, HardDrive, Play, Search, Settings2, Users } from '@lucide/svelte';

  let { section }: { section: 'downloads'|'utility'|'storage'|'workers'|'backups'|'settings' } = $props();
  const meta: Record<string, { title: string; description: string; endpoint: string; job?: string; icon: typeof Boxes }> = {
    downloads: { title: 'Download manager', description: 'Antrean JSON, progress, dan histori download.', endpoint: '/downloads/artifacts', job: 'download', icon: Boxes },
    utility: { title: 'Utility workspace', description: 'Folder, pengaturan default, dan riwayat operasi.', endpoint: '/utility/folders', job: 'utility', icon: FolderCog },
    storage: { title: 'Storage katalog', description: 'Cari katalog, upload folder workspace, dan kelola metadata.', endpoint: '/storage/items?limit=50', job: 'storage_upload', icon: HardDrive },
    workers: { title: 'Workers', description: 'Endpoint worker dan route profile aktif.', endpoint: '/workers', icon: Users },
    backups: { title: 'Backup', description: 'Status backup terenkripsi per node.', endpoint: '/backups/status', icon: Archive },
    settings: { title: 'Pengaturan', description: 'Default utility dan informasi sistem.', endpoint: '/utility/settings', icon: Settings2 }
  };
  const Icon = $derived(meta[section].icon);
  let data = $state<any>(null); let error = $state(''); let query = $state(''); let path = $state(''); let folder = $state(''); let keywords = $state(''); let operation = $state('pindah'); let pending = $state(false);
  const label = (key: string) => key.replaceAll('_', ' ');
  const display = (item: unknown) => {
    if (item === null || item === undefined || item === '') return '-';
    if (typeof item === 'boolean') return item ? 'Aktif' : 'Nonaktif';
    if (Array.isArray(item)) return `${item.length} item`;
    if (typeof item === 'object') return Object.entries(item as object).slice(0, 3).map(([key, value]) => `${label(key)}: ${typeof value === 'object' ? 'tersedia' : value}`).join(' · ');
    return String(item);
  };
  const records = () => Array.isArray(data?.items) ? data.items : data && typeof data === 'object' ? [data] : [];
  async function load() { try { const endpoint = section === 'storage' && query ? `/storage/items?q=${encodeURIComponent(query)}&limit=50` : meta[section].endpoint; data = await api<any>(endpoint); error = ''; } catch (cause) { error = cause instanceof Error ? cause.message : 'Gagal memuat data.'; } }
  async function action() { pending = true; try { if (section === 'backups') await post('/backups'); if (section === 'utility' && path) await post('/utility/jobs', { utility: operation, folders: [path] }); if (section === 'storage' && path) await post('/storage/uploads', { folder_path: path, folder, keywords }); await load(); } finally { pending = false; } }
  onMount(load);
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">{section.toUpperCase()}</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">{meta[section].title}</h1><p class="muted mt-2">{meta[section].description}</p></div><div class="grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Icon size={23}/></div></header>

<section class="card mt-7 p-5 sm:p-6">
  {#if section === 'storage'}
    <div class="flex flex-wrap gap-2"><div class="relative min-w-56 flex-1"><Search class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" size={17}/><input class="field !pl-10" bind:value={query} placeholder="Cari nama, folder, atau keyword" onkeydown={(event) => event.key === 'Enter' && load()}/></div><button class="button secondary" onclick={load}><Search size={16}/>Cari</button></div>
    <div class="mt-5 grid gap-3 md:grid-cols-3"><label class="text-sm font-bold">Folder workspace<input class="field mt-2" bind:value={path} placeholder="/workspace/..."/></label><label class="text-sm font-bold">Folder logis<input class="field mt-2" bind:value={folder} placeholder="Contoh: arsip-2026"/></label><label class="text-sm font-bold">Keywords<input class="field mt-2" bind:value={keywords} placeholder="Opsional, pisahkan koma"/></label></div><button class="button mt-4" onclick={action} disabled={!path || pending}><HardDrive size={16}/>{pending ? 'Menambahkan antrean...' : 'Upload folder'}</button>
  {:else if section === 'utility'}
    <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_13rem]"><label class="text-sm font-bold">Folder workspace<input class="field mt-2" bind:value={path} placeholder="Pilih path dari workspace tree"/></label><label class="text-sm font-bold">Jenis operasi<select class="field mt-2" bind:value={operation}><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option></select></label></div><button class="button mt-4" onclick={action} disabled={!path || pending}><Play size={16}/>{pending ? 'Menambahkan antrean...' : 'Jalankan utility'}</button>
  {:else if section === 'backups'}
    <div class="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-900 dark:bg-violet-950"><div><b>Backup terenkripsi per node</b><p class="muted mt-1 text-sm">Password dan sesi tidak ditampilkan di dashboard.</p></div><button class="button" onclick={action} disabled={pending}><Archive size={16}/>{pending ? 'Memulai...' : 'Backup sekarang'}</button></div>
  {/if}

  {#if error}<div class="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>{/if}
  <div class="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
    {#each records() as record, index}
      <article class="record-card page-enter" style={`animation-delay:${index * 35}ms`}>
        {#each Object.entries(record).slice(0, 6) as [key, item]}
          <div class="flex items-start justify-between gap-4 border-b border-[var(--line)] py-2 last:border-0"><span class="muted shrink-0 text-xs font-bold uppercase tracking-wide">{label(key)}</span><span class="text-right text-sm font-semibold break-words">{display(item)}</span></div>
        {/each}
      </article>
    {:else}
      <div class="rounded-2xl border border-dashed border-[var(--line)] py-12 text-center md:col-span-2 xl:col-span-3"><Icon class="mx-auto mb-3 text-violet-500" size={28}/><p class="font-bold">Belum ada data.</p><p class="muted mt-1 text-sm">Gunakan aksi di atas atau refresh kembali.</p></div>
    {/each}
  </div>
</section>
{#if meta[section].job}<JobTable kind={meta[section].job} title="Riwayat & progress" />{/if}
