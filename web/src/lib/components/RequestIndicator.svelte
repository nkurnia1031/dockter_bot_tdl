<script lang="ts">
  import { onMount } from 'svelte';
  import { AlertCircle, CheckCircle2, LoaderCircle } from '@lucide/svelte';

  type IndicatorState = 'idle' | 'loading' | 'success' | 'error';
  type RequestDetail = {
    method?: string;
    mutation?: boolean;
    pending?: number;
    message?: string;
  };

  let indicatorState = $state<IndicatorState>('idle');
  let pending = $state(0);
  let message = $state('');
  let visible = $state(false);
  let showTimer: ReturnType<typeof setTimeout> | undefined;
  let hideTimer: ReturnType<typeof setTimeout> | undefined;

  function clearTimers() {
    if (showTimer) clearTimeout(showTimer);
    if (hideTimer) clearTimeout(hideTimer);
    showTimer = undefined;
    hideTimer = undefined;
  }

  function scheduleHide(delay = 1200) {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (pending === 0) {
        visible = false;
        indicatorState = 'idle';
      }
      hideTimer = undefined;
    }, delay);
  }

  function onStart(event: Event) {
    const detail = (event as CustomEvent<RequestDetail>).detail || {};
    pending = Number(detail.pending || 0);
    indicatorState = 'loading';
    message = pending > 1 ? `Memproses ${pending} permintaan...` : 'Memproses permintaan...';
    clearTimers();
    // Avoid flashing the indicator for very fast background GETs while still
    // giving a visible acknowledgement for normal button requests.
    showTimer = setTimeout(() => {
      visible = true;
      showTimer = undefined;
    }, 120);
  }

  function onEnd(event: Event) {
    const detail = (event as CustomEvent<RequestDetail>).detail || {};
    pending = Number(detail.pending || 0);
    if (pending === 0 && indicatorState === 'loading') {
      if (!visible) clearTimers();
      else scheduleHide(180);
    }
  }

  function onSuccess(event: Event) {
    const detail = (event as CustomEvent<RequestDetail>).detail || {};
    if (!detail.mutation) return;
    pending = Number(detail.pending || 0);
    indicatorState = 'success';
    message = 'Permintaan berhasil diterima.';
    visible = true;
    if (showTimer) clearTimeout(showTimer);
    scheduleHide();
  }

  function onError(event: Event) {
    const detail = (event as CustomEvent<RequestDetail>).detail || {};
    pending = Number(detail.pending || 0);
    indicatorState = 'error';
    message = detail.message || 'Permintaan gagal diproses.';
    visible = true;
    if (showTimer) clearTimeout(showTimer);
    scheduleHide(2400);
  }

  onMount(() => {
    window.addEventListener('tme3:request-start', onStart);
    window.addEventListener('tme3:request-end', onEnd);
    window.addEventListener('tme3:request-success', onSuccess);
    window.addEventListener('tme3:request-error', onError);
    return () => {
      clearTimers();
      window.removeEventListener('tme3:request-start', onStart);
      window.removeEventListener('tme3:request-end', onEnd);
      window.removeEventListener('tme3:request-success', onSuccess);
      window.removeEventListener('tme3:request-error', onError);
    };
  });
</script>

{#if visible}
  <div class="request-indicator" role="status" aria-live="polite">
    <div class={`request-line ${indicatorState}`}></div>
    <div class={`request-pill ${indicatorState}`}>
      {#if indicatorState === 'loading'}<LoaderCircle size={15} class="animate-spin" />{:else if indicatorState === 'success'}<CheckCircle2 size={15} />{:else if indicatorState === 'error'}<AlertCircle size={15} />{/if}
      <span>{message}</span>
    </div>
  </div>
{/if}

<style>
  .request-indicator { position: fixed; inset: 0; z-index: 100; pointer-events: none; }
  .request-line { position: fixed; inset: 0 0 auto; height: 3px; background: var(--brand); box-shadow: 0 0 14px color-mix(in srgb, var(--brand) 70%, transparent); }
  .request-line.loading { animation: request-progress 1.1s ease-in-out infinite; transform-origin: left; }
  .request-pill { position: fixed; top: 1rem; right: 1rem; display: inline-flex; align-items: center; gap: .5rem; max-width: min(24rem, calc(100vw - 2rem)); border: 1px solid var(--line); border-radius: 999px; padding: .55rem .85rem; background: var(--panel-strong); color: var(--ink); box-shadow: 0 12px 30px color-mix(in srgb, #0f172a 18%, transparent); font-size: .78rem; font-weight: 750; }
  .request-pill.loading { color: var(--brand-strong); }
  .request-pill.success { border-color: color-mix(in srgb, #10b981 40%, var(--line)); color: #047857; }
  .request-pill.error { border-color: color-mix(in srgb, #ef4444 40%, var(--line)); color: #b91c1c; }
  :global(.dark) .request-pill.success { color: #6ee7b7; }
  :global(.dark) .request-pill.error { color: #fca5a5; }
  @keyframes request-progress { 0% { transform: scaleX(.08); opacity: .6; } 45% { transform: scaleX(.7); opacity: 1; } 100% { transform: scaleX(1); opacity: .55; } }
</style>
