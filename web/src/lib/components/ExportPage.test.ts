import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ExportPage from './ExportPage.svelte';

describe('ExportPage labels', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

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

  it('keeps queue and completion alerts visible with media totals', async () => {
    let status = 'queued';
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/sources') || url.includes('/labels')) {
        return new Response(JSON.stringify({items:[]}), {status:200});
      }
      if (url.includes('/jobs/export-1')) {
        return new Response(JSON.stringify(status === 'succeeded'
          ? {id:'export-1',status,result:{value:{chat_ref:'@example',exported_count:12,message_count:12,media_count:7,photo_count:4,video_count:3}}}
          : {id:'export-1',status,progress:{message:'Menunggu worker'}}), {status:200});
      }
      if (url.endsWith('/exports') && init?.method === 'POST') {
        return new Response(JSON.stringify({id:'export-1',status:'queued',progress:{message:'Menunggu worker'}}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    await screen.findByText('Export baru');
    const input=screen.getByLabelText('Username atau chat ID');
    await fireEvent.input(input, {target:{value:'example'}});
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(await screen.findByText('Export masuk antrean')).toBeTruthy();
    status='succeeded';
    expect(await screen.findByText('12 pesan · 7 media · 4 foto · 3 video', {}, {timeout:2500})).toBeTruthy();
  });

  it('only sends a manual start ID when overwrite is enabled', async () => {
    const requests:Record<string,unknown>[]=[];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url=String(input);
      if (url.includes('/sources')) return new Response(JSON.stringify({items:[{chat_ref:'example',last_id:40,label:'arsip'}]}), {status:200});
      if (url.includes('/labels')) return new Response(JSON.stringify({items:[]}), {status:200});
      if (url.endsWith('/exports') && init?.method === 'POST') {
        requests.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({id:`export-${requests.length}`,status:'queued'}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    const source=await screen.findByLabelText('Pilih source tersimpan');
    await screen.findByRole('option', {name:/example/});
    await fireEvent.change(source, {target:{value:'example'}});
    const start=screen.getByLabelText('Start message ID') as HTMLInputElement;
    expect(start.disabled).toBe(true);

    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(requests[0]).toMatchObject({chat_ref:'example',use_url_message_id:false});
    expect(requests[0]).not.toHaveProperty('start_id');

    await fireEvent.click(screen.getByRole('switch', {name:/Overwrite Start ID/}));
    expect(start.disabled).toBe(false);
    await fireEvent.input(start, {target:{value:'12'}});
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(requests[1]).toMatchObject({chat_ref:'example',start_id:12,use_url_message_id:true});
  });
});
