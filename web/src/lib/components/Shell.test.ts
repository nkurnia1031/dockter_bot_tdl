import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';

const mocks = vi.hoisted(() => ({
  session: {
    loading: false,
    current: { authenticated: true, actor: { telegram_user_id: 42, profile: 'default', worker_route: 'local' } },
    profileCatalog: [],
    selectedTargetProfile: 'default',
    restore: vi.fn(),
    chooseTargetProfile: vi.fn(),
    chooseWorker: vi.fn(),
    logout: vi.fn()
  }
}));

vi.mock('$app/state', () => ({ page: { url: { pathname: '/' } } }));
vi.mock('$lib/session.svelte', () => ({ session: mocks.session }));
vi.mock('./Login.svelte', () => ({ default: () => null }));
vi.mock('./RequestIndicator.svelte', () => ({ default: () => null }));

import Shell from './Shell.svelte';

describe('Shell operations layout', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    document.documentElement.removeAttribute('data-theme');
    mocks.session.restore.mockReset();
  });

  afterEach(() => cleanup());

  it('groups all primary destinations into the approved navigation sections', () => {
    render(Shell);

    for (const group of ['Monitor', 'Transfer', 'Pemrosesan', 'Sistem']) {
      expect(screen.getByRole('heading', { name: group })).toBeTruthy();
    }
    for (const destination of [
      'Ringkasan', 'Aktivitas', 'Storage', 'Download', 'AriaNg', 'Kirim ke Chat',
      'Export', 'Quick Mode', 'TTS', 'Dekripsi', 'Utility', 'Backup',
      'Profil / Vault', 'Workers', 'Pengaturan', 'Pengembangan'
    ]) {
      expect(screen.getAllByRole('link').some((link) => link.textContent?.trim() === destination)).toBe(true);
    }
  });

  it('starts in dark mode and lets the operator change the theme', async () => {
    render(Shell);
    await waitFor(() => expect(document.documentElement.classList.contains('dark')).toBe(true));

    await fireEvent.click(screen.getByRole('button', { name: 'Pilih tema' }));
    await fireEvent.click(screen.getByRole('menuitem', { name: 'Terang' }));

    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem('tme3-theme')).toBe('light');
  });

  it('opens the mobile navigation as a dialog and closes it with Escape', async () => {
    render(Shell);

    await fireEvent.click(screen.getByRole('button', { name: 'Buka navigasi' }));
    expect(screen.getByRole('dialog', { name: 'Navigasi mobile' })).toBeTruthy();
    await fireEvent.keyDown(screen.getByRole('dialog', { name: 'Navigasi mobile' }), { key: 'Escape' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Buka navigasi' }).getAttribute('aria-expanded')).toBe('false'));
  });
});
