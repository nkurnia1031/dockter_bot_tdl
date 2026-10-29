import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import StoragePage from './StoragePage.svelte';
import { session } from '../session.svelte';

type TestDialogPrototype = { showModal?: () => void; close?: () => void };

function enableDialogMethods() {
  const prototype = HTMLDialogElement.prototype as unknown as TestDialogPrototype;
  prototype.showModal = function (this: HTMLDialogElement) { this.setAttribute('open', ''); };
  prototype.close = function (this: HTMLDialogElement) { this.removeAttribute('open'); };
}

function stubStorageFile() {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = new URL(String(input), 'https://ui.test');
    if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({
      current_folder: null, breadcrumbs: [], folders: [],
      items: [{id:9,display_name:'report.pdf',original_name:'report.pdf',file_size:10,status:'active'}],
      total_folders: 0, total_items: 1,
    }), {status:200});
    if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}), {status:200});
    return new Response(JSON.stringify({items:[]}), {status:200});
  }));
}

describe('Storage file manager', () => {
  afterEach(() => {
    cleanup();
    const prototype = HTMLDialogElement.prototype as unknown as TestDialogPrototype;
    delete prototype.showModal;
    delete prototype.close;
    vi.unstubAllGlobals();
    localStorage.clear();
  });

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

  it('uses the saved Storage readiness snapshot and does not start a verification message/job', async () => {
    enableDialogMethods();
    const requests: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url: url.pathname, method, body: typeof init?.body==='string'?init.body:undefined });
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true, profiles: ['default'], actor: { telegram_user_id: 1, profile: 'default', worker_route: 'local' },
      }), { status: 200 });
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({ items: [{ name: 'local', url: 'http://worker', enabled: true }] }), { status: 200 });
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles: [{ name: 'default', workers: ['local'] }],
        runtime_readiness: {
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
          cells: [{ worker: 'local', profile: 'default', runtime: 'storage', status: 'ready', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
        },
      }), { status: 200 });
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({
        current_folder: null, breadcrumbs: [], folders: [], items: [], total_folders: 0, total_items: 0,
      }), { status: 200 });
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    await session.restore();
    render(StoragePage);

    expect(await screen.findByText('Storage siap')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /verifikasi akses tdl/i })).toBeNull();
    expect(requests.some(({ url, method }) => url.endsWith('/tdl-access/verification') && method === 'POST')).toBe(false);
    expect(requests.some(({ url, method }) => url.endsWith('/context/verify') && method === 'POST')).toBe(false);

    await fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    expect(await screen.findByRole('heading', { name: 'Upload folder workspace' })).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Pilih' }));
    const submit = screen.getByRole('button', { name: 'Mulai upload' });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(submit);
    expect(requests.some(({ url, method }) => url.endsWith('/storage/uploads') && method === 'POST')).toBe(true);
    const uploadRequest=requests.find(({url,method})=>url.endsWith('/storage/uploads')&&method==='POST');
    const uploadBody=JSON.parse(uploadRequest?.body||'{}');
    expect(uploadBody.provider).toBe('telegram');
    expect(uploadBody.transfer_mode).toBe('copy');
    expect(uploadBody.rclone_upload).toBeUndefined();
    expect(requests.some(({ url, method }) => url.endsWith('/tdl-access/verification') && method === 'POST')).toBe(false);
  }, 15000);

  it('keeps Storage upload gated when the saved readiness snapshot has no ready profile', async () => {
    enableDialogMethods();
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      const url = new URL(String(input), 'https://ui.test');
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated: true, profiles: ['default'], actor: { telegram_user_id: 1, profile: 'default', worker_route: 'local' },
      }), { status: 200 });
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({ items: [{ name: 'local', url: 'http://worker', enabled: true }] }), { status: 200 });
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles: [{ name: 'default', workers: ['local'] }],
        runtime_readiness: {
          checked_at: '2026-10-23T05:00:00Z',
          workers: [{ name: 'local', status: 'success', checked_at: '2026-10-23T05:00:00Z', reason_code: '' }],
          cells: [{ worker: 'local', profile: 'default', runtime: 'storage', status: 'not_ready', checked_at: '2026-10-23T05:00:00Z', reason_code: 'TDL_ACCESS_NOT_VERIFIED' }],
        },
      }), { status: 200 });
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({
        current_folder: null, breadcrumbs: [], folders: [], items: [], total_folders: 0, total_items: 0,
      }), { status: 200 });
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({ path: '/workspace', items: [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));
    await session.restore();
    render(StoragePage);

    expect(await screen.findByText('Storage belum siap')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    expect(await screen.findByRole('heading', { name: 'Upload folder workspace' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Mulai upload' }) as HTMLButtonElement).disabled).toBe(true);
  }, 15000);

  it('closes file details from the close button, backdrop, and Escape', async () => {
    stubStorageFile();
    render(StoragePage);

    const fileButton = await screen.findByRole('button', {name:/^report\.pdf/});
    await fireEvent.click(fileButton);
    let dialog = await screen.findByRole('dialog', {name:'Detail file'});
    const closeButton = screen.getByRole('button', {name:'Tutup detail file'});
    expect(closeButton.parentElement?.className).toContain('sticky');
    expect(closeButton.parentElement?.className).toContain('top-0');
    expect(document.activeElement).toBe(closeButton);

    await fireEvent.click(dialog);
    expect(screen.getByRole('dialog', {name:'Detail file'})).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', {name:'Kirim Telegram'}));
    expect(await screen.findByText('report.pdf dikirim ke Telegram.')).toBeTruthy();
    expect(screen.getByRole('dialog', {name:'Detail file'})).toBeTruthy();
    await fireEvent.click(closeButton);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(fileButton);

    await fireEvent.click(fileButton);
    dialog = await screen.findByRole('dialog', {name:'Detail file'});
    const backdrop = screen.getByRole('button', {name:'Tutup detail file melalui latar'});
    await fireEvent.click(backdrop);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(fileButton);

    await fireEvent.click(fileButton);
    dialog = await screen.findByRole('dialog', {name:'Detail file'});
    await fireEvent.keyDown(dialog, {key:'Escape'});
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(fileButton);
  }, 15000);

  it('keeps keyboard focus inside the Storage detail dialog', async () => {
    stubStorageFile();
    render(StoragePage);

    await fireEvent.click(await screen.findByRole('button', {name:/^report\.pdf/}));
    const dialog = await screen.findByRole('dialog', {name:'Detail file'});
    const closeButton = screen.getByRole('button', {name:'Tutup detail file'});
    await fireEvent.keyDown(closeButton, {key:'Tab', shiftKey:true});

    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(screen.getByRole('button', {name:'Pindahkan ke Trash'}));

    await fireEvent.keyDown(document.activeElement!, {key:'Tab'});
    expect(document.activeElement).toBe(closeButton);
  }, 15000);

  it('browses rclone read-only under the selected worker and configured readiness snapshot', async () => {
    enableDialogMethods();
    const requests: { path:string; method:string; url:URL }[] = [];
    const fetcher = vi.fn(async (input:string, init?:RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method=(init?.method||'GET').toUpperCase();
      requests.push({path:url.pathname,method,url});
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{name:'local',url:'http://worker',enabled:true}]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']}],runtime_readiness:{checked_at:'now',
          workers:[{name:'local',status:'success',checked_at:'now',reason_code:''}],
          cells:[{worker:'local',profile:null,runtime:'rclone_storage',status:'ready',checked_at:'now',reason_code:''}]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/rclone/browser')) {
        const nested=url.searchParams.get('path')==='docs';
        return new Response(JSON.stringify({path:nested?'docs':'',breadcrumbs:nested?['docs']:[],limit:100,offset:0,total:nested?1:1,
          items:nested?[{name:'report.txt',path:'docs/report.txt',is_dir:false,size:12,updated_at:''}]:[{name:'docs',path:'docs',is_dir:true,size:0,updated_at:''}]}),{status:200});
      }
      return new Response(JSON.stringify({items:[]}),{status:200});
    });
    vi.stubGlobal('fetch',fetcher);
    await session.restore();
    render(StoragePage);
    await fireEvent.click(await screen.findByRole('tab',{name:'Rclone'}));
    expect(await screen.findByText('Remote rclone')).toBeTruthy();
    await fireEvent.click(await screen.findByRole('button',{name:'docs'}));
    expect(await screen.findByText('report.txt')).toBeTruthy();
    expect(requests.some(item=>item.path.endsWith('/storage/rclone/browser')&&item.url.searchParams.get('worker')==='local')).toBe(true);
    expect(requests.some(item=>item.path.endsWith('/storage/rclone/browser')&&item.url.searchParams.get('path')==='docs')).toBe(true);
    await fireEvent.click(screen.getByRole('button',{name:'Root'}));
    await fireEvent.click(await screen.findByRole('button',{name:'Pilih tujuan'}));
    await fireEvent.click(screen.getByRole('button',{name:'Upload ke folder ini'}));
    expect(screen.getByText('Tujuan rclone').parentElement?.textContent).toContain('docs');
    const transfer=screen.getByLabelText('Transfer') as HTMLSelectElement;
    expect(transfer.value).toBe('copy');
    await fireEvent.change(transfer,{target:{value:'move'}});
    const moveConfirmation=screen.getByLabelText(/Saya memahami file Workspace akan dihapus/);
    expect((moveConfirmation as HTMLInputElement).checked).toBe(false);
    await fireEvent.click(moveConfirmation);
    expect((moveConfirmation as HTMLInputElement).checked).toBe(true);
    expect(requests.every(item=>item.method==='GET'||item.path.endsWith('/auth/browser/session')||item.path.endsWith('/profiles/local'))).toBe(true);
  },15000);
});
