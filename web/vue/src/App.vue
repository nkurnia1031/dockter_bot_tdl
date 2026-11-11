<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import LoginView from './components/LoginView.vue';
import OperationsShell from './components/OperationsShell.vue';
import RequestIndicator from './components/RequestIndicator.vue';
import { session, sessionActions } from './session';
import { applyTheme, resolveTheme } from './theme';

function applySavedTheme() {
  applyTheme(resolveTheme(localStorage.getItem('tme3-theme')));
}

applySavedTheme();
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
const onSystemThemeChange = () => applySavedTheme();

onMounted(() => {
  systemTheme.addEventListener('change', onSystemThemeChange);
  void sessionActions.restore();
});
onUnmounted(() => systemTheme.removeEventListener('change', onSystemThemeChange));
</script>

<template>
  <RequestIndicator />
  <main v-if="session.loading" class="boot-screen" role="status">
    <section class="boot-card">
      <div class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></div>
      <p class="eyebrow">TME3BOT</p>
      <h1>Menyiapkan control center</h1>
      <p class="muted">Memulihkan sesi browser yang aman…</p>
    </section>
  </main>
  <LoginView v-else-if="!session.current.authenticated" />
  <OperationsShell v-else />
</template>
