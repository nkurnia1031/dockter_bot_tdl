import { beforeEach, describe, expect, it, vi } from 'vitest';
import { session, sessionActions } from './session';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock('./lib/api', () => ({ api: mocks.api, post: mocks.post, put: mocks.put }));

describe('browser session', () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.post.mockReset();
    mocks.put.mockReset();
    session.current = { authenticated: false, profiles: [] };
    session.workers = [];
    session.profileCatalog = [];
    session.selectedTargetProfile = '';
    session.loading = true;
    session.switching = false;
    session.challenge = null;
  });

  it('restores the cookie session and loads worker/profile context without token data', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/auth/browser/session') return Promise.resolve({ authenticated: true, actor: { telegram_user_id: 7, profile: 'default', worker_route: 'local' }, profiles: ['default'] });
      if (path === '/workers') return Promise.resolve({ items: [{ name: 'local', url: 'https://worker.invalid', enabled: true }] });
      if (path === '/profiles/local') return Promise.resolve({ profiles: [{ name: 'default', workers: ['local'], exclusive_worker: 'local' }] });
      throw new Error(`Unexpected API path ${path}`);
    });

    await sessionActions.restore();

    expect(session.current.authenticated).toBe(true);
    expect(session.current.actor?.profile).toBe('default');
    expect(session.workers[0]).toMatchObject({ name: 'local', selected: true });
    expect(session.selectedTargetProfile).toBe('default');
    expect(JSON.stringify(session.current)).not.toContain('access_token');
  });

  it('keeps login challenge in browser state and exchanges it through the existing cookie endpoint', async () => {
    mocks.post.mockResolvedValue({ verification_uri: 'https://t.me/example', expires_at: 'later', interval: 2 });
    mocks.api.mockImplementation((path: string) => {
      if (path === '/auth/browser/challenge') return Promise.resolve({ authenticated: true, actor: { telegram_user_id: 8, profile: 'default', worker_route: 'local' }, profiles: ['default'] });
      if (path === '/workers') return Promise.resolve({ items: [] });
      if (path === '/profiles/local') return Promise.resolve({ profiles: [] });
      throw new Error(`Unexpected API path ${path}`);
    });

    await sessionActions.startLogin(true);
    expect(session.challenge?.verification_uri).toBe('https://t.me/example');
    await sessionActions.pollLogin();

    expect(session.current.authenticated).toBe(true);
    expect(session.challenge).toBeNull();
    expect(mocks.post).toHaveBeenCalledWith('/auth/browser/challenge', { remember_me: true });
  });

  it('refreshes an expired access cookie before treating the browser as logged out', async () => {
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/auth/browser/session') return Promise.reject(Object.assign(new Error('expired'), { status: 401 }));
      if (path === '/auth/browser/refresh' && init?.method === 'POST') return Promise.resolve({ authenticated: true, actor: { telegram_user_id: 9, profile: 'default', worker_route: 'local' }, profiles: ['default'] });
      if (path === '/workers') return Promise.resolve({ items: [] });
      if (path === '/profiles/local') return Promise.resolve({ profiles: [] });
      throw new Error(`Unexpected API path ${path}`);
    });

    await sessionActions.restore();

    expect(session.current.authenticated).toBe(true);
    expect(mocks.api).toHaveBeenCalledWith('/auth/browser/refresh', { method: 'POST' });
  });

  it('emits target and context events when selectors change', async () => {
    session.current = { authenticated: true, actor: { telegram_user_id: 17, profile: 'default', worker_route: 'local' }, profiles: ['default'] };
    session.profileCatalog = [
      { name: 'default', workers: ['local'], exclusive_worker: 'local' },
      { name: 'irang', workers: ['remote-1'], exclusive_worker: 'remote-1' }
    ];
    const targetChanged = vi.fn();
    const contextChanged = vi.fn();
    window.addEventListener('tme3:target-profile-changed', targetChanged);
    window.addEventListener('tme3:context-changed', contextChanged);
    mocks.put.mockResolvedValue({ route: 'remote-1' });

    sessionActions.chooseTargetProfile('irang');
    await sessionActions.chooseWorker('remote-1');

    expect(targetChanged).toHaveBeenCalledOnce();
    expect(contextChanged).toHaveBeenCalledOnce();
    expect(session.selectedTargetProfile).toBe('irang');
    expect(session.current.actor?.worker_route).toBe('remote-1');
    window.removeEventListener('tme3:target-profile-changed', targetChanged);
    window.removeEventListener('tme3:context-changed', contextChanged);
  });
});
