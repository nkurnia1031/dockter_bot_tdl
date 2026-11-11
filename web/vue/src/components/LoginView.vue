<script setup lang="ts">
import { onUnmounted, ref } from 'vue';
import { session, sessionActions } from '../session';

const rememberMe = ref(false);
const waiting = ref(false);
const error = ref('');
let timer: ReturnType<typeof setTimeout> | undefined;

function clearTimer() {
  if (timer) clearTimeout(timer);
  timer = undefined;
}

async function poll() {
  if (!waiting.value) return;
  try {
    const result = await sessionActions.pollLogin();
    if (result.authenticated) {
      waiting.value = false;
      return;
    }
    timer = setTimeout(() => { void poll(); }, Math.max(1, Number(session.challenge?.interval || 2)) * 1000);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Status login gagal diperiksa.';
    waiting.value = false;
    session.challenge = null;
  }
}

async function beginLogin() {
  error.value = '';
  clearTimer();
  try {
    await sessionActions.startLogin(rememberMe.value);
    waiting.value = true;
    timer = setTimeout(() => { void poll(); }, Math.max(1, Number(session.challenge?.interval || 2)) * 1000);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Login gagal dimulai.';
  }
}

onUnmounted(clearTimer);
</script>

<template>
  <main class="login-screen">
    <section class="login-card">
      <div class="brand-mark brand-mark-large" aria-hidden="true"><span></span><span></span><span></span></div>
      <p class="eyebrow">TME3BOT · OPERATIONS</p>
      <h1>Masuk dengan Telegram</h1>
      <p class="muted login-description">Otorisasi dilakukan melalui bot. Token akses tetap berada pada cookie HttpOnly.</p>
      <a v-if="session.challenge" class="button login-primary" :href="session.challenge.verification_uri" target="_blank" rel="noreferrer">Buka bot Telegram <span aria-hidden="true">↗</span></a>
      <div v-if="session.challenge" class="notice login-wait" role="status">
        <span class="state-dot state-running" aria-hidden="true"></span>
        {{ waiting ? 'Menunggu persetujuan pada perangkat ini…' : 'Selesaikan verifikasi di Telegram.' }}
      </div>
      <template v-else>
        <label class="remember-option"><input v-model="rememberMe" type="checkbox" /><span><strong>Ingat saya</strong><small>Sesi browser tetap aktif sampai Anda logout.</small></span></label>
        <button class="button login-primary" type="button" @click="beginLogin">Mulai login <span aria-hidden="true">→</span></button>
      </template>
      <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
    </section>
  </main>
</template>
