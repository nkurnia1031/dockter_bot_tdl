import { api, post, put } from './api';

export type Session = { authenticated: boolean; actor?: { telegram_user_id: number; profile: string; worker_route: string }; profiles: string[] };
let current = $state<Session>({ authenticated: false, profiles: [] });
let loading = $state(true);
let challenge = $state<{ verification_uri: string; expires_at: string; interval: number } | null>(null);

export const session = {
  get current() { return current; }, get loading() { return loading; }, get challenge() { return challenge; },
  async restore() { try { current = await api<Session>('/auth/browser/session'); } catch { current = { authenticated: false, profiles: [] }; } finally { loading = false; } },
  async startLogin() { challenge = await post('/auth/browser/challenge'); },
  async pollLogin() { current = await api<Session>('/auth/browser/challenge'); if (current.authenticated) challenge = null; return current; },
  async chooseProfile(profile: string) { current = await put<Session>('/auth/browser/profile', { profile }); },
  async logout() { await post('/auth/browser/logout'); current = { authenticated: false, profiles: [] }; challenge = null; }
};
