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

  it('emits global request lifecycle events for visible feedback', async () => {
    const events: string[] = [];
    const record = (event: Event) => events.push(event.type);
    window.addEventListener('tme3:request-start', record);
    window.addEventListener('tme3:request-success', record);
    window.addEventListener('tme3:request-end', record);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);

    await api('/jobs', { method: 'POST', body: '{}' });

    expect(events).toEqual(['tme3:request-start', 'tme3:request-success', 'tme3:request-end']);
    window.removeEventListener('tme3:request-start', record);
    window.removeEventListener('tme3:request-success', record);
    window.removeEventListener('tme3:request-end', record);
  });
});
