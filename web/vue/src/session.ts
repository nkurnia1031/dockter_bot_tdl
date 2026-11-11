import { reactive } from 'vue';
import { api, post, put } from './lib/api';

export type BrowserActor = { telegram_user_id: number; profile: string; worker_route: string };
export type BrowserSession = { authenticated: boolean; actor?: BrowserActor; profiles: string[] };
export type WorkerOption = { name: string; url: string; public_url?: string; enabled?: boolean; selected?: boolean };
export type ProfileOption = { name: string; workers: string[]; exclusive_worker: string };
export type LoginChallenge = { verification_uri: string; expires_at: string; interval: number };

type SessionState = {
  current: BrowserSession;
  workers: WorkerOption[];
  profileCatalog: ProfileOption[];
  selectedTargetProfile: string;
  loading: boolean;
  switching: boolean;
  challenge: LoginChallenge | null;
};

export const session = reactive<SessionState>({
  current: { authenticated: false, profiles: [] },
  workers: [],
  profileCatalog: [],
  selectedTargetProfile: '',
  loading: true,
  switching: false,
  challenge: null
});

let generation = 0;
let restorePromise: Promise<void> | null = null;
let contextRevision = 0;

function emitContextChanged() {
  contextRevision += 1;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('tme3:context-changed', {
      detail: {
        revision: contextRevision,
        profile: session.current.actor?.profile,
        worker: session.current.actor?.worker_route
      }
    }));
  }
}

function selectedWorkers(items: WorkerOption[], route?: string) {
  return items.map((item) => ({ ...item, selected: item.name === route }));
}

async function loadContext(next: BrowserSession) {
  const [workerResult, profileResult] = await Promise.allSettled([
    api<{ items: WorkerOption[] }>('/workers'),
    api<Record<string, unknown>>('/profiles/local')
  ]);
  if (workerResult.status === 'fulfilled') {
    session.workers = selectedWorkers(workerResult.value.items || [], next.actor?.worker_route);
  } else {
    session.workers = [];
  }
  if (profileResult.status === 'fulfilled') {
    const items = profileResult.value.profiles;
    session.profileCatalog = Array.isArray(items)
      ? items.filter((item): item is ProfileOption => Boolean(item && typeof item === 'object' && typeof (item as ProfileOption).name === 'string'))
      : [];
  } else {
    session.profileCatalog = [];
  }
  if (!session.profileCatalog.some((item) => item.name === session.selectedTargetProfile)) {
    const preferred = next.actor?.profile || '';
    session.selectedTargetProfile = session.profileCatalog.some((item) => item.name === preferred)
      ? preferred
      : session.profileCatalog[0]?.name || '';
  }
}

function clearSession() {
  session.current = { authenticated: false, profiles: [] };
  session.workers = [];
  session.profileCatalog = [];
  session.selectedTargetProfile = '';
  session.challenge = null;
}

export const sessionActions = {
  async restore(): Promise<void> {
    if (restorePromise) return restorePromise;
    const request = ++generation;
    restorePromise = (async () => {
      try {
        let restored: BrowserSession;
        try {
          restored = await api<BrowserSession>('/auth/browser/session');
        } catch (cause) {
          if ((cause as { status?: number })?.status !== 401) throw cause;
          restored = await api<BrowserSession>('/auth/browser/refresh', { method: 'POST' });
        }
        if (request !== generation) return;
        session.current = restored;
        if (restored.authenticated) await loadContext(restored);
        else clearSession();
      } catch {
        if (request === generation) clearSession();
      } finally {
        if (request === generation) session.loading = false;
        restorePromise = null;
      }
    })();
    return restorePromise;
  },
  async startLogin(rememberMe = false): Promise<void> {
    session.challenge = await post<LoginChallenge>('/auth/browser/challenge', { remember_me: rememberMe });
  },
  async pollLogin(): Promise<BrowserSession> {
    const next = await api<BrowserSession>('/auth/browser/challenge');
    if (next.authenticated) {
      session.current = next;
      session.challenge = null;
      await loadContext(next);
    }
    return next;
  },
  async refreshProfileCatalog(): Promise<void> {
    try {
      const result = await api<Record<string, unknown>>('/profiles/local');
      const items = Array.isArray(result.profiles) ? result.profiles : [];
      session.profileCatalog = items.filter((item): item is ProfileOption =>
        Boolean(item && typeof item === 'object' && typeof (item as ProfileOption).name === 'string')
      );
      if (!session.profileCatalog.some((item) => item.name === session.selectedTargetProfile)) {
        const preferred = session.current.actor?.profile || '';
        session.selectedTargetProfile = session.profileCatalog.some((item) => item.name === preferred)
          ? preferred
          : session.profileCatalog[0]?.name || '';
      }
    } catch {
      // Keep the last known catalogue when a refresh fails transiently.
    }
  },
  async chooseProfile(profile: string): Promise<void> {
    if (session.switching || profile === session.current.actor?.profile) return;
    session.switching = true;
    try {
      session.current = await put<BrowserSession>('/auth/browser/profile', { profile });
      session.workers = selectedWorkers(session.workers, session.current.actor?.worker_route);
      emitContextChanged();
    } finally {
      session.switching = false;
    }
  },
  chooseTargetProfile(profile: string): void {
    if (!session.profileCatalog.some((item) => item.name === profile) || profile === session.selectedTargetProfile) return;
    session.selectedTargetProfile = profile;
    contextRevision += 1;
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('tme3:target-profile-changed', {
        detail: { revision: contextRevision, profile }
      }));
    }
  },
  async chooseWorker(route: string): Promise<void> {
    if (session.switching || route === session.current.actor?.worker_route) return;
    session.switching = true;
    try {
      await put('/me/worker-route', { route });
      if (session.current.actor) session.current.actor.worker_route = route;
      session.workers = selectedWorkers(session.workers, route);
      emitContextChanged();
    } finally {
      session.switching = false;
    }
  },
  async logout(): Promise<void> {
    await post('/auth/browser/logout');
    generation += 1;
    clearSession();
  }
};
