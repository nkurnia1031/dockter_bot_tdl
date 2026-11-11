import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import RequestIndicator from './RequestIndicator.vue';

describe('RequestIndicator', () => {
  it('keeps a concurrent failure visible when another request succeeds afterward', async () => {
    vi.useFakeTimers();
    const wrapper = mount(RequestIndicator);
    window.dispatchEvent(new CustomEvent('tme3:request-start', { detail: { requestId: 1, pending: 1, mutation: true } }));
    window.dispatchEvent(new CustomEvent('tme3:request-start', { detail: { requestId: 2, pending: 2, mutation: true } }));
    window.dispatchEvent(new CustomEvent('tme3:request-error', { detail: { requestId: 1, pending: 2, mutation: true, message: 'Upload ditolak.' } }));
    window.dispatchEvent(new CustomEvent('tme3:request-end', { detail: { requestId: 1, pending: 1 } }));
    window.dispatchEvent(new CustomEvent('tme3:request-success', { detail: { requestId: 2, pending: 1, mutation: true } }));
    window.dispatchEvent(new CustomEvent('tme3:request-end', { detail: { requestId: 2, pending: 0 } }));
    await vi.advanceTimersByTimeAsync(2200);
    expect(wrapper.text()).toContain('Upload ditolak.');
    await vi.advanceTimersByTimeAsync(250);
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    wrapper.unmount();
    vi.useRealTimers();
  });
});
