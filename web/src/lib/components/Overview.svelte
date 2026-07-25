<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import JobTable from './JobTable.svelte';
  import { Activity, Archive, Boxes, Clock3, Database, HardDrive } from '@lucide/svelte';

  let data = $state<Record<string, any> | null>(null);
  let error = $state('');
  const icons = [Activity, Clock3, Database, HardDrive, Archive, Boxes];
  const label = (key: string) => key.replaceAll('_', ' ');
  const describe = (item: unknown) => {
    if (item === null || item === undefined) return 'Belum tersedia';
    if (typeof item === 'number') return new Intl.NumberFormat('id-ID').format(item);
    if (typeof item === 'string') return item;
    if (Array.isArray(item)) return `${item.length} item`;
    if (typeof item === 'object') {
      const pairs = Object.entries(item as Record<string, unknown>).slice(0, 2).map(([key, value]) => `${label(key)}: ${typeof value === 'object' ? 'tersedia' : value}`);
      return pairs.join(' · ') || 'Tersedia';
    }
    return String(item);
  };
  onMount(async () => { try { data = await api('/dashboard/summary'); } catch (cause) { error = cause instanceof Error ? cause.message : 'Gagal memuat ringkasan.'; } });
</script>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">CONTROL CENTER</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Ringkasan operasional</h1><p class="muted mt-2 max-w-2xl">Pantau status gateway, antrean pekerjaan, storage, dan backup dari satu tempat.</p></div>
  <div class="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200"><b class="block">Status realtime</b><span class="mt-1 flex items-center gap-1.5"><i class="size-2 rounded-full bg-emerald-500"></i>Backend siap menerima perintah</span></div>
</header>

{#if error}<div class="mt-6 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</div>{/if}

<div class="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
  {#each Object.entries(data || {}) as [key, item], index}
    {@const Icon = icons[index % icons.length]}
    <section class="record-card page-enter" style={`animation-delay:${index * 55}ms`}>
      <div class="flex items-start justify-between gap-4"><div><p class="muted text-xs font-bold uppercase tracking-[.12em]">{label(key)}</p><p class="mt-2 text-base font-extrabold">{describe(item)}</p></div><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300"><Icon size={19}/></div></div>
    </section>
  {:else}
    {#each Array(6) as _}<div class="h-28 animate-pulse rounded-2xl border border-[var(--line)] bg-[var(--panel)]"></div>{/each}
  {/each}
</div>

<JobTable title="Job terbaru" />
