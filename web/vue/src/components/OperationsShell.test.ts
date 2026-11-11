import { mount, flushPromises } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import OperationsShell from './OperationsShell.vue';
import { createAppRouter, navigationGroups } from '../router';
import { session } from '../session';

const matchMediaDescriptor = Object.getOwnPropertyDescriptor(window, 'matchMedia');

describe('OperationsShell', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false }) });
    session.current = { authenticated: true, actor: { telegram_user_id: 17, profile: 'default', worker_route: 'local' }, profiles: ['default'] };
    session.workers = [];
    session.profileCatalog = [
      { name: 'default', workers: ['local'], exclusive_worker: 'local' },
      { name: 'irang', workers: ['remote-1'], exclusive_worker: 'remote-1' }
    ];
    session.selectedTargetProfile = 'default';
  });

  afterEach(() => {
    if (matchMediaDescriptor) Object.defineProperty(window, 'matchMedia', matchMediaDescriptor);
    else delete (window as unknown as { matchMedia?: unknown }).matchMedia;
    document.body.innerHTML = '';
  });

  it('renders grouped navigation and preserves profile and theme preferences', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/');
    await router.isReady();
    const wrapper = mount(OperationsShell, { global: { plugins: [router] } });

    expect(wrapper.findAll('.desktop-sidebar .nav-group-title').map((item) => item.text())).toEqual(['Monitor', 'Transfer', 'Pemrosesan', 'Sistem']);
    expect(wrapper.text()).toContain('TME3Bot');
    expect(navigationGroups.flatMap((group) => group.links)).toHaveLength(16);

    await wrapper.get('select[aria-label="Profil target default"]').setValue('irang');
    expect(session.selectedTargetProfile).toBe('irang');
    await wrapper.get('select[aria-label="Tema"]').setValue('light');
    expect(localStorage.getItem('tme3-theme')).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');

    await wrapper.get('button[aria-label="Buka navigasi"]').trigger('click');
    expect(wrapper.find('.mobile-drawer').exists()).toBe(true);
    wrapper.unmount();
  });

  it('moves focus into the mobile navigation, traps Tab, and closes with Escape', async () => {
    const router = createAppRouter(createMemoryHistory());
    await router.push('/');
    await router.isReady();
    const wrapper = mount(OperationsShell, { attachTo: document.body, global: { plugins: [router] } });
    const trigger = wrapper.get('button[aria-label="Buka navigasi"]');
    (trigger.element as unknown as HTMLElement).focus();
    await trigger.trigger('click');
    await flushPromises();

    const drawer = wrapper.get('.mobile-drawer');
    const close = drawer.get('button[aria-label="Tutup navigasi"]').element as unknown as HTMLElement;
    expect(drawer.attributes('role')).toBe('dialog');
    expect(drawer.attributes('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(close);

    const links = drawer.findAll('a');
    const first = links[0].element as unknown as HTMLElement;
    (links[links.length - 1].element as unknown as HTMLElement).focus();
    await drawer.trigger('keydown', { key: 'Tab' });
    expect(document.activeElement).toBe(first);

    await drawer.trigger('keydown', { key: 'Escape' });
    await flushPromises();
    expect(wrapper.find('.mobile-drawer').exists()).toBe(false);
    expect(document.activeElement).toBe(trigger.element);
    wrapper.unmount();
  });
});
