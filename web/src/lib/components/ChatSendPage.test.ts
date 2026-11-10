import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ChatSendPage from './ChatSendPage.svelte';
import { session } from '../session.svelte';

describe('Kirim ke Chat page', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('submits selected worker, rotating profiles, chat reference, and Workspace folders', async () => {
    const submission = vi.fn<(url: string, init: RequestInit) => void>();
    const job = { id: 'chat-send-1234', kind: 'chat_send', status: 'queued', profile: 'default', worker: 'remote-2' };
    const fetcher = vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(String(input), 'https://ui.test');
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true,
        profiles: ['default', 'archive'],
        actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
      }), { status: 200 });
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', url: 'http://local', enabled: true },
        { name: 'remote-2', url: 'http://remote-2', enabled: true },
      ] }), { status: 200 });
      if (url.pathname === '/api/v1/profiles/local') return new Response(JSON.stringify({ profiles: [], runtime_readiness: { workers: [], cells: [] } }), { status: 200 });
      if (url.pathname.endsWith('/workers/remote-2/profiles/local')) return new Response(JSON.stringify({ items: [
        { name: 'default', ready: false },
        { name: 'archive', ready: true },
      ] }), { status: 200 });
      if (url.pathname.endsWith('/workers/local/profiles/local')) return new Response(JSON.stringify({ items: [
        { name: 'default', ready: true },
      ] }), { status: 200 });
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({
        path: '/workspace',
        items: [{ name: 'books', path: '/workspace/books', kind: 'directory', files: 2, directories: 1 }],
      }), { status: 200 });
      if (url.pathname.endsWith('/chat-send/jobs')) {
        submission(String(input), init);
        return new Response(JSON.stringify(job), { status: 202 });
      }
      if (url.pathname.endsWith('/jobs/metrics')) return new Response(JSON.stringify({ workers: [] }), { status: 200 });
      if (url.pathname.includes('/jobs?')) return new Response(JSON.stringify({ items: submission.mock.calls.length ? [job] : [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetcher);
    await session.restore();
    render(ChatSendPage);

    await fireEvent.change(await screen.findByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    const archive = await screen.findByRole('checkbox', { name: /archive/ });
    const defaultProfile = screen.getByRole('checkbox', { name: /default/ }) as HTMLInputElement;
    if (defaultProfile.checked) await fireEvent.click(defaultProfile);
    await fireEvent.click(archive);
    await fireEvent.click(defaultProfile);
    expect(screen.getAllByText('Urutan 1').length).toBe(1);
    expect(screen.getAllByText('Urutan 2').length).toBe(1);
    await fireEvent.input(screen.getByRole('textbox', { name: /Chat tujuan/ }), { target: { value: 'https://t.me/c/123456/1' } });
    const booksFolder = await screen.findByRole('checkbox', { name: 'Pilih books' });
    await fireEvent.click(booksFolder);
    expect(screen.getByText('/workspace/books ×')).toBeTruthy();
    const submitButton = screen.getByRole('button', { name: 'Kirim ke Chat' });
    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(submitButton);

    await waitFor(() => expect(submission).toHaveBeenCalledTimes(1));
    const [submittedUrl, submittedInit] = submission.mock.calls[0];
    expect(submittedUrl).toContain('/chat-send/jobs');
    expect(new Headers(submittedInit.headers).get('Idempotency-Key')).toBeTruthy();
    expect(JSON.parse(String(submittedInit.body))).toEqual({
      worker: 'remote-2',
      chat_ref: 'https://t.me/c/123456/1',
      folders: ['/workspace/books'],
      profiles: ['archive', 'default'],
      transfer_mode: 'copy',
      move_confirmed: false,
    });
    expect(await screen.findByText(/Job Kirim ke Chat diterima/)).toBeTruthy();
  }, 15000);

  it('requires confirmation before submitting Move', async () => {
    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(String(input), 'https://ui.test');
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true, profiles: ['default'], actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' },
      }), { status: 200 });
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({ items: [{ name: 'local', url: 'http://local', enabled: true }] }), { status: 200 });
      if (url.pathname === '/api/v1/profiles/local') return new Response(JSON.stringify({ profiles: [], runtime_readiness: { workers: [], cells: [] } }), { status: 200 });
      if (url.pathname.endsWith('/workers/local/profiles/local')) return new Response(JSON.stringify({ items: [{ name: 'default', ready: true }] }), { status: 200 });
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [{ name: 'books', path: '/workspace/books', kind: 'directory' }] }), { status: 200 });
      if (url.pathname.endsWith('/jobs/metrics') || url.pathname.includes('/jobs?')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    await session.restore();
    render(ChatSendPage);
    const defaultProfile = await screen.findByRole('checkbox', { name: /default/ }) as HTMLInputElement;
    if (!defaultProfile.checked) await fireEvent.click(defaultProfile);
    await fireEvent.input(screen.getByRole('textbox', { name: /Chat tujuan/ }), { target: { value: '@target' } });
    const booksFolder = await screen.findByRole('checkbox', { name: 'Pilih books' });
    await fireEvent.click(booksFolder);
    expect(screen.getByText('/workspace/books ×')).toBeTruthy();
    await fireEvent.click(screen.getByRole('radio', { name: /Move/ }));
    const submitButton = screen.getByRole('button', { name: 'Kirim ke Chat' });
    await waitFor(() => expect((submitButton as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(submitButton);
    expect(confirm).toHaveBeenCalledTimes(1);
  }, 15000);
});
