import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock('$lib/api', () => ({ api: apiMock, post: vi.fn() }));

import Aria2Page from './+page.svelte';

describe('AriaNg worker readiness', () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === '/workers') return { items: [{ name: 'remote-1', enabled: true }] };
      if (path.startsWith('/utility/tree?')) return {
        path: '/workspace',
        items: [{ name: 'aria2', path: '/workspace/aria2', kind: 'directory', directories: 0, files: 0 }]
      };
      if (path === '/aria2-rpc-remote-1' && init?.method === 'POST') {
        const request = JSON.parse(String(init.body));
        if (request.method === 'aria2.getGlobalOption') return { result: {
          'max-overall-download-limit': '0', 'max-overall-upload-limit': '0',
          'max-concurrent-downloads': '3', 'max-connection-per-server': '5', split: '5',
          'lowest-speed-limit': '102400', 'max-tries': '0', 'retry-wait': '0', timeout: '60',
          'connect-timeout': '10', 'disk-cache': '67108864'
        } };
        if (request.method === 'aria2.changeGlobalOption') return { result: 'OK' };
      }
      if (path === '/workers/remote-1/aria2/health') return {
        worker: 'remote-1', ready: true, reason_code: '',
        engine: { ready: true, version: '1.36.0' },
        hook: { ready: true, script_present: true, configured: true, run_count: 1, last_result: 'retry-resumed' }
      };
      throw new Error(`Unexpected request ${path}`);
    });
  });

  it('loads AriaNg only for a ready selected worker and keeps its RPC secret out of the iframe URL', async () => {
    render(Aria2Page);
    await screen.findByText('remote-1');
    const frame = await screen.findByTitle('aria2 remote-1');
    expect(screen.getByText('Engine: aria2 1.36.0')).toBeTruthy();
    expect(screen.getByText('Hook low-speed: siap')).toBeTruthy();
    expect(frame.getAttribute('src')).toContain('/api/v1/aria2-ui/remote-1/index.html');
    expect(frame.getAttribute('src')).toContain('%2Fapi%2Fv1%2Faria2-rpc-remote-1');
    expect(frame.getAttribute('src')).not.toContain('secret');
    expect(apiMock).toHaveBeenCalledWith('/workers/remote-1/aria2/health');
  });

  it('loads and saves only safe transfer settings through the authenticated bridge', async () => {
    render(Aria2Page);
    const downloadLimit = await screen.findByLabelText(/Batas kecepatan unduh/);
    expect((downloadLimit as HTMLInputElement).value).toBe('0');

    await fireEvent.input(downloadLimit, { target: { value: '2M' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan pengaturan' }));

    await screen.findByText('Pengaturan tersimpan dan akan dipertahankan setelah worker dimulai ulang.');
    const saveCall = apiMock.mock.calls.find(([path, init]) =>
      path === '/aria2-rpc-remote-1' && init?.method === 'POST' &&
      JSON.parse(String(init.body)).method === 'aria2.changeGlobalOption'
    );
    expect(saveCall).toBeTruthy();
    const payload = JSON.parse(String(saveCall?.[1]?.body));
    expect(payload.params[0]['max-overall-download-limit']).toBe('2M');
    expect(JSON.stringify(payload)).not.toContain('rpc-secret');
  });
});
