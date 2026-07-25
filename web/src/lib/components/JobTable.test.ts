import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import JobTable from './JobTable.svelte';

describe('JobTable', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows an accessible empty state and global terminate action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    render(JobTable, { title: 'Daftar aktivitas' });
    expect(await screen.findByText('Belum ada job.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Terminate semua aktif' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Refresh daftar job' })).toBeTruthy();
  });
});
