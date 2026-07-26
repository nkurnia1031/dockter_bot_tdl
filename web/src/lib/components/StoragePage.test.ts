import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import StoragePage from './StoragePage.svelte';

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
  });
});
