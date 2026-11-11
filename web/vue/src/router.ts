import { createRouter, createWebHistory, type RouterHistory } from 'vue-router';
import type { Component } from 'vue';
import OverviewPage from './pages/OverviewPage.vue';
import ActivityPage from './pages/ActivityPage.vue';
import ProfilesPage from './pages/ProfilesPage.vue';
import ProfileVaultPage from './pages/ProfileVaultPage.vue';
import WorkersPage from './pages/WorkersPage.vue';
import SettingsPage from './pages/SettingsPage.vue';
import DevelopmentPage from './pages/DevelopmentPage.vue';
import StoragePage from './pages/StoragePage.vue';
import DownloadsPage from './pages/DownloadsPage.vue';
import Aria2Page from './pages/Aria2Page.vue';
import PlaceholderPage from './pages/PlaceholderPage.vue';

export type AppRouteDefinition = {
  path: string;
  label: string;
  section: string;
  description: string;
  component: Component;
};

const placeholder = (path: string, label: string, section: string, description: string): AppRouteDefinition => ({
  path, label, section, description, component: PlaceholderPage
});

export const routeDefinitions: AppRouteDefinition[] = [
  { path: '/', label: 'Ringkasan', section: 'Monitor', description: 'Job aktif, worker, layanan, dan kegagalan terbaru.', component: OverviewPage },
  { path: '/activity/', label: 'Aktivitas', section: 'Monitor', description: 'Monitor job realtime.', component: ActivityPage },
  { path: '/storage/', label: 'Storage', section: 'Transfer', description: 'Jelajahi dan kelola penyimpanan Telegram atau rclone.', component: StoragePage },
  { path: '/downloads/', label: 'Download', section: 'Transfer', description: 'Kelola antrean dan riwayat unduhan.', component: DownloadsPage },
  { path: '/aria2/', label: 'AriaNg', section: 'Transfer', description: 'Kirim dan pantau tugas aria2 pada worker.', component: Aria2Page },
  placeholder('/chat-send/', 'Kirim ke Chat', 'Transfer', 'Kirim file Workspace ke chat Telegram.'),
  placeholder('/exports/', 'Export', 'Pemrosesan', 'Ekspor pesan dari sumber Telegram.'),
  placeholder('/quick-mode/', 'Quick Mode', 'Pemrosesan', 'Jalankan alur Quick Mode.'),
  placeholder('/tts/', 'TTS', 'Pemrosesan', 'Proses dan kirim audio TTS.'),
  placeholder('/decrypt/', 'Dekripsi', 'Pemrosesan', 'Dekripsi teks dan tautan.'),
  placeholder('/utility/', 'Utility', 'Pemrosesan', 'Jalankan alat pada folder Workspace.'),
  placeholder('/backups/', 'Backup', 'Pemrosesan', 'Kelola backup dan pemulihan.'),
  { path: '/profiles/', label: 'Profil / Vault', section: 'Sistem', description: 'Periksa profil dan distribusikan sesi.', component: ProfilesPage },
  { path: '/profiles/vault/', label: 'Vault', section: 'Sistem', description: 'Kelola berkas profil aktif.', component: ProfileVaultPage },
  { path: '/workers/', label: 'Workers', section: 'Sistem', description: 'Lihat status dan rute worker.', component: WorkersPage },
  { path: '/settings/', label: 'Pengaturan', section: 'Sistem', description: 'Kelola pengaturan aplikasi.', component: SettingsPage },
  { path: '/development/', label: 'Pengembangan', section: 'Sistem', description: 'Catatan dan laporan pengembangan.', component: DevelopmentPage }
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
