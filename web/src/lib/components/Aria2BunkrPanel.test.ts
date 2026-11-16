import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));
vi.mock('$lib/api', () => ({ api: apiMock }));

import Aria2BunkrPanel from './Aria2BunkrPanel.svelte';

describe('Aria2 Bunkr panel', () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.endsWith('/aria2/links/tasks')) return { items: [] };
      if (path.endsWith('/aria2/links/preview')) return { items: [
        {
          source_index: 0,
          kind: 'album',
          title: 'iWOMARht',
          error: '',
          files: [
            { item_id: 'file-1', file_name: 'episode-01.mp4', thumbnail_url: 'https://img.test/episode-01.jpg' },
            { item_id: 'file-2', file_name: 'episode-02.mp4', thumbnail_url: 'https://img.test/episode-02.jpg' }
          ]
        }
      ] };
      if (path.endsWith('/aria2/links/enqueue')) return { items: [
        { source_index: 0, file_name: 'episode-01.mp4', gid: '1111111111111111', status: 'queued', route: 'tor' }
      ] };
      throw new Error(`Unexpected request ${path}`);
    });
  });

  it('previews Bunkr albums with large thumbnails and submits selected files through the authenticated API client', async () => {
    render(Aria2BunkrPanel, { worker: 'remote-1', directory: '/workspace/aria2', active: true });

    await fireEvent.input(screen.getByLabelText('Link Bunkr atau URL langsung'), {
      target: { value: 'https://bunkr.cr/a/iWOMARht' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Periksa link' }));

    await screen.findByText('episode-01.mp4');
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    const thumbnail = screen.getByAltText('episode-01.mp4') as HTMLImageElement;
    expect(thumbnail.className).toContain('h-48');
    expect(thumbnail.className).toContain('w-full');

    await fireEvent.click(screen.getByLabelText('Rute unduh'));
    await fireEvent.change(screen.getByLabelText('Rute unduh'), { target: { value: 'tor' } });
    await fireEvent.click(screen.getByRole('checkbox', { name: /episode-02\.mp4/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Masukkan pilihan ke Aria2' }));

    await screen.findByText('1 task masuk antrean.');
    const previewCall = apiMock.mock.calls.find(([path]) => String(path).endsWith('/aria2/links/preview'));
    expect(previewCall?.[0]).toBe('/workers/remote-1/aria2/links/preview');
    const enqueueCall = apiMock.mock.calls.find(([path]) => String(path).endsWith('/aria2/links/enqueue'));
    expect(enqueueCall?.[0]).toBe('/workers/remote-1/aria2/links/enqueue');
    expect(JSON.parse(String(enqueueCall?.[1]?.body))).toEqual({
      sources: ['https://bunkr.cr/a/iWOMARht'],
      selections: { '0': ['file-1'] },
      directory: '/workspace/aria2',
      route: 'tor'
    });
  });

  it('shows automatic URL refresh retry state without manual refresh controls', async () => {
    apiMock.mockImplementation(async (path: string) => {
      if (path.endsWith('/aria2/links/tasks')) return { items: [{
        gid: '2222222222222222', kind: 'bunkr', file_name: 'episode-01.mp4', status: 'refreshing',
        completed_bytes: 5, total_bytes: 100, speed_bytes_per_second: 0, route: 'non',
        refresh_attempts: 2, retry_after_seconds: 9, reason_code: 'BUNKR_URL_REFRESH_RETRYING'
      }] };
      throw new Error(`Unexpected request ${path}`);
    });
    render(Aria2BunkrPanel, { worker: 'remote-1', directory: '/workspace/aria2', active: true });

    await screen.findByText(/Memperbarui URL otomatis/);
    expect(screen.getByText(/percobaan 2/)).toBeTruthy();
    expect(screen.getByText(/9 dtk/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Perbarui link sekarang|Retry manual/i })).toBeNull();
  });

  it('shows a detected expired Bunkr URL as pending automatic refresh without a fake attempt count', async () => {
    apiMock.mockImplementation(async (path: string) => {
      if (path.endsWith('/aria2/links/tasks')) return { items: [{
        gid: '3333333333333333', kind: 'bunkr', file_name: 'episode-01.mp4', status: 'refreshing',
        completed_bytes: 0, total_bytes: 100, speed_bytes_per_second: 0, route: 'non',
        refresh_attempts: 0, retry_after_seconds: 0, reason_code: 'BUNKR_URL_REFRESH_PENDING'
      }] };
      throw new Error(`Unexpected request ${path}`);
    });
    render(Aria2BunkrPanel, { worker: 'remote-1', directory: '/workspace/aria2', active: true });

    await screen.findByText('Memperbarui URL otomatis…');
    expect(screen.queryByText(/percobaan 0/)).toBeNull();
  });

  it('invalidates album selection when the source links change after preview', async () => {
    render(Aria2BunkrPanel, { worker: 'remote-1', directory: '/workspace/aria2', active: true });

    const input = screen.getByLabelText('Link Bunkr atau URL langsung');
    await fireEvent.input(input, { target: { value: 'https://bunkr.cr/a/iWOMARht' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Periksa link' }));
    await screen.findByText('episode-01.mp4');

    await fireEvent.input(input, { target: { value: 'https://bunkr.cr/a/another-album' } });

    expect(screen.queryByText('Pilih file untuk antrean')).toBeNull();
    expect(screen.getByText(/berubah.*periksa ulang/i)).toBeTruthy();
  });
});
