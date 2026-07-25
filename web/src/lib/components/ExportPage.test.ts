import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import ExportPage from './ExportPage.svelte';

describe('ExportPage labels', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('renders label DTO text instead of object coercion', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      if (input.includes('/sources')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (input.includes('/labels')) return new Response(JSON.stringify({ items: [{ label: '1cans', updated_at: '2026-07-25T00:00:00Z' }] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    render(ExportPage);
    expect(await screen.findByRole('button', { name: '1cans' })).toBeTruthy();
    expect(screen.queryByText('[object Object]')).toBeNull();
  });
});
