import { createMemoryHistory } from 'vue-router';
import { describe, expect, it } from 'vitest';
import { createAppRouter, navigationGroups, routeDefinitions } from './router';
import DownloadsPage from './pages/DownloadsPage.vue';
import Aria2Page from './pages/Aria2Page.vue';

describe('Vue route map', () => {
  it('registers every existing static URL, including the nested Vault page', () => {
    expect(routeDefinitions.map(({ path }) => path)).toEqual([
      '/', '/activity/', '/storage/', '/downloads/', '/aria2/', '/chat-send/',
      '/exports/', '/quick-mode/', '/tts/', '/decrypt/', '/utility/', '/backups/',
      '/profiles/', '/profiles/vault/', '/workers/', '/settings/', '/development/'
    ]);
  });

  it('groups all routes under the four approved navigation sections', () => {
    expect(navigationGroups.map(({ label }) => label)).toEqual(['Monitor', 'Transfer', 'Pemrosesan', 'Sistem']);
    expect(navigationGroups.flatMap(({ links }) => links.map(({ path }) => path)).sort()).toEqual(
      routeDefinitions.filter(({ path }) => path !== '/profiles/vault/').map(({ path }) => path).sort()
    );
  });

  it('mounts the Vue Download Manager instead of the migration placeholder', () => {
    expect(routeDefinitions.find(({ path }) => path === '/downloads/')?.component).toBe(DownloadsPage);
  });

  it('mounts the Vue AriaNg page instead of the migration placeholder', () => {
    expect(routeDefinitions.find(({ path }) => path === '/aria2/')?.component).toBe(Aria2Page);
  });

  it('redirects slashless feature URLs to the existing trailing-slash form', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/profiles/vault?tab=active');
    expect(router.currentRoute.value.fullPath).toBe('/profiles/vault/?tab=active');
  });
});
