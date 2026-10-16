import { afterEach, describe, expect, it, vi } from 'vitest';
import { session } from './session.svelte';

describe('browser profile and worker context', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('switches the active worker atomically and emits a context revision', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/browser/session')) {
        return new Response(JSON.stringify({
          authenticated: true,
          actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
          profiles: ['default']
        }), { status: 200 });
      }
      if (url.endsWith('/workers')) {
        return new Response(JSON.stringify({
          items: [
            { name: 'local', url: 'http://worker-local' },
            { name: 'remote-1', url: 'https://worker.example' }
          ]
        }), { status: 200 });
      }
      if (url.endsWith('/me/worker-route') && init?.method === 'PUT') {
        return new Response(JSON.stringify({ route: 'remote-1' }), { status: 200 });
      }
      return new Response('{}', { status: 404 });
    });
    vi.stubGlobal('fetch', fetcher);
    await session.restore();
    const previousRevision = session.contextRevision;
    const changed = vi.fn();
    window.addEventListener('tme3:context-changed', changed, { once: true });

    await session.chooseWorker('remote-1');

    expect(session.current.actor?.worker_route).toBe('remote-1');
    expect(session.workers.find((item) => item.name === 'remote-1')?.selected).toBe(true);
    expect(session.contextRevision).toBe(previousRevision + 1);
    expect(changed).toHaveBeenCalledOnce();
  });

  it('restores an expired browser access cookie by rotating the refresh session', async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method });
      if (url.endsWith('/auth/browser/session')) return new Response('{}', { status: 401 });
      if (url.endsWith('/auth/browser/refresh')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
        profiles: ['default']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local' }
      ] }), { status: 200 });
      return new Response('{}', { status: 404 });
    }));

    await session.restore();

    expect(session.current.authenticated).toBe(true);
    expect(calls.slice(0, 3).map((call) => [call.url.split('/api/v1')[1], call.method])).toEqual([
      ['/auth/browser/session', 'GET'],
      ['/auth/browser/refresh', 'POST'],
      ['/workers', 'GET']
    ]);
  });

  it('sends the Remember me choice with the browser login challenge', async () => {
    let challengeRequest: RequestInit | undefined;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/browser/challenge')) {
        challengeRequest = init;
        return new Response(JSON.stringify({
          verification_uri: 'https://t.me/my_bot?start=login_code',
          expires_at: '2026-10-15T00:00:00Z',
          interval: 2
        }), { status: 200 });
      }
      return new Response('{}', { status: 404 });
    }));

    await session.startLogin(true);

    expect(JSON.parse(String(challengeRequest?.body))).toEqual({ remember_me: true });
    expect(session.challenge?.verification_uri).toContain('login_code');
  });

  it('loads profile choices from the verified catalog without changing actor identity', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || 'GET'} ${url}`);
      if (url.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        actor: { telegram_user_id: 42, profile: 'identity-profile', worker_route: 'local' },
        profiles: ['identity-profile', 'stale-identity-profile']
      }), { status: 200 });
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://worker-local' },
        { name: 'remote-1', url: 'https://worker.example' }
      ] }), { status: 200 });
      if (url.endsWith('/profiles/local')) return new Response(JSON.stringify({ profiles: [
        { name: 'shared', workers: ['local', 'remote-1'], exclusive_worker: '' },
        { name: 'remote-only', workers: ['remote-1'], exclusive_worker: 'remote-1' }
      ] }), { status: 200 });
      return new Response('{}', { status: 404 });
    }));

    await session.restore();
    expect(session.profileCatalog.map((item) => item.name)).toEqual(['remote-only', 'shared']);
    expect(session.selectedTargetProfile).toBe('remote-only');
    session.chooseTargetProfile('shared');

    expect(session.selectedTargetProfile).toBe('shared');
    expect(session.current.actor?.profile).toBe('identity-profile');
    expect(calls.some((call) => call.includes('/profiles/local/scan'))).toBe(false);
    expect(calls.some((call) => call.includes('/auth/browser/profile'))).toBe(false);
  });
});
