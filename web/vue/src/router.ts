import { createRouter, createWebHistory, type RouterHistory } from 'vue-router';
import type { Component } from 'vue';
import OverviewPage from './pages/OverviewPage.vue';
import ActivityPage from './pages/ActivityPage.vue';
import ProfilesPage from './pages/ProfilesPage.vue';
import ProfileVaultPage from './pages/ProfileVaultPage.vue';
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
  placeholder('/storage/', 'Storage', 'Transfer', 'Jelajahi dan kelola penyimpanan Telegram atau rclone.'),
  placeholder('/downloads/', 'Download', 'Transfer', 'Kelola antrean dan riwayat unduhan.'),
  placeholder('/aria2/', 'AriaNg', 'Transfer', 'Kirim dan pantau tugas aria2 pada worker.'),
  placeholder('/chat-send/', 'Kirim ke Chat', 'Transfer', 'Kirim file Workspace ke chat Telegram.'),
  placeholder('/exports/', 'Export', 'Pemrosesan', 'Ekspor pesan dari sumber Telegram.'),
  placeholder('/quick-mode/', 'Quick Mode', 'Pemrosesan', 'Jalankan alur Quick Mode.'),
  placeholder('/tts/', 'TTS', 'Pemrosesan', 'Proses dan kirim audio TTS.'),
  placeholder('/decrypt/', 'Dekripsi', 'Pemrosesan', 'Dekripsi teks dan tautan.'),
  placeholder('/utility/', 'Utility', 'Pemrosesan', 'Jalankan alat pada folder Workspace.'),
  placeholder('/backups/', 'Backup', 'Pemrosesan', 'Kelola backup dan pemulihan.'),
  { path: '/profiles/', label: 'Profil / Vault', section: 'Sistem', description: 'Periksa profil dan distribusikan sesi.', component: ProfilesPage },
  { path: '/profiles/vault/', label: 'Vault', section: 'Sistem', description: 'Kelola berkas profil aktif.', component: ProfileVaultPage },
  placeholder('/workers/', 'Workers', 'Sistem', 'Lihat status dan rute worker.'),
  placeholder('/settings/', 'Pengaturan', 'Sistem', 'Kelola pengaturan aplikasi.'),
  placeholder('/development/', 'Pengembangan', 'Sistem', 'Catatan dan laporan pengembangan.')
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
