<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';

type RequestDetail = { requestId?: number; pending?: number; mutation?: boolean; message?: string };
const visible = ref(false);
const state = ref<'loading' | 'success' | 'error'>('loading');
const message = ref('Memproses permintaan…');
const pending = ref(0);
const inFlightRequests = new Set<number>();
let hadMutationSuccess = false;
let failedRequestMessage = '';
let showTimer: ReturnType<typeof setTimeout> | undefined;
let hideTimer: ReturnType<typeof setTimeout> | undefined;

function clearTimers() {
  if (showTimer) clearTimeout(showTimer);
  if (hideTimer) clearTimeout(hideTimer);
  showTimer = hideTimer = undefined;
}
function scheduleHide(delay: number) {
  if (hideTimer) clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    hideTimer = undefined;
    if (pending.value === 0) visible.value = false;
  }, delay);
}
function start(event: Event) {
  const detail = (event as CustomEvent<RequestDetail>).detail || {};
  const wasIdle = inFlightRequests.size === 0;
  if (typeof detail.requestId === 'number') inFlightRequests.add(detail.requestId);
  if (wasIdle) {
    hadMutationSuccess = false;
    failedRequestMessage = '';
    state.value = 'loading';
  }
  pending.value = Number(detail.pending || 0);
  if (!failedRequestMessage) message.value = pending.value > 1 ? `Memproses ${pending.value} permintaan…` : 'Memproses permintaan…';
  clearTimers();
  showTimer = setTimeout(() => { visible.value = true; showTimer = undefined; }, 120);
}
function end(event: Event) {
  const detail = (event as CustomEvent<RequestDetail>).detail || {};
  pending.value = Number(detail.pending || 0);
  if (typeof detail.requestId === 'number') inFlightRequests.delete(detail.requestId);
  if (inFlightRequests.size === 0) {
    if (failedRequestMessage) {
      state.value = 'error';
      message.value = failedRequestMessage;
      visible.value = true;
      if (showTimer) clearTimeout(showTimer);
      showTimer = undefined;
      scheduleHide(2400);
      return;
    }
    if (hadMutationSuccess) {
      state.value = 'success';
      message.value = 'Permintaan berhasil diterima.';
      visible.value = true;
      if (showTimer) clearTimeout(showTimer);
      showTimer = undefined;
      scheduleHide(1200);
      return;
    }
  }
  if (pending.value === 0 && inFlightRequests.size === 0) {
    if (state.value === 'loading') {
      if (!visible.value) clearTimers();
      else scheduleHide(180);
    } else if (visible.value && !hideTimer) {
      scheduleHide(180);
    }
  }
}
function success(event: Event) {
  const detail = (event as CustomEvent<RequestDetail>).detail || {};
  if (!detail.mutation) return;
  pending.value = Number(detail.pending || 0);
  hadMutationSuccess = true;
  if (failedRequestMessage && inFlightRequests.size) return;
  if (inFlightRequests.size) return;
  state.value = 'success';
  message.value = 'Permintaan berhasil diterima.';
  visible.value = true;
  if (showTimer) clearTimeout(showTimer);
  scheduleHide(1200);
}
function failed(event: Event) {
  const detail = (event as CustomEvent<RequestDetail>).detail || {};
  pending.value = Number(detail.pending || 0);
  failedRequestMessage = detail.message || 'Permintaan gagal diproses.';
  state.value = 'error';
  message.value = failedRequestMessage;
  visible.value = true;
  if (showTimer) clearTimeout(showTimer);
  showTimer = undefined;
  if (inFlightRequests.size === 0) scheduleHide(2400);
}
onMounted(() => {
  window.addEventListener('tme3:request-start', start);
  window.addEventListener('tme3:request-end', end);
  window.addEventListener('tme3:request-success', success);
  window.addEventListener('tme3:request-error', failed);
});
onUnmounted(() => {
  clearTimers();
  window.removeEventListener('tme3:request-start', start);
  window.removeEventListener('tme3:request-end', end);
  window.removeEventListener('tme3:request-success', success);
  window.removeEventListener('tme3:request-error', failed);
});
</script>

<template>
  <div v-if="visible" class="request-indicator" role="status" aria-live="polite">
    <span class="request-progress" :class="state"></span>
    <span class="request-message" :class="state"><span aria-hidden="true">{{ state === 'loading' ? '◌' : state === 'success' ? '✓' : '!' }}</span>{{ message }}</span>
  </div>
</template>
