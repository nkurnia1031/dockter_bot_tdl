import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import WorkspaceExplorer from './WorkspaceExplorer.svelte';

describe('WorkspaceExplorer', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('renders workspace paths as folders and navigates using absolute paths', async () => {
    const fetcher = vi.fn(async (input: string) => {
      const path = new URL(input, 'https://ui.test').searchParams.get('path');
      return new Response(JSON.stringify(path === '/workspace/media'
        ? { path, items: [] }
        : { path: '/workspace', items: [{ name: 'media', path: '/workspace/media', kind: 'directory', files: 2, directories: 1 }] }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetcher);
    render(WorkspaceExplorer);
    const media = await screen.findByText('media');
    expect(screen.queryByText('w')).toBeNull();
    await fireEvent.click(media);
    expect(await screen.findByText('/workspace/media')).toBeTruthy();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('path=%2Fworkspace%2Fmedia'))).toBe(true);
  });
});
