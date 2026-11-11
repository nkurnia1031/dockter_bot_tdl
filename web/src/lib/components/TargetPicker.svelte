<script lang="ts">
  import { onMount } from 'svelte';
  import { post } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { runtimeReadinessFor, runtimeReadinessForWorker } from '$lib/profile-catalog';
  import { CheckCircle2, RefreshCw, ShieldCheck, TriangleAlert } from '@lucide/svelte';

  type Verification = {
    verified: boolean;
    purpose: string;
    profile?: string | null;
    worker: string;
    worker_health?: string;
    storage_profile?: string | null;
    quick_mode?: boolean;
    checked_at?: string;
  };

  let {
    purpose = 'export',
    requireProfile = true,
    profile = $bindable(''),
    worker = $bindable(''),
    verified = $bindable<Verification | null>(null),
    disabled = false,
    quickMode = false,
    requiresVerification = true,
    readinessRuntime = 'export',
    showReadiness = true,
    allowDisabledWorkerSelection = false,
    onWorkerChange
  }: {
    purpose?: 'export'|'utility'|'storage';
    requireProfile?: boolean;
    profile?: string;
    worker?: string;
    verified?: Verification | null;
    disabled?: boolean;
    quickMode?: boolean;
    requiresVerification?: boolean;
    readinessRuntime?: 'export'|'utility'|'quick_mode'|'storage'|'rclone_storage';
    showReadiness?: boolean;
    allowDisabledWorkerSelection?: boolean;
    onWorkerChange?: (worker: string) => void;
  } = $props();

  let checking = $state(false);
  let error = $state('');
  const storedReadiness = $derived(readinessRuntime === 'storage'
    ? runtimeReadinessForWorker(session.runtimeReadiness, worker, readinessRuntime)
    : runtimeReadinessFor(
      session.runtimeReadiness,
      requireProfile ? profile : null,
      worker,
      readinessRuntime
    ));
  const readiness = $derived(session.workers.find((item) => item.name === worker)?.enabled === false
    ? { status: 'disabled' as const, checked_at: '', reason_code: 'WORKER_DISABLED' }
    : storedReadiness);
  const readinessRuntimeLabel = $derived(
    readinessRuntime === 'utility' ? 'Utility' : readinessRuntime === 'quick_mode' ? 'Quick Mode' : readinessRuntime === 'rclone_storage' ? 'Storage rclone' : readinessRuntime === 'storage' ? 'Storage' : 'Export'
  );
  const readinessLabels = $derived({
    ready: `Scan terakhir: ${readinessRuntimeLabel} siap`,
    not_ready: `Scan terakhir: ${readinessRuntimeLabel} belum siap`,
    offline: 'Scan terakhir: worker offline',
    disabled: 'Worker nonaktif untuk job baru',
    unscanned: 'Belum pernah di-scan'
  });
  const readinessStyle = $derived(
    readiness.status === 'ready'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200'
      : readiness.status === 'offline' || readiness.status === 'not_ready'
        ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200'
        : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100'
  );
  const workerOptions = $derived(session.workers);

  onMount(() => {
    const tracksRuntimeReadiness = showReadiness && (requireProfile || readinessRuntime === 'storage' || readinessRuntime === 'rclone_storage');
    if (tracksRuntimeReadiness) void session.refreshProfileCatalog();
    const onJobFinished = () => { void session.refreshProfileCatalog(); };
    if (tracksRuntimeReadiness) window.addEventListener('tme3:job-finished', onJobFinished);
    const onTargetProfileChanged = (event: Event) => {
      const selected = (event as CustomEvent<{ profile?: string }>).detail?.profile;
      if (selected && selected !== profile) {
        profile = selected;
        invalidate();
      }
    };
    if (requireProfile) window.addEventListener('tme3:target-profile-changed', onTargetProfileChanged);
    return () => {
      if (tracksRuntimeReadiness) window.removeEventListener('tme3:job-finished', onJobFinished);
      if (requireProfile) window.removeEventListener('tme3:target-profile-changed', onTargetProfileChanged);
    };
  });

  $effect(() => {
    if (requireProfile && !profile) {
      profile = session.selectedTargetProfile || session.current.actor?.profile || session.current.profiles[0] || '';
    }
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
        worker,
        ...(quickMode ? { quick_mode: true } : {})
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
      <select class="field mt-2" bind:value={worker} onchange={() => { invalidate(); onWorkerChange?.(worker); }} disabled={disabled || checking}>
        <option value="" disabled>Pilih worker</option>
        {#each workerOptions as item}<option value={item.name} disabled={!allowDisabledWorkerSelection && item.enabled === false}>{item.name}{item.enabled === false ? ' (nonaktif)' : ''}</option>{/each}
      </select>
    </label>
    {#if requiresVerification}
      <button class="button secondary shrink-0" onclick={check} disabled={disabled || checking || !worker || (requireProfile && !profile)}>
        <RefreshCw size={15} class={checking ? 'animate-spin' : ''}/>{checking ? 'Memeriksa...' : 'Verifikasi target'}
      </button>
    {/if}
  </div>
  {#if requiresVerification && verified}
    <div class="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
      <CheckCircle2 size={17}/><b>Target backend terverifikasi</b><span>{verified.profile ? `${verified.profile} · ` : ''}{verified.worker}</span><span class="text-xs opacity-75">{verified.checked_at ? new Date(verified.checked_at).toLocaleString('id-ID') : ''}</span>
    </div>
  {:else if requiresVerification}
    <div class="mt-3 flex items-center gap-2 text-xs text-[var(--muted)]"><ShieldCheck size={15}/>Pilih target lalu verifikasi sebelum mengirim job.</div>
  {:else if showReadiness}
    <div class={`mt-3 flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-sm ${readinessStyle}`} aria-label={`Kesiapan ${readinessRuntimeLabel}`} role="status">
      {#if readiness.status === 'ready'}<CheckCircle2 size={17}/>{:else}<ShieldCheck size={17}/>{/if}
      <b>{readinessLabels[readiness.status]}</b>
      <span>{requireProfile && profile ? `${profile} · ` : ''}{worker || 'worker belum dipilih'}</span>
      {#if readiness.status === 'ready' && readiness.checked_at}
        <span class="text-xs opacity-75">{new Date(readiness.checked_at).toLocaleString('id-ID')}</span>
      {:else if readiness.reason_code && readiness.status !== 'unscanned'}
        <span class="text-xs opacity-75">{readiness.reason_code}</span>
      {/if}
      <span class="w-full text-xs opacity-75">Status scan hanya informasi; command aktual menentukan hasil job.</span>
    </div>
  {/if}
  {#if error}<div class="mt-3 flex gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200"><TriangleAlert size={16} class="shrink-0"/><span>{error}</span></div>{/if}
</section>
