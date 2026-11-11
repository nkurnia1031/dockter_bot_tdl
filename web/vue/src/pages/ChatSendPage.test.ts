import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatSendPage from './ChatSendPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), submission: vi.fn() }));
vi.mock('../lib/api', () => ({ api: mocks.api, post: vi.fn() }));
vi.mock('../session', () => ({
  session: {
    workers: [{ name: 'local', enabled: true }, { name: 'remote-2', enabled: true }, { name: 'offline', enabled: false }],
    current: { actor: { profile: 'default', worker_route: 'local' } }
  }
}));

const monitorStub = {
  props: ['kind', 'title', 'retryable'],
  template: '<div data-testid="chat-job-monitor">{{ title }} · {{ kind }} · retry={{ retryable }}</div>'
};

function setupApi() {
  mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/workers/local/profiles/local') return { items: [{ name: 'default', ready: true }, { name: 'alternate', ready: false }] };
    if (path === '/workers/remote-2/profiles/local') return { items: [{ name: 'archive', ready: true }, { name: 'default', ready: true }] };
    if (path.startsWith('/utility/tree?')) {
      const params = new URLSearchParams(path.split('?')[1]);
      return {
        path: params.get('path') || '/workspace',
        items: [
          { name: 'books', path: '/workspace/books', kind: 'directory', files: 2, directories: 1 },
          { name: 'archive', path: '/workspace/archive', kind: 'directory', files: 1, directories: 0 }
        ]
      };
    }
    if (path === '/chat-send/jobs' && init?.method === 'POST') {
      mocks.submission(path, init);
      return { id: 'chat-send-1234', kind: 'chat_send', status: 'queued' };
    }
    throw new Error(`Unexpected API request ${path}`);
  });
}

function renderPage() {
  return render(ChatSendPage, { global: { stubs: { JobMonitor: monitorStub } } });
}

describe('ChatSendPage', () => {
  beforeEach(() => { vi.clearAllMocks(); setupApi(); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

  it('submits the selected worker, profile order, chat reference, and multiple Workspace folders', async () => {
    renderPage();
    await screen.findByRole('checkbox', { name: /default/ });
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-2' } });
    const archiveProfile = await screen.findByRole('checkbox', { name: 'archive' });
    await fireEvent.click(archiveProfile);
    const defaultProfile = await screen.findByRole('checkbox', { name: /default/ });
    if ((defaultProfile as HTMLInputElement).checked) await fireEvent.click(defaultProfile);
    await fireEvent.click(defaultProfile);

    await fireEvent.input(screen.getByLabelText('Chat tujuan'), { target: { value: 'https://t.me/c/123456/1' } });
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih books' }));
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih archive' }));
    expect(screen.getByText('/workspace/books ×')).toBeTruthy();
    expect(screen.getByText('/workspace/archive ×')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: 'Kirim ke Chat' }));
    await waitFor(() => expect(mocks.submission).toHaveBeenCalledTimes(1));
    const [url, init] = mocks.submission.mock.calls[0];
    expect(url).toBe('/chat-send/jobs');
    expect(new Headers(init.headers).get('Idempotency-Key')).toBeTruthy();
    expect(JSON.parse(String(init.body))).toEqual({
      worker: 'remote-2',
      chat_ref: 'https://t.me/c/123456/1',
      folders: ['/workspace/books', '/workspace/archive'],
      profiles: ['archive', 'default'],
      transfer_mode: 'copy',
      move_confirmed: false
    });
    expect(await screen.findByText(/Job Kirim ke Chat diterima/)).toBeTruthy();
    expect(screen.getByTestId('chat-job-monitor').textContent).toContain('chat_send · retry=true');
  });

  it('requires confirmation for Move and sends the explicit confirmation flag', async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);
    renderPage();
    await screen.findByRole('checkbox', { name: /default/ });
    await fireEvent.input(screen.getByLabelText('Chat tujuan'), { target: { value: '@target' } });
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih books' }));
    await fireEvent.click(screen.getByRole('radio', { name: /Move/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Kirim ke Chat' }));

    await waitFor(() => expect(mocks.submission).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(mocks.submission.mock.calls[0][1].body))).toMatchObject({
      chat_ref: '@target', transfer_mode: 'move', move_confirmed: true
    });
  });

  it('keeps the page and shows the API error when a job cannot be submitted', async () => {
    mocks.api.mockImplementation(async (path: string) => {
      if (path.endsWith('/profiles/local')) return { items: [{ name: 'default' }] };
      if (path.startsWith('/utility/tree?')) return { path: '/workspace', items: [{ name: 'books', path: '/workspace/books', kind: 'directory' }] };
      if (path === '/chat-send/jobs') throw new Error('TDL worker tidak tersedia');
      throw new Error(`Unexpected API request ${path}`);
    });
    renderPage();
    await screen.findByRole('checkbox', { name: /default/ });
    await fireEvent.input(screen.getByLabelText('Chat tujuan'), { target: { value: '@target' } });
    await fireEvent.click(await screen.findByRole('checkbox', { name: 'Pilih books' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Kirim ke Chat' }));
    expect((await screen.findByRole('alert')).textContent).toContain('TDL worker tidak tersedia');
  });
});
