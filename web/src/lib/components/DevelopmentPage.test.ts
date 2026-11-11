import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import DevelopmentPage from './DevelopmentPage.svelte';

describe('DevelopmentPage', () => {
  afterEach(() => cleanup());

  it('shows testing guidance, production boundaries, completed work, and new backend ideas', () => {
    render(DevelopmentPage);

    expect(screen.getByRole('heading', { name: 'Pengembangan' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Tes otomatis' })).toBeTruthy();
    expect(screen.getByText(/Tes production hanya dijalankan dari mesin\/workspace ini/)).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Query status job' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Ide berikutnya' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Kerja ulang pada metrik monitor' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Setup koneksi SQLite' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /Buka GitHub Actions/ }).getAttribute('href'))
      .toBe('https://github.com/nkurnia1031/dockter_bot_tdl/actions');
  });
});
