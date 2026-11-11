<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import { navigationGroups } from '../router';
import NavIcon from './NavIcon.vue';
import { session, sessionActions } from '../session';
import { applyTheme, resolveTheme, type ThemePreference } from '../theme';

const route = useRoute();
const isDev = import.meta.env.DEV;
const mobileOpen = ref(false);
const mobileMenuButton = ref<HTMLButtonElement | null>(null);
const mobileDrawer = ref<HTMLElement | null>(null);
const mobileCloseButton = ref<HTMLButtonElement | null>(null);
let mobileReturnFocus: HTMLElement | null = null;
const collapsed = ref(false);
const accountOpen = ref(false);
const theme = ref<ThemePreference>('dark');
const actorInitials = computed(() => String(session.current.actor?.telegram_user_id || '?').slice(-2));
const workerRoute = computed(() => session.current.actor?.worker_route || 'Belum dipilih');
const navIcons: Record<string, string> = {
  '/': 'dashboard', '/activity/': 'activity', '/storage/': 'storage', '/downloads/': 'download',
  '/aria2/': 'aria', '/chat-send/': 'send', '/exports/': 'export', '/quick-mode/': 'quick',
  '/tts/': 'tts', '/decrypt/': 'decrypt', '/utility/': 'utility', '/backups/': 'backup',
  '/profiles/': 'profile', '/workers/': 'workers', '/settings/': 'settings', '/development/': 'development'
};

function setTheme(value: string) {
  theme.value = resolveTheme(value);
  localStorage.setItem('tme3-theme', theme.value);
  applyTheme(theme.value);
}
function isActive(path: string) {
  return path === '/' ? route.path === '/' : route.path === path || route.path.startsWith(path);
}
function toggleSidebar() {
  collapsed.value = !collapsed.value;
  localStorage.setItem('tme3-sidebar-collapsed', String(collapsed.value));
}
async function logout() {
  accountOpen.value = false;
  await sessionActions.logout();
}

function openMobileNav() {
  mobileReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : mobileMenuButton.value;
  mobileOpen.value = true;
  void nextTick(() => mobileCloseButton.value?.focus());
}

async function closeMobileNav() {
  mobileOpen.value = false;
  const target = mobileReturnFocus;
  mobileReturnFocus = null;
  await nextTick();
  if (target?.isConnected) target.focus();
}

