import { createRouter, createWebHistory, type RouterHistory } from 'vue-router';
import type { Component } from 'vue';

export type AppRouteDefinition = {
  path: string;
  label: string;
  section: string;
  description: string;
  component: () => Promise<{ default: Component }>;
};

export const routeDefinitions: AppRouteDefinition[] = [
  { path: '/', label: 'Ringkasan', section: 'Monitor', description: 'Job aktif, worker, layanan, dan kegagalan terbaru.', component: () => import('./pages/OverviewPage.vue') },
  { path: '/activity/', label: 'Aktivitas', section: 'Monitor', description: 'Monitor job realtime.', component: () => import('./pages/ActivityPage.vue') },
  { path: '/storage/', label: 'Storage', section: 'Transfer', description: 'Jelajahi dan kelola penyimpanan Telegram atau rclone.', component: () => import('./pages/StoragePage.vue') },
  { path: '/downloads/', label: 'Download', section: 'Transfer', description: 'Kelola antrean dan riwayat unduhan.', component: () => import('./pages/DownloadsPage.vue') },
  { path: '/aria2/', label: 'AriaNg', section: 'Transfer', description: 'Kirim dan pantau tugas aria2 pada worker.', component: () => import('./pages/Aria2Page.vue') },
  { path: '/chat-send/', label: 'Kirim ke Chat', section: 'Transfer', description: 'Kirim file Workspace ke chat Telegram.', component: () => import('./pages/ChatSendPage.vue') },
  { path: '/exports/', label: 'Export', section: 'Pemrosesan', description: 'Ekspor pesan dari sumber Telegram.', component: () => import('./pages/ExportPage.vue') },
  { path: '/quick-mode/', label: 'Quick Mode', section: 'Pemrosesan', description: 'Jalankan dan pulihkan alur Quick Mode.', component: () => import('./pages/QuickModePage.vue') },
  { path: '/tts/', label: 'TTS', section: 'Pemrosesan', description: 'Proses dan kirim audio TTS.', component: () => import('./pages/TtsPage.vue') },
  { path: '/decrypt/', label: 'Dekripsi', section: 'Pemrosesan', description: 'Dekripsi teks dan tautan.', component: () => import('./pages/DecryptPage.vue') },
  { path: '/utility/', label: 'Utility', section: 'Pemrosesan', description: 'Jalankan alat pada folder Workspace.', component: () => import('./pages/UtilityPage.vue') },
  { path: '/backups/', label: 'Backup', section: 'Pemrosesan', description: 'Kelola backup dan pemulihan.', component: () => import('./pages/BackupsPage.vue') },
  { path: '/profiles/', label: 'Profil / Vault', section: 'Sistem', description: 'Periksa profil dan distribusikan sesi.', component: () => import('./pages/ProfilesPage.vue') },
  { path: '/profiles/vault/', label: 'Vault', section: 'Sistem', description: 'Kelola berkas profil aktif.', component: () => import('./pages/ProfileVaultPage.vue') },
  { path: '/workers/', label: 'Workers', section: 'Sistem', description: 'Lihat status dan rute worker.', component: () => import('./pages/WorkersPage.vue') },
  { path: '/settings/', label: 'Pengaturan', section: 'Sistem', description: 'Kelola pengaturan aplikasi.', component: () => import('./pages/SettingsPage.vue') },
  { path: '/development/', label: 'Pengembangan', section: 'Sistem', description: 'Catatan dan laporan pengembangan.', component: () => import('./pages/DevelopmentPage.vue') }
];

export const navigationGroups = ['Monitor', 'Transfer', 'Pemrosesan', 'Sistem'].map((label) => ({
  label,
  links: routeDefinitions.filter((route) => route.section === label && route.path !== '/profiles/vault/')
}));

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    scrollBehavior: () => ({ top: 0 }),
    routes: [
      ...routeDefinitions.map(({ path, component, label }) => ({ path, component, meta: { title: label } })),
      { path: '/:pathMatch(.*)*', redirect: '/' }
    ]
  });
  router.beforeEach((to) => {
    if (to.path !== '/' && routeDefinitions.some((route) => route.path === `${to.path}/`)) {
      return { path: `${to.path}/`, query: to.query, hash: to.hash, replace: true };
    }
  });
  return router;
}
