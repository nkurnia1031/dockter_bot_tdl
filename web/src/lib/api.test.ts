import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('static API client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses same-origin cookies and forwards CSRF for mutations', async () => {
    document.cookie = 'tme3_csrf=test-csrf; Path=/';
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await api('/jobs/terminate-active', { method: 'POST', body: '{}' });
    expect(fetcher).toHaveBeenCalledWith('/api/v1/jobs/terminate-active', expect.objectContaining({ credentials: 'same-origin' }));
    expect(new Headers(fetcher.mock.calls[0][1].headers).get('x-csrf-token')).toBe('test-csrf');
  });
});
