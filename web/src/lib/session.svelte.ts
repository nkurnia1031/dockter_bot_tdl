import { api, post, put } from './api';

export type Session = { authenticated: boolean; actor?: { telegram_user_id: number; profile: string; worker_route: string }; profiles: string[] };
export type SessionWorker = { name: string; url: string; selected?: boolean };
let current = $state<Session>({ authenticated: false, profiles: [] });
let workers = $state<SessionWorker[]>([]);
let loading = $state(true);
let switching = $state(false);
let contextRevision = $state(0);
let challenge = $state<{ verification_uri: string; expires_at: string; interval: number } | null>(null);
let generation = 0;

const selectedWorkers = (items: SessionWorker[], route?: string) =>
  items.map((item) => ({ ...item, selected: item.name === route }));

async function loadWorkers(route?: string): Promise<SessionWorker[]> {
  const response = await api<{items: SessionWorker[]}>('/workers');
  return selectedWorkers(response.items || [], route);
}

function contextChanged() {
  contextRevision += 1;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('tme3:context-changed', {
      detail: {
        revision: contextRevision,
        profile: current.actor?.profile,
        worker: current.actor?.worker_route
      }
    }));
  }
}

export const session = {
  get current() { return current; },
  get workers() { return workers; },
  get loading() { return loading; },
  get switching() { return switching; },
  get contextRevision() { return contextRevision; },
  get challenge() { return challenge; },
  async restore() {
    const request = ++generation;
    try {
      const restored = await api<Session>('/auth/browser/session');
      const restoredWorkers = restored.authenticated
        ? await loadWorkers(restored.actor?.worker_route)
        : [];
      if (request !== generation) return;
      current = restored;
      workers = restoredWorkers;
    } catch {
      if (request !== generation) return;
      current = { authenticated: false, profiles: [] };
      workers = [];
    } finally {
      if (request === generation) loading = false;
    }
  },
  async startLogin() { challenge = await post('/auth/browser/challenge'); },
  async pollLogin() {
    const next = await api<Session>('/auth/browser/challenge');
    current = next;
    if (current.authenticated) {
      workers = await loadWorkers(current.actor?.worker_route);
      challenge = null;
      contextChanged();
    }
    return current;
  },
  async chooseProfile(profile: string) {
    if (switching || profile === current.actor?.profile) return;
    const request = ++generation;
    switching = true;
    try {
      const next = await put<Session>('/auth/browser/profile', { profile });
      if (request !== generation) return;
      current = next;
      workers = selectedWorkers(workers, next.actor?.worker_route);
      contextChanged();
    } finally {
      if (request === generation) switching = false;
    }
  },
  async chooseWorker(route: string) {
    if (switching || route === current.actor?.worker_route) return;
    const request = ++generation;
    switching = true;
    try {
      await put<{route: string}>('/me/worker-route', { route });
      if (request !== generation) return;
      if (current.actor) current = {
        ...current,
        actor: { ...current.actor, worker_route: route }
      };
      workers = selectedWorkers(workers, route);
      contextChanged();
    } finally {
      if (request === generation) switching = false;
    }
  },
  async logout() {
    await post('/auth/browser/logout');
    current = { authenticated: false, profiles: [] };
    workers = [];
    challenge = null;
  }
};
