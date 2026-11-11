import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Aria2Page from './Aria2Page.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../lib/api', () => ({ api: mocks.api, post: vi.fn(), patch: vi.fn(), put: vi.fn(), remove: vi.fn() }));

const workers = [
  { name: 'local', enabled: true },
  { name: 'remote-1', enabled: true },
  { name: 'remote-disabled', enabled: false }
];
const settings = {
  'max-overall-download-limit': '0', 'max-overall-upload-limit': '0',
  'max-concurrent-downloads': '3', 'max-connection-per-server': '5', split: '5',
  'lowest-speed-limit': '102400', 'max-tries': '0', 'retry-wait': '0', timeout: '60',
  'connect-timeout': '10', 'disk-cache': '67108864'
};

function setupApi() {
  mocks.api.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/workers') return { items: workers };
    if (path === '/utility/tree?path=%2Fworkspace&worker=local') return { path: '/workspace', items: [
      { name: 'aria2', path: '/workspace/aria2', kind: 'directory', directories: 0, files: 0 },
      { name: 'downloads', path: '/workspace/downloads', kind: 'directory', directories: 1, files: 3 }
    ] };
    if (path === '/utility/tree?path=%2Fworkspace&worker=remote-1') return { path: '/workspace', items: [
      { name: 'aria2', path: '/workspace/aria2', kind: 'directory', directories: 0, files: 0 }
    ] };
    if (path.startsWith('/workers/') && path.endsWith('/aria2/health')) {
      const worker = path.split('/')[2];
      return { worker, ready: worker !== 'remote-disabled', reason_code: worker === 'remote-disabled' ? 'WORKER_DISABLED' : '', engine: { ready: worker !== 'remote-disabled', version: '1.36.0' }, hook: { ready: worker !== 'remote-disabled', script_present: true, configured: true, run_count: 1, last_result: 'retry-resumed' } };
    }
    if (path === '/auth/browser/session') return { authenticated: true, actor: { profile: 'default' }, profiles: ['default'] };
    if (path.startsWith('/aria2-rpc-') && init?.method === 'POST') {
      const request = JSON.parse(String(init.body));
      if (request.method === 'aria2.getGlobalOption') return { result: settings };
      if (request.method === 'aria2.changeGlobalOption') return { result: 'OK' };
      if (request.method === 'aria2.getVersion') return { result: { version: '1.36.0' } };
      return { result: 'OK' };
    }
    throw new Error(`Unexpected request ${path}`);
  });
}

describe('Aria2Page', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); setupApi(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

  it('loads the selected worker health and embeds AriaNg through the secret-free gateway route', async () => {
    render(Aria2Page);
    const frame = await screen.findByTitle('aria2 local');
    expect(await screen.findByText('Engine: aria2 1.36.0')).toBeTruthy();
    expect(screen.getByText('Hook low-speed: siap')).toBeTruthy();
    const src = frame.getAttribute('src') || '';
    expect(src).toContain('/api/v1/aria2-ui/local/index.html');
    expect(new URL(src, window.location.origin).hash).toContain('interface=api%2Fv1%2Faria2-rpc-local');
    expect(src.toLowerCase()).not.toContain('secret');
    expect(mocks.api).toHaveBeenCalledWith('/workers/local/aria2/health');
  });

  it('loads and saves transfer settings only through the worker RPC bridge', async () => {
    render(Aria2Page);
    const button = await screen.findByRole('button', { name: 'Pengaturan transfer' });
    expect(screen.queryByRole('dialog', { name: 'Pengaturan transfer' })).toBeNull();
    await fireEvent.click(button);
    expect(await screen.findByRole('dialog', { name: 'Pengaturan transfer' })).toBeTruthy();
    const limit = screen.getByLabelText(/Batas kecepatan unduh/) as HTMLInputElement;
    expect(limit.value).toBe('0');
    await fireEvent.input(limit, { target: { value: '2M' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan pengaturan' }));
    expect(await screen.findByText('Pengaturan tersimpan dan akan dipertahankan setelah worker dimulai ulang.')).toBeTruthy();

    const saveCall = mocks.api.mock.calls.find(([path, init]) => path === '/aria2-rpc-local' && init?.method === 'POST' && JSON.parse(String(init.body)).method === 'aria2.changeGlobalOption');
    expect(saveCall).toBeTruthy();
    const payload = JSON.parse(String(saveCall?.[1]?.body));
    expect(payload.params[0]['max-overall-download-limit']).toBe('2M');
    expect(JSON.stringify(payload).toLowerCase()).not.toContain('rpc-secret');
  });

  it('chooses and stores a Workspace download folder per worker', async () => {
    render(Aria2Page);
    const folderButton = await screen.findByRole('button', { name: 'Pilih folder unduhan, saat ini /workspace/aria2' });
    expect(screen.queryByRole('dialog', { name: 'Folder unduhan' })).toBeNull();
    await fireEvent.click(folderButton);
    expect(await screen.findByRole('dialog', { name: 'Folder unduhan' })).toBeTruthy();
    await fireEvent.click(await screen.findByRole('radio', { name: 'Pilih downloads' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Gunakan folder' }));
    expect(await screen.findByRole('button', { name: 'Pilih folder unduhan, saat ini /workspace/downloads' })).toBeTruthy();
    expect(localStorage.getItem('tme3-aria2-folder:local')).toBe('/workspace/downloads');
    expect(mocks.api).toHaveBeenCalledWith('/utility/tree?path=%2Fworkspace&worker=local');
  });

  it('scopes health and folder selection to the newly selected worker', async () => {
    localStorage.setItem('tme3-aria2-folder:remote-1', '/workspace/custom');
    render(Aria2Page);
    await screen.findByTitle('aria2 local');
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-1' } });
    expect(await screen.findByTitle('aria2 remote-1')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Pilih folder unduhan, saat ini /workspace/custom' })).toBeTruthy();
    expect(mocks.api).toHaveBeenCalledWith('/workers/remote-1/aria2/health');
  });

  it('recovers browser session and refreshes only the AriaNg frame without a page reload', async () => {
    render(Aria2Page);
    const frame = await screen.findByTitle('aria2 local');
    const initialGeneration = frame.getAttribute('data-connection-generation');
    await fireEvent.click(screen.getByRole('button', { name: 'Sambungkan ulang' }));
    expect(await screen.findByText('Koneksi AriaNg diperbarui tanpa memuat ulang halaman.')).toBeTruthy();
    await waitFor(() => expect(screen.getByTitle('aria2 local').getAttribute('data-connection-generation')).not.toBe(initialGeneration));
    expect(mocks.api).toHaveBeenCalledWith('/auth/browser/session');
    expect(mocks.api.mock.calls.some(([path, init]) => path === '/aria2-rpc-local' && JSON.parse(String(init?.body)).method === 'aria2.getVersion')).toBe(true);
  });

  it('shows unhealthy workers without exposing the AriaNg iframe or enabling configuration', async () => {
    render(Aria2Page);
    await screen.findByTitle('aria2 local');
    await fireEvent.change(screen.getByRole('combobox', { name: 'Worker' }), { target: { value: 'remote-disabled' } });
    expect(await screen.findByText('WORKER_DISABLED')).toBeTruthy();
    expect(screen.queryByTitle('aria2 remote-disabled')).toBeNull();
    expect((screen.getByRole('button', { name: 'Pengaturan transfer' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
