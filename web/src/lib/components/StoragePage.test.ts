import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import StoragePage from './StoragePage.svelte';
import { session } from '../session.svelte';

describe('Storage file manager', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

  it('renders folder tree, opens nested folder, and exposes recycle bin', async () => {
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(String(input), 'https://ui.test');
      if (url.pathname.endsWith('/storage/folders/tree')) {
        return new Response(JSON.stringify({items:[
          {id:1,parent_id:null,name:'Projects',path:'Projects',status:'active',updated_at:'2026-07-26T00:00:00Z'},
          {id:2,parent_id:1,name:'2026',path:'Projects/2026',status:'active',updated_at:'2026-07-26T00:00:00Z'}
        ]}), {status:200});
      }
      if (url.pathname.endsWith('/storage/browser')) {
        const nested=url.searchParams.get('folder_id')==='1';
        return new Response(JSON.stringify({
          current_folder:nested?{id:1,name:'Projects'}:null,
          breadcrumbs:nested?[{id:1,name:'Projects'}]:[],
          folders:nested?[]:[{id:1,parent_id:null,name:'Projects',path:'Projects',status:'active'}],
          items:nested?[{id:9,display_name:'report.pdf',original_name:'report.pdf',file_size:10,status:'active'}]:[],
          total_folders:nested?0:1,total_items:nested?1:0
        }), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    });
    vi.stubGlobal('fetch', fetcher);
    render(StoragePage);

    expect(await screen.findByRole('button', {name:'Projects'})).toBeTruthy();
    expect(screen.getByRole('button', {name:'Recycle Bin'})).toBeTruthy();
    await fireEvent.click(screen.getAllByRole('button', {name:'Projects'})[0]);
    expect(await screen.findByText('report.pdf')).toBeTruthy();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('folder_id=1'))).toBe(true);
  }, 15000);

  it('shows skipped profile reason and TDL command from the verification job', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true, profiles: ['default'], actor: { telegram_user_id: 1, profile: 'default', worker_route: 'local' },
      }), { status: 200 });
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({ items: [{ name: 'local', url: 'http://worker' }] }), { status: 200 });
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({
        current_folder: null, breadcrumbs: [], folders: [], items: [], total_folders: 0, total_items: 0,
      }), { status: 200 });
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.pathname.endsWith('/tdl-access/verification') && method === 'POST') return new Response(JSON.stringify({
        operation_id: 'storage-operation', status: 'queued', phase: 'queued', job_id: 'storage-verify-job',
      }), { status: 202 });
      if (url.pathname.endsWith('/operations/storage-operation')) return new Response(JSON.stringify({
        operation_id: 'storage-operation', status: 'succeeded', phase: 'completed', job_id: 'storage-verify-job',
      }), { status: 200 });
      if (url.pathname.endsWith('/jobs/storage-verify-job')) return new Response(JSON.stringify({
        status: 'succeeded',
        progress: { message: 'Profil default dilewati (TDL_SESSION_DIRECTORY_MISSING); perintah TDL tidak dijalankan.' },
        result: { value: {
          command_template: 'tdl --storage type=bolt,path=<session-database> -n <export-namespace> up -p <temporary-test-file> -c <configured-destination> --caption <temporary-caption-file>',
          summary: { total: 1, tested: 0, ready: 0, failed: 1 },
          profiles: [{ profile: 'default', ready: false, session_status: 'unavailable', command_attempted: false, error_code: 'TDL_SESSION_DIRECTORY_MISSING', error_message: 'Folder sesi export profil ini tidak ditemukan pada worker.' }],
        } },
      }), { status: 200 });
      if (url.pathname.endsWith('/tdl-access/verification')) return new Response(JSON.stringify({
        worker: 'local', ready: false, profiles: [],
      }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    await session.restore();
    render(StoragePage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Verifikasi akses TDL' }));
    await fireEvent.click(await screen.findByRole('button', { name: 'Muat status' }));

    expect(await screen.findByText(/Folder sesi export profil ini tidak ditemukan/)).toBeTruthy();
    expect(screen.getByText(/tdl --storage type=bolt,path=<session-database>/)).toBeTruthy();
    expect(screen.getByText(/Profil default dilewati/)).toBeTruthy();
    expect(screen.getByText(/0 profil dapat mengirim dari 1/)).toBeTruthy();
    expect(screen.getByText(/tidak dijalankan karena sesi/i)).toBeTruthy();
  }, 15000);
});
