import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import QuickModePage from './QuickModePage.svelte';

describe('QuickModePage', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('verifies Quick Mode, creates a job, and loads the global filter', async () => {
    const requests: { url: string; body?: Record<string, unknown> }[] = [];
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      if (url.includes('/context/verify')) {
        const body = JSON.parse(String(init?.body || '{}')) as Record<string, unknown>;
        requests.push({ url, body });
        return new Response(JSON.stringify({ verified: true, purpose: 'export', profile: 'default', worker: 'local', quick_mode: body.quick_mode === true }), { status: 200 });
      }
      if (url.includes('/sources') || url.includes('/labels')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.includes('/jobs') && init?.method !== 'POST') return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/exports') && init?.method === 'POST') {
        requests.push({ url, body: JSON.parse(String(init.body)) });
        return new Response(JSON.stringify({ id: 'quick-manager-1', status: 'queued' }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(QuickModePage);
    await screen.findByRole('button', { name: 'Tambah Quick Mode' });
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.input(screen.getByLabelText('Username atau chat ID'), { target: { value: 'example' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Tambah Quick Mode' }));

    expect(requests.find((item) => item.url.includes('/context/verify'))?.body).toMatchObject({ purpose: 'export', quick_mode: true });
    expect(requests.find((item) => item.url.endsWith('/exports'))?.body).toMatchObject({ chat_ref: 'example', quick_mode: true });
    await waitFor(() => expect(calls.some((item) => item.includes('/jobs?limit=200&scope=global&kind=export&quick_mode=true'))).toBe(true));
  });

  it('hides physical staging actions while its backend job is active', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = String(input);
      if (url.includes('/sources') || url.includes('/labels')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.includes('/jobs?limit=200&scope=global&kind=export&quick_mode=true')) {
        return new Response(JSON.stringify({ items: [{
          id: 'active-stage-job-1234',
          kind: 'export',
          status: 'running',
          profile: 'default',
          worker: 'local',
          payload: { quick_mode: true, quick_retry: { stage_job_id: 'stage-active' } }
        }] }), { status: 200 });
      }
      if (url.includes('/quick-mode/staging')) {
        return new Response(JSON.stringify({ items: [{
          stage_job_id: 'stage-active',
          folder_name: 'batch',
          worker: 'local',
          profile: 'default',
          phase: 'thumbnailing',
          json_present: true,
          expected_media_count: 1,
          actual_media_count: 1,
          thumbnail_present: false,
          archive_parts: 0,
          tdl_export_present: true,
          tdl_download_present: true,
          staging_path: '/workspace/quickmode/stage-active'
        }] }), { status: 200 });
      }
      if (url.includes('/jobs?')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(QuickModePage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Refresh scan' }));
    expect(await screen.findByText('Sedang processing (#active-s)')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Thumbnail' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Upload' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Compress' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Resume Download' })).toBeNull();
  });
});
