import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import Login from './Login.svelte';
import { session } from '$lib/session.svelte';

describe('Login', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('sends the checked Remember me option with the Telegram challenge', async () => {
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith('/auth/browser/challenge') && init?.method === 'POST') {
        return new Response(JSON.stringify({
          verification_uri: 'https://t.me/my_bot?start=login_code',
          expires_at: '2026-10-15T00:00:00Z',
          interval: 2
        }), { status: 200 });
      }
      if (url.endsWith('/auth/browser/challenge') && init?.method === 'GET') {
        return new Response(JSON.stringify({
          authenticated: true,
          actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
          profiles: ['default']
        }), { status: 200 });
      }
      if (url.endsWith('/workers')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/auth/browser/logout')) return new Response(JSON.stringify({ revoked: true }), { status: 200 });
      return new Response('{}', { status: 404 });
    }));
    render(Login);

    const rememberMe = screen.getByRole('checkbox', { name: /Ingat saya/ });
    await fireEvent.click(rememberMe);
    expect((rememberMe as HTMLInputElement).checked).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: 'Mulai login' }));

    expect(await screen.findByRole('link', { name: 'Buka bot Telegram' })).toBeTruthy();
    await screen.findByRole('button', { name: 'Mulai login' }, { timeout: 10000 });
    const challengeRequest = requests.find((request) =>
      request.url.endsWith('/auth/browser/challenge') && request.init?.method === 'POST'
    );
    expect(JSON.parse(String(challengeRequest?.init?.body))).toEqual({ remember_me: true });
    await session.logout();
  }, 15000);
});