function handleMobileDrawerKeydown(event: KeyboardEvent) {
  const drawer = mobileDrawer.value;
  if (!drawer) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    void closeMobileNav();
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = [...drawer.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((element) => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true');
  if (!focusable.length) {
    event.preventDefault();
    drawer.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
    event.preventDefault();
    first.focus();
  }
}

watch(() => route.fullPath, () => { if (mobileOpen.value) void closeMobileNav(); accountOpen.value = false; });
onMounted(() => {
  collapsed.value = localStorage.getItem('tme3-sidebar-collapsed') === 'true';
  theme.value = resolveTheme(localStorage.getItem('tme3-theme'));
  applyTheme(theme.value);
});
</script>

<template>
  <div class="application" :class="{ 'sidebar-is-collapsed': collapsed }">
    <aside class="desktop-sidebar" :class="{ collapsed }" aria-label="Navigasi utama">
      <div class="sidebar-brand">
        <RouterLink class="brand-lockup" to="/" aria-label="TME3Bot Ringkasan">
          <span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></span>
          <span class="brand-name"><strong>TME3Bot</strong><small>Operations</small></span>
        </RouterLink>
        <button class="icon-button collapse-control" type="button" :aria-label="collapsed ? 'Lebarkan sidebar' : 'Ringkas sidebar'" :aria-expanded="!collapsed" @click="toggleSidebar">{{ collapsed ? '›' : '‹' }}</button>
      </div>
      <nav class="side-nav">
        <section v-for="group in navigationGroups" :key="group.label" class="nav-group" :aria-label="group.label">
          <h2 class="nav-group-title">{{ group.label }}</h2>
          <RouterLink v-for="link in group.links" :key="link.path" class="nav-link" :class="{ active: isActive(link.path) }" :to="link.path" :aria-current="isActive(link.path) ? 'page' : undefined" :title="collapsed ? link.label : undefined">
            <span class="nav-symbol"><NavIcon :name="navIcons[link.path] || 'settings'" /></span>
            <span class="nav-label">{{ link.label }}</span>
            <span v-if="isActive(link.path)" class="nav-active-mark" aria-hidden="true"></span>
          </RouterLink>
        </section>
      </nav>
      <div class="sidebar-footer">
        <div class="worker-summary"><span class="route-mark" aria-hidden="true">W</span><span class="worker-summary-text"><strong>{{ workerRoute }}</strong><small>Worker route profil</small></span></div>
        <span class="sidebar-version">TME3BOT CONTROL</span>
      </div>
    </aside>

    <main class="main-column">
      <header class="topbar">
        <div class="topbar-start">
          <button ref="mobileMenuButton" class="icon-button mobile-menu" type="button" aria-label="Buka navigasi" :aria-expanded="mobileOpen" @click="openMobileNav">☰</button>
          <div class="breadcrumb"><span>OPERATIONS</span><i aria-hidden="true">/</i><strong>{{ route.meta.title || 'TME3Bot' }}</strong></div>
        </div>
        <div class="topbar-end">
          <label class="target-picker"><span>Profil target</span><select aria-label="Profil target default" :value="session.selectedTargetProfile" :disabled="session.profileCatalog.length < 2" @change="sessionActions.chooseTargetProfile(($event.target as HTMLSelectElement).value)"><option v-if="!session.profileCatalog.length" value="">Belum scan</option><option v-for="profile in session.profileCatalog" :key="profile.name" :value="profile.name">{{ profile.name }}</option></select></label>
          <select class="theme-picker" aria-label="Tema" :value="theme" @change="setTheme(($event.target as HTMLSelectElement).value)"><option value="dark">Gelap</option><option value="light">Terang</option><option value="system">Sistem</option></select>
          <div class="account-menu">
            <button class="account-trigger" type="button" aria-label="Menu akun" :aria-expanded="accountOpen" @click="accountOpen = !accountOpen"><span class="account-avatar">{{ actorInitials }}</span><span class="account-id">{{ session.current.actor?.telegram_user_id }}</span><span aria-hidden="true">⌄</span></button>
            <div v-if="accountOpen" class="account-popover">
              <small>Telegram user</small><strong>{{ session.current.actor?.telegram_user_id }}</strong>
              <small>Identity profile</small><strong>{{ session.current.actor?.profile || '—' }}</strong>
              <button class="logout-button" type="button" @click="logout">Keluar</button>
            </div>
          </div>
        </div>
      </header>

      <div v-if="isDev" class="preview-banner"><span class="preview-dot"></span>Mode pengembangan · perubahan lokal belum dideploy</div>
      <section class="page-content">
        <RouterView v-slot="{ Component, route: viewRoute }">
          <Transition name="route" mode="out-in">
            <component :is="Component" :key="viewRoute.path" />
          </Transition>
        </RouterView>
      </section>
    </main>
  </div>

  <Transition name="drawer">
    <div v-if="mobileOpen" class="mobile-overlay" @click.self="closeMobileNav">
      <aside ref="mobileDrawer" class="mobile-drawer" role="dialog" aria-modal="true" aria-label="Navigasi mobile" tabindex="-1" @keydown="handleMobileDrawerKeydown">
        <div class="sidebar-brand"><RouterLink class="brand-lockup" to="/" @click="closeMobileNav"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></span><span class="brand-name"><strong>TME3Bot</strong><small>Operations</small></span></RouterLink><button ref="mobileCloseButton" class="icon-button" type="button" aria-label="Tutup navigasi" @click="closeMobileNav">×</button></div>
        <nav class="side-nav">
          <section v-for="group in navigationGroups" :key="group.label" class="nav-group"><h2 class="nav-group-title">{{ group.label }}</h2><RouterLink v-for="link in group.links" :key="link.path" class="nav-link" :class="{ active: isActive(link.path) }" :to="link.path"><span class="nav-symbol"><NavIcon :name="navIcons[link.path] || 'settings'" /></span><span class="nav-label">{{ link.label }}</span></RouterLink></section>
        </nav>
        <div class="worker-summary mobile-worker"><span class="route-mark" aria-hidden="true">W</span><span class="worker-summary-text"><strong>{{ workerRoute }}</strong><small>Worker route profil</small></span></div>
      </aside>
    </div>
  </Transition>
</template>
