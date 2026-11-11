import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.vue';
import { session, sessionActions } from './session';

describe('App bootstrap', () => {
  beforeEach(() => {
    session.loading = true;
    vi.spyOn(sessionActions, 'restore').mockResolvedValue();
  });

  it('applies a saved theme before the browser session resolves', () => {
    localStorage.setItem('tme3-theme', 'light');
    const wrapper = mount(App);

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(wrapper.find('.boot-screen').exists()).toBe(true);
    wrapper.unmount();
  });
});
