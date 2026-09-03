<script lang="ts">
  import { post } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { CheckCircle2, RefreshCw, ShieldCheck, TriangleAlert } from '@lucide/svelte';

  type Verification = {
    verified: boolean;
    purpose: string;
    profile?: string | null;
    worker: string;
    worker_health?: string;
    storage_profile?: string | null;
    checked_at?: string;
  };

  let {
    purpose = 'export',
    requireProfile = true,
    profile = $bindable(''),
    worker = $bindable(''),
    verified = $bindable<Verification | null>(null),
    disabled = false
  }: {
    purpose?: 'export'|'utility'|'storage';
    requireProfile?: boolean;
    profile?: string;
    worker?: string;
    verified?: Verification | null;
    disabled?: boolean;
  } = $props();

  let checking = $state(false);
  let error = $state('');

  $effect(() => {
    if (requireProfile && !profile) profile = session.current.actor?.profile || session.current.profiles[0] || 'default';
    if (!worker) worker = session.workers.find((item) => item.enabled !== false)?.name || session.current.actor?.worker_route || 'local';
  });

  function invalidate() {
    verified = null;
    error = '';
  }

  async function check() {
    checking = true;
    error = '';
    try {
      verified = await post<Verification>('/context/verify', {
        purpose,
        ...(requireProfile ? { profile } : {}),
        worker
      });
    } catch (cause) {
      verified = null;
      error = cause instanceof Error ? cause.message : 'Target tidak dapat diverifikasi.';
    } finally {
      checking = false;
    }
  }
</script>

<section class="rounded-2xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
  <div class="flex flex-wrap items-end gap-3">
    {#if requireProfile}
      <label class="min-w-[10rem] flex-1 text-sm font-bold">Profile target
        <select class="field mt-2" bind:value={profile} onchange={invalidate} disabled={disabled || checking}>
          <option value="" disabled>Pilih profile</option>
          {#each session.current.profiles as item}<option value={item}>{item}</option>{/each}
        </select>
      </label>
    {/if}
    <label class="min-w-[10rem] flex-1 text-sm font-bold">Worker target
      <select class="field mt-2" bind:value={worker} onchange={invalidate} disabled={disabled || checking}>
        <option value="" disabled>Pilih worker</option>
        {#each session.workers as item}<option value={item.name} disabled={item.enabled === false}>{item.name}{item.enabled === false ? ' (nonaktif)' : ''}</option>{/each}
      </select>
    </label>
    <button class="button secondary shrink-0" onclick={check} disabled={disabled || checking || !worker || (requireProfile && !profile)}>
      <RefreshCw size={15} class={checking ? 'animate-spin' : ''}/>{checking ? 'Memeriksa...' : 'Verifikasi target'}
    </button>
  </div>
  {#if verified}
    <div class="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
      <CheckCircle2 size={17}/><b>Target backend terverifikasi</b><span>{verified.profile ? `${verified.profile} · ` : ''}{verified.worker}</span><span class="text-xs opacity-75">{verified.checked_at ? new Date(verified.checked_at).toLocaleString('id-ID') : ''}</span>
    </div>
  {:else}
    <div class="mt-3 flex items-center gap-2 text-xs text-[var(--muted)]"><ShieldCheck size={15}/>Pilih target lalu verifikasi sebelum mengirim job.</div>
  {/if}
  {#if error}<div class="mt-3 flex gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200"><TriangleAlert size={16} class="shrink-0"/><span>{error}</span></div>{/if}
</section>
