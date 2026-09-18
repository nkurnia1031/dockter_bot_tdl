import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ExportPage from './ExportPage.svelte';

describe('ExportPage labels', () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });

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

  it('ignores malformed persisted export notices', async () => {
    sessionStorage.setItem('tme3-export-notices', JSON.stringify(['stale-job']));
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      if (input.includes('/jobs/stale-job')) return new Response(JSON.stringify({items: []}), { status: 200 });
      if (input.includes('/sources') || input.includes('/labels')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    render(ExportPage);
    await screen.findByText('Export baru');
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps queue and completion alerts visible with media totals', async () => {
    let status = 'queued';
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      if (url.includes('/context/verify')) {
        return new Response(JSON.stringify({ verified: true, purpose: 'export', profile: 'default', worker: 'local', worker_health: 'healthy' }), { status: 200 });
      }
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
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    await screen.findByText('Target backend terverifikasi');
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
      if (url.includes('/context/verify')) {
        return new Response(JSON.stringify({ verified: true, purpose: 'export', profile: 'default', worker: 'local', worker_health: 'healthy' }), { status: 200 });
      }
      if (url.includes('/sources')) return new Response(JSON.stringify({items:[{chat_ref:'example',last_id:40,label:'arsip'}]}), {status:200});
      if (url.includes('/labels')) return new Response(JSON.stringify({items:[]}), {status:200});
      if (url.endsWith('/exports') && init?.method === 'POST') {
        requests.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({id:`export-${requests.length}`,status:'succeeded'}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    await screen.findByText('Target backend terverifikasi');
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
    await waitFor(() => expect((screen.getByRole('button', {name:'Mulai export'}) as HTMLButtonElement).disabled).toBe(false), {timeout:1500});
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(requests[1]).toMatchObject({chat_ref:'example',start_id:12,use_url_message_id:true});
  });

  it('releases export after 500ms without waiting for JSON milestone and prevents duplicate clicks', async () => {
    let exportRequests=0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url=String(input);
      if (url.includes('/context/verify')) {
        return new Response(JSON.stringify({ verified: true, purpose: 'export', profile: 'default', worker: 'local', worker_health: 'healthy' }), { status: 200 });
      }
      if (url.includes('/sources') || url.includes('/labels')) return new Response(JSON.stringify({items:[]}), {status:200});
      if (url.endsWith('/exports') && init?.method === 'POST') {
        exportRequests+=1;
        return new Response(JSON.stringify({id:`locked-${exportRequests}`,status:'queued',progress:{message:'Menunggu worker'}}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.input(screen.getByLabelText('Username atau chat ID'), {target:{value:'example'}});
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));

    const lockedButton=await screen.findByRole('button', {name:'Tunggu sebentar...'});
    expect((lockedButton as HTMLButtonElement).disabled).toBe(true);
    const noticeViewport=screen.getByRole('alert').parentElement?.parentElement;
    expect(noticeViewport).not.toBe(document.body);
    expect(screen.getByRole('alert').parentElement?.className).toContain('export-notice-viewport');

    await fireEvent.click(lockedButton);
    expect(exportRequests).toBe(1);
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect((screen.getByRole('button', {name:'Tunggu sebentar...'}) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect((screen.getByRole('button', {name:'Mulai export'}) as HTMLButtonElement).disabled).toBe(false), {timeout:1000});

    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(exportRequests).toBe(2);
    await screen.findByRole('button', {name:'Tunggu sebentar...'});
    await fireEvent.click(screen.getByRole('button', {name:'Reset form'}));
    expect(screen.getByRole('button', {name:'Mulai export'})).toBeTruthy();
  });

  it('re-verifies and sends quick_mode when Quick Mode is enabled', async () => {
    const requests: {url:string; body:Record<string,unknown>}[]=[];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url=String(input);
      if (url.includes('/context/verify')) {
        const body=JSON.parse(String(init?.body || '{}')) as Record<string,unknown>;
        requests.push({url, body});
        return new Response(JSON.stringify({ verified: true, purpose: 'export', profile: 'default', worker: 'local', worker_health: 'healthy', quick_mode: body.quick_mode === true }), { status: 200 });
      }
      if (url.includes('/sources') || url.includes('/labels')) return new Response(JSON.stringify({items:[]}), {status:200});
      if (url.endsWith('/exports') && init?.method === 'POST') {
        requests.push({url, body:JSON.parse(String(init.body))});
        return new Response(JSON.stringify({id:'quick-1',status:'succeeded',result:{value:{quick_mode:true,storage_folder:'ModeCepat/2026',thumbnail_name:'example.png',thumbnail_uploaded_as_photo:true,archive_names:['example.7z.001']}}}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.input(screen.getByLabelText('Username atau chat ID'), {target:{value:'example'}});
    await fireEvent.click(screen.getByRole('switch', {name:/Quick Mode Export/}));
    expect(screen.queryByText('Target backend terverifikasi')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Verifikasi target' }));
    expect(requests[1].body).toMatchObject({purpose:'export', quick_mode:true});
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));
    expect(requests[2].body).toMatchObject({chat_ref:'example',quick_mode:true});
    expect(await screen.findByText(/ModeCepat\/2026/)).toBeTruthy();
    expect(await screen.findByText(/thumbnail sebagai foto/)).toBeTruthy();
  });

  it('applies the same 500ms cooldown to Quick Mode without waiting for JSON milestone', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url=String(input);
      if (url.includes('/context/verify')) {
        const body=JSON.parse(String(init?.body || '{}')) as Record<string,unknown>;
        return new Response(JSON.stringify({ verified:true, purpose:'export', profile:'default', worker:'local', worker_health:'healthy', quick_mode:body.quick_mode === true }), {status:200});
      }
      if (url.includes('/sources') || url.includes('/labels')) return new Response(JSON.stringify({items:[]}), {status:200});
      if (url.endsWith('/exports') && init?.method === 'POST') {
        return new Response(JSON.stringify({id:'quick-queued',status:'queued',progress:{message:'Menunggu worker'}}), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    }));
    render(ExportPage);
    await screen.findByText('Export baru');
    await fireEvent.click(screen.getByRole('button', {name:'Verifikasi target'}));
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.input(screen.getByLabelText('Username atau chat ID'), {target:{value:'example'}});
    await fireEvent.click(screen.getByRole('switch', {name:/Quick Mode Export/}));
    await fireEvent.click(screen.getByRole('button', {name:'Verifikasi target'}));
    await screen.findByText('Target backend terverifikasi');
    await fireEvent.click(screen.getByRole('button', {name:'Mulai export'}));

    const lockedButton=await screen.findByRole('button', {name:'Tunggu sebentar...'});
    expect((lockedButton as HTMLButtonElement).disabled).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect((screen.getByRole('button', {name:'Tunggu sebentar...'}) as HTMLButtonElement).disabled).toBe(true);
    await waitFor(() => expect((screen.getByRole('button', {name:'Mulai export'}) as HTMLButtonElement).disabled).toBe(false), {timeout:1000});
  });
});
