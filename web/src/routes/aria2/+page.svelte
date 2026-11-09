<script lang="ts">
  import { onMount } from 'svelte';
  import { Activity, RefreshCw } from '@lucide/svelte';
  import { api } from '$lib/api';

  type Worker = { name: string; enabled: boolean };
  type Health = {
    worker: string;
    ready: boolean;
    reason_code: string;
    engine: { ready: boolean; version: string | null };
    hook: {
      ready: boolean;
      script_present: boolean;
      configured: boolean;
      run_count?: number;
      last_run_at?: string | null;
      last_result?: string;
    };
  };

  let workers: Worker[] = $state([]);
  let health: Record<string, Health> = $state({});
  let loading = $state(true);
  let inspecting = $state('');
  let error = $state('');

  async function loadWorkers() {
    loading = true;
    error = '';
    try {
      const response = await api<{ items: Worker[] }>('/workers');
      workers = response.items || [];
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Daftar worker gagal dimuat.';
    } finally {
      loading = false;
    }
  }

  async function inspect(name: string) {
    inspecting = name;
    error = '';
    try {
      health = {
        ...health,
        [name]: await api<Health>(`/workers/${encodeURIComponent(name)}/aria2/health`)
      };
    } catch (cause) {
      error = cause instanceof Error ? cause.message : `Status Aria2 ${name} gagal diperiksa.`;
    } finally {
      inspecting = '';
    }
  }

  onMount(() => { void loadWorkers(); });
</script>

<svelte:head>
  <title>AriaNg · tme3bot</title>
  <meta name="description" content="Status layanan unduhan Aria2 per worker." />
</svelte:head>

<section class="mx-auto max-w-6xl p-4 sm:p-6 lg:p-8">
  <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="muted text-sm font-bold uppercase tracking-[.14em]">Transfer</p>
      <h1 class="mt-1 text-3xl font-black">AriaNg</h1>
      <p class="muted mt-2 max-w-2xl">Unduhan aria2 berjalan pada worker terpilih. Status engine dan hook diperiksa saat diminta.</p>
    </div>
    <button class="button secondary" onclick={loadWorkers} disabled={loading}>
      <RefreshCw size={16} class={loading ? 'animate-spin' : ''} /> Muat ulang worker
    </button>
  </div>

  {#if error}<div class="alert error mb-4" role="alert">{error}</div>{/if}
  {#if loading}
    <div class="card p-6" role="status">Memuat worker…</div>
  {:else if !workers.length}
    <div class="card p-6">Belum ada worker terdaftar.</div>
  {:else}
    <div class="grid gap-4 md:grid-cols-2">
      {#each workers as worker (worker.name)}
        {@const result = health[worker.name]}
        <article class="card p-5">
          <div class="flex items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-extrabold">{worker.name}</h2>
              <p class="muted mt-1 text-sm">{worker.enabled ? 'Worker aktif' : 'Worker nonaktif'}</p>
            </div>
            <button class="button secondary" onclick={() => inspect(worker.name)} disabled={inspecting === worker.name} aria-label={`Periksa Aria2 ${worker.name}`}>
              <RefreshCw size={15} class={inspecting === worker.name ? 'animate-spin' : ''} />
              {result ? 'Periksa ulang' : 'Periksa status'}
            </button>
          </div>

          {#if result}
            <div class="mt-5 grid gap-3 sm:grid-cols-2">
              <div class="rounded-xl border border-[var(--line)] p-3">
                <p class="muted text-xs font-bold uppercase">Engine</p>
                <p class="mt-1 font-semibold">{result.engine.ready ? `Siap · aria2 ${result.engine.version || ''}` : 'Tidak tersedia'}</p>
              </div>
              <div class="rounded-xl border border-[var(--line)] p-3">
                <p class="muted text-xs font-bold uppercase">Hook low-speed</p>
                <p class="mt-1 font-semibold">{result.hook.ready ? 'Siap' : 'Tidak siap'}</p>
              </div>
            </div>
            <div class="mt-4 flex flex-wrap items-center gap-2 text-sm">
              <span class={`rounded-full px-3 py-1 font-bold ${result.ready ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`} role="status">
                {result.ready ? 'Siap' : result.reason_code || 'Belum siap'}
              </span>
              {#if result.hook.last_result && result.hook.last_result !== 'never'}
                <span class="muted">Hook terakhir: {result.hook.last_result}</span>
              {/if}
            </div>
          {:else}
            <div class="muted mt-5 flex items-center gap-2 text-sm"><Activity size={15}/> Status belum diperiksa.</div>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</section>
