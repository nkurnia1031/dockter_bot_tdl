import { createMemoryHistory } from 'vue-router';
import { describe, expect, it } from 'vitest';
import { createAppRouter, navigationGroups, routeDefinitions } from './router';
import DownloadsPage from './pages/DownloadsPage.vue';
import Aria2Page from './pages/Aria2Page.vue';
import ChatSendPage from './pages/ChatSendPage.vue';
import ExportPage from './pages/ExportPage.vue';
import TtsPage from './pages/TtsPage.vue';
import QuickModePage from './pages/QuickModePage.vue';
import DecryptPage from './pages/DecryptPage.vue';
import UtilityPage from './pages/UtilityPage.vue';
import BackupsPage from './pages/BackupsPage.vue';

async function resolveRoutePage(path: string) {
  const component = routeDefinitions.find((route) => route.path === path)?.component;
  if (!component) throw new Error(`Missing route ${path}`);
  return (await component()).default;
}

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

  it('lazy-loads the Vue Download Manager instead of the migration placeholder', async () => {
    expect(await resolveRoutePage('/downloads/')).toBe(DownloadsPage);
  });

  it('lazy-loads the Vue AriaNg page instead of the migration placeholder', async () => {
    expect(await resolveRoutePage('/aria2/')).toBe(Aria2Page);
  });

  it('lazy-loads the Vue Chat Send page instead of the migration placeholder', async () => {
    expect(await resolveRoutePage('/chat-send/')).toBe(ChatSendPage);
  });

  it('lazy-loads the Vue Export and TTS pages instead of migration placeholders', async () => {
    expect(await resolveRoutePage('/exports/')).toBe(ExportPage);
    expect(await resolveRoutePage('/tts/')).toBe(TtsPage);
  });

  it('lazy-loads the Vue Quick Mode page instead of the migration placeholder', async () => {
    expect(await resolveRoutePage('/quick-mode/')).toBe(QuickModePage);
  });

  it('lazy-loads Vue Decrypt, Utility, and Backup pages instead of migration placeholders', async () => {
    expect(await resolveRoutePage('/decrypt/')).toBe(DecryptPage);
    expect(await resolveRoutePage('/utility/')).toBe(UtilityPage);
    expect(await resolveRoutePage('/backups/')).toBe(BackupsPage);
  });

  it('redirects slashless feature URLs to the existing trailing-slash form', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/profiles/vault?tab=active');
    expect(router.currentRoute.value.fullPath).toBe('/profiles/vault/?tab=active');
  });
});
