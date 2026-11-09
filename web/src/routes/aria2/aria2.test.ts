import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock('$lib/api', () => ({ api: apiMock }));

import Aria2Page from './+page.svelte';

describe('AriaNg worker readiness', () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.mockImplementation(async (path: string) => {
      if (path === '/workers') return { items: [{ name: 'remote-1', enabled: true }] };
      if (path === '/workers/remote-1/aria2/health') return {
        worker: 'remote-1', ready: true, reason_code: '',
        engine: { ready: true, version: '1.36.0' },
        hook: { ready: true, script_present: true, configured: true, run_count: 1, last_result: 'retry-resumed' }
      };
      throw new Error(`Unexpected request ${path}`);
    });
  });

  it('checks one worker only when requested and shows engine plus hook health', async () => {
    render(Aria2Page);
    await screen.findByText('remote-1');
    expect(apiMock).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByRole('button', { name: 'Periksa Aria2 remote-1' }));
    expect(await screen.findByText('Siap · aria2 1.36.0')).toBeTruthy();
    expect(screen.getByText('Hook terakhir: retry-resumed')).toBeTruthy();
    expect(apiMock).toHaveBeenCalledWith('/workers/remote-1/aria2/health');
  });
});
