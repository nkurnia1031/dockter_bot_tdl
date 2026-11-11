import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
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

  it('hides the shared folder tree but keeps navigation and recursive list summaries', async () => {
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
          folders:nested?[]:[{id:1,parent_id:null,name:'Projects',path:'Projects',status:'active',file_count:2,folder_count:1,size_bytes:30,size_complete:true}],
          items:nested?[{id:9,display_name:'report.pdf',original_name:'report.pdf',file_size:10,status:'active'}]:[],
          total_folders:nested?0:1,total_items:nested?1:0
        }), {status:200});
      }
      return new Response(JSON.stringify({items:[]}), {status:200});
    });
    vi.stubGlobal('fetch', fetcher);
    render(StoragePage);

    expect(await screen.findByRole('button', {name:/Projects/})).toBeTruthy();
    expect(screen.getByRole('button', {name:'Recycle Bin'})).toBeTruthy();
    expect(screen.getByRole('button', {name:'All Files'})).toBeTruthy();
    expect(screen.queryByText('Folder bersama')).toBeNull();
    await fireEvent.click(screen.getByRole('button', {name:'Tampilan daftar'}));
    expect(await screen.findByText('2 file · 1 folder · 30 B')).toBeTruthy();
    await fireEvent.click(screen.getAllByRole('button', {name:/^Projects/})[0]);
    expect((await screen.findAllByText('report.pdf')).length).toBeGreaterThan(0);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('folder_id=1'))).toBe(true);
  }, 15000);

  it('loads one recursive rclone summary per opened folder and refreshes it manually', async () => {
    const summaryCalls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:string) => {
      const url = new URL(String(input), 'https://ui.test');
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true, profiles:['default'], actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{name:'local',url:'http://worker',enabled:true}]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']}], runtime_readiness:{checked_at:'2026-11-01T00:00:00Z',
          workers:[{name:'local',status:'success',checked_at:'now',reason_code:''}],
          cells:[{worker:'local',profile:null,runtime:'rclone_storage',status:'ready',checked_at:'now',reason_code:''}]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/rclone/browser')) {
        const path=url.searchParams.get('path')||'';
        return new Response(JSON.stringify({
          path,breadcrumbs:[],items:path==='Archive'?
            [{name:'Nested',path:'Archive/Nested',is_dir:true,size:0,updated_at:'now'}]:[
              {name:'Archive',path:'Archive',is_dir:true,size:0,updated_at:'now'},
              {name:'Media',path:'Media',is_dir:true,size:0,updated_at:'now'},
            ],total:path==='Archive'?1:2,limit:100,offset:0,
        }),{status:200});
      }
      if (url.pathname.endsWith('/storage/rclone/folder-summaries')) {
        const path=url.searchParams.get('path')||'';
        summaryCalls.push(path);
        return new Response(JSON.stringify({path,summaries:path==='Archive'?
          [{path:'Archive/Nested',file_count:4,folder_count:2,size_bytes:0,size_complete:true}]:[
            {path:'Archive',file_count:2,folder_count:1,size_bytes:3145728,size_complete:false},
            {path:'Media',file_count:1,folder_count:0,size_bytes:2097152,size_complete:true},
          ]}),{status:200});
      }
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);
    await fireEvent.click(await screen.findByRole('tab',{name:'Rclone'}));

    expect(await screen.findByText('2 file · 1 folder · Ukuran tidak lengkap')).toBeTruthy();
    expect(screen.getByText('1 file · 0 folder · 2.0 MB')).toBeTruthy();
    expect(summaryCalls).toEqual(['']);
    await fireEvent.click(screen.getByRole('button',{name:/^Archive/}));
    expect(await screen.findByText('4 file · 2 folder · 0 B')).toBeTruthy();
    expect(summaryCalls).toEqual(['','Archive']);
    await fireEvent.change(screen.getByDisplayValue('Nama'),{target:{value:'size'}});
    await waitFor(()=>expect(screen.getByText('4 file · 2 folder · 0 B')).toBeTruthy());
    expect(summaryCalls).toEqual(['','Archive']);
    await fireEvent.click(screen.getByRole('button',{name:'Refresh rclone'}));
    await waitFor(()=>expect(summaryCalls).toEqual(['','Archive','Archive']));
  },15000);

  it('creates an rclone folder and renames a listed remote entry through the selected worker', async () => {
    enableDialogMethods();
    const mutations: {method:string;body:Record<string,unknown>}[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url=new URL(String(input),'https://ui.test');
      const method=(init?.method||'GET').toUpperCase();
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{name:'local',url:'http://worker',enabled:true}]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']}],
        runtime_readiness:{checked_at:'now',workers:[{name:'local',status:'success',checked_at:'now',reason_code:''}],
          cells:[{worker:'local',profile:null,runtime:'rclone_storage',status:'ready',checked_at:'now',reason_code:''}]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/rclone/browser')) return new Response(JSON.stringify({
        path:'',breadcrumbs:[],items:[{name:'Archive',path:'Archive',is_dir:true,size:0,updated_at:'now'}],total:1,limit:100,offset:0,
      }),{status:200});
      if (url.pathname.endsWith('/storage/rclone/folder-summaries')) return new Response(JSON.stringify({path:'',summaries:[]}),{status:200});
      if (url.pathname.endsWith('/storage/rclone/actions') && method==='POST') {
        const body=JSON.parse(String(init?.body||'{}'));
        mutations.push({method,body});
        return new Response(JSON.stringify({action:body.action,path:(body.path?body.path+'/':'')+body.name}),{status:200});
      }
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);
    await fireEvent.click(await screen.findByRole('tab',{name:'Rclone'}));

    await fireEvent.click(await screen.findByRole('button',{name:'Folder baru'}));
    await fireEvent.input(screen.getByLabelText('Nama folder'),{target:{value:'2026'}});
    await fireEvent.click(screen.getByRole('button',{name:'Buat folder'}));
    await waitFor(()=>expect(mutations).toHaveLength(1));
    expect(mutations[0].body).toMatchObject({worker:'local',action:'create_folder',path:'',name:'2026'});

    await waitFor(()=>expect((screen.getByRole('button',{name:'Rename Archive'}) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(screen.getByRole('button',{name:'Rename Archive'}));
    await fireEvent.input(screen.getByLabelText('Nama file atau folder'),{target:{value:'Archive-old'}});
    await fireEvent.click(screen.getByRole('button',{name:'Simpan rename'}));
    await waitFor(()=>expect(mutations).toHaveLength(2));
    expect(mutations[1].body).toMatchObject({worker:'local',action:'rename',path:'Archive',name:'Archive-old'});
  },15000);

  it('submits a bounded rclone copy job and restores an item from its Trash view', async () => {
    enableDialogMethods();
    const jobs: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url=new URL(String(input),'https://ui.test');
      const method=(init?.method||'GET').toUpperCase();
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
      if (url.pathname.endsWith('/storage/rclone/browser')) return new Response(JSON.stringify({
        path:'',breadcrumbs:[],items:[{name:'report.zip',path:'report.zip',is_dir:false,size:42,updated_at:'now'}],total:1,limit:100,offset:0,trash_supported:true,
      }),{status:200});
      if (url.pathname.endsWith('/storage/rclone/trash')) return new Response(JSON.stringify({
        supported:true,items:[{id:'file-1',ambiguous:false,name:'old.zip',path:'Archive/old.zip',is_dir:false,size:15,updated_at:'now'}],total:1,limit:100,offset:0,
      }),{status:200});
      if (url.pathname.endsWith('/storage/rclone/jobs') && method==='POST') {
        const body=JSON.parse(String(init?.body||'{}')) as Record<string,unknown>;
        jobs.push(body);
        return new Response(JSON.stringify({id:`rclone-job-${jobs.length}`}),{status:200});
      }
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);
    await fireEvent.click(await screen.findByRole('tab',{name:'Rclone'}));
    await fireEvent.click(await screen.findByLabelText('Pilih file report.zip'));
    await fireEvent.click(screen.getByRole('button',{name:'Copy ke sini'}));
    await fireEvent.click(screen.getByRole('button',{name:'Copy'}));
    await waitFor(()=>expect(jobs).toHaveLength(1));
    expect(jobs[0]).toMatchObject({worker:'local',action:'copy',sources:[{path:'report.zip',is_dir:false}],destination_path:'',trashed:false});

    await fireEvent.click(screen.getByRole('tab',{name:'Trash'}));
    expect(await screen.findByText('Archive/old.zip')).toBeTruthy();
    await fireEvent.click(screen.getByLabelText('Pilih file old.zip'));
    await fireEvent.click(screen.getByRole('button',{name:'Pulihkan'}));
    expect(screen.getByText(/Google Drive hanya menyediakan restore seluruh item Trash di folder induk secara rekursif/)).toBeTruthy();
    expect(screen.getByText(/Jika satu item pilihan berbenturan dengan item aktif, seluruh grup folder induk itu dibatalkan/)).toBeTruthy();
    await fireEvent.click(screen.getAllByRole('button',{name:'Pulihkan'}).at(-1)!);
    await waitFor(()=>expect(jobs).toHaveLength(2));
    expect(jobs[1]).toMatchObject({worker:'local',action:'restore',sources:[{path:'Archive/old.zip',is_dir:false,id:'file-1'}],destination_path:'',trashed:true,confirmed:false});
  },15000);

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

    expect(await screen.findByText(/Storage siap/)).toBeTruthy();
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

  it('submits Storage upload when the saved readiness snapshot is not ready', async () => {
    enableDialogMethods();
    const requests: { url: string; method: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      requests.push({ url: url.pathname, method: (init?.method || 'GET').toUpperCase() });
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

    expect(await screen.findByText('Scan: tidak siap')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    expect(await screen.findByRole('heading', { name: 'Upload folder workspace' })).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Pilih' }));
    const submit = screen.getByRole('button', { name: 'Mulai upload' }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    await fireEvent.click(submit);
    await waitFor(() => expect(requests.some(({ url, method }) => url.endsWith('/storage/uploads') && method === 'POST')).toBe(true));
  }, 15000);

  it('submits a Telegram download when the saved Download scan is not ready', async () => {
    enableDialogMethods();
    const requests: {url:string;method:string;body?:string}[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({url:url.pathname,method,body:typeof init?.body==='string'?init.body:undefined});
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{
        name:'local',url:'http://worker',public_url:'https://files.worker.test',enabled:true,
      }]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']}],runtime_readiness:{checked_at:'2026-11-01T00:00:00Z',workers:[
          {name:'local',status:'success',checked_at:'2026-11-01T00:00:00Z',reason_code:''},
        ],cells:[
          {worker:'local',profile:null,runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'local',profile:'default',runtime:'download',status:'not_ready',checked_at:'now',reason_code:'PROFILE_CANARY_DOWNLOAD_FAILED'},
        ]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({
        current_folder:null,breadcrumbs:[],folders:[],
        items:[{id:9,display_name:'report.pdf',original_name:'report.pdf',file_size:10,status:'active'}],
        total_folders:0,total_items:1,
      }),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[
        {name:'downloads',path:'/workspace/downloads',kind:'directory',files:0,directories:0},
      ]}),{status:200});
      if (url.pathname.endsWith('/storage/download-links')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/jobs/metrics')) return new Response(JSON.stringify({}),{status:200});
      if (url.pathname.endsWith('/jobs')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/downloads') && method==='POST') return new Response(JSON.stringify({id:'telegram-download-job'}),{status:200});
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);

    await screen.findByText('report.pdf');
    await fireEvent.click(screen.getByRole('button',{name:'Pilih semua'}));
    await fireEvent.click(screen.getByRole('button',{name:/Download/}));
    expect(await screen.findByRole('heading',{name:'Download ke worker'})).toBeTruthy();
    expect(screen.getByLabelText('Profil yang akan dicoba oleh TDL')).toBeTruthy();
    expect((screen.getByRole('button',{name:'Mulai download'}) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Scan terakhir: belum siap \(PROFILE_CANARY_DOWNLOAD_FAILED\)/)).toBeTruthy();
    await fireEvent.click(await screen.findByRole('radio',{name:'Pilih downloads'}));
    expect((screen.getByRole('button',{name:'Mulai download'}) as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(screen.getByRole('checkbox',{name:/Buat link publik tanpa kedaluwarsa/}));
    await fireEvent.click(screen.getByRole('button',{name:'Mulai download'}));

    await waitFor(() => expect(requests.some((request)=>request.url.endsWith('/storage/downloads')&&request.method==='POST')).toBe(true));
    const submitted=requests.find((request)=>request.url.endsWith('/storage/downloads')&&request.method==='POST');
    expect(JSON.parse(submitted?.body||'{}')).toEqual({
      provider:'telegram',worker:'local',profile:'default',item_ids:[9],folder_ids:[],
      destination_path:'/workspace/downloads',publish_public_links:true,
    });
  },15000);

  it('supports rclone folder downloads and confirmed revoke from the public link list', async () => {
    enableDialogMethods();
    const requests: {url:string;method:string;body?:string}[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({url:url.pathname,method,body:typeof init?.body==='string'?init.body:undefined});
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{
        name:'local',url:'http://worker',public_url:'https://files.worker.test',enabled:true,
      }]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']}],runtime_readiness:{checked_at:'2026-11-01T00:00:00Z',workers:[
          {name:'local',status:'success',checked_at:'2026-11-01T00:00:00Z',reason_code:''},
        ],cells:[
          {worker:'local',profile:null,runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'local',profile:null,runtime:'rclone_storage',status:'ready',checked_at:'now',reason_code:''},
        ]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[
        {name:'downloads',path:'/workspace/downloads',kind:'directory',files:0,directories:0},
      ]}),{status:200});
      if (url.pathname.endsWith('/storage/rclone/browser')) return new Response(JSON.stringify({
        path:'',breadcrumbs:[],items:[{name:'archive',path:'archive',is_dir:true,size:0,updated_at:'now'}],total:1,limit:100,offset:0,
      }),{status:200});
      if (url.pathname.endsWith('/storage/download-links')) return new Response(JSON.stringify({items:[{
        id:'7d844860-0de4-4ef2-9f20-503b43cd9942',worker:'local',relative_path:'archive/old.zip',file_name:'old.zip',provider:'rclone',job_id:'old-job',created_at:'2026-11-01T00:00:00Z',url:'https://files.worker.test/public/download/'+ 'a'.repeat(43),
      }]}),{status:200});
      if (url.pathname.endsWith('/jobs/metrics')) return new Response(JSON.stringify({}),{status:200});
      if (url.pathname.endsWith('/jobs')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/downloads') && method==='POST') return new Response(JSON.stringify({id:'rclone-download-job'}),{status:200});
      if (url.pathname.includes('/storage/download-links/') && method==='POST') return new Response(JSON.stringify({cleanup_status:'deleted'}),{status:200});
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);

    expect(await screen.findByText('old.zip')).toBeTruthy();
    expect(await screen.findByText('archive/old.zip')).toBeTruthy();
    await fireEvent.click(screen.getByRole('tab',{name:'Rclone'}));
    await screen.findByRole('checkbox',{name:'Pilih folder archive'});
    await fireEvent.click(screen.getByRole('checkbox',{name:'Pilih folder archive'}));
    await fireEvent.click(screen.getByRole('button',{name:'Download 1 dipilih'}));
    expect(await screen.findByRole('heading',{name:'Download ke worker'})).toBeTruthy();
    expect(screen.queryByLabelText('Profil dengan lane Download siap')).toBeNull();
    await fireEvent.click(await screen.findByRole('radio',{name:'Pilih downloads'}));
    await fireEvent.click(screen.getByRole('checkbox',{name:/Buat link publik tanpa kedaluwarsa/}));
    await fireEvent.click(screen.getByRole('button',{name:'Mulai download'}));

    await waitFor(() => expect(requests.some((request)=>request.url.endsWith('/storage/downloads')&&request.method==='POST')).toBe(true));
    const submitted=requests.find((request)=>request.url.endsWith('/storage/downloads')&&request.method==='POST');
    expect(JSON.parse(submitted?.body||'{}')).toEqual({
      provider:'rclone',worker:'local',rclone_sources:[{path:'archive',is_dir:true,size:0}],
      destination_path:'/workspace/downloads',publish_public_links:true,
    });

    await fireEvent.click(screen.getAllByRole('button',{name:'Cabut & hapus file'})[0]);
    expect(await screen.findByRole('heading',{name:'Cabut link dan hapus file worker?'})).toBeTruthy();
    await fireEvent.click(screen.getAllByRole('button',{name:'Cabut & hapus file'})[1]);
    await waitFor(() => expect(requests.some((request)=>request.url.includes('/storage/download-links/')&&request.method==='POST')).toBe(true));
    const revoke=requests.find((request)=>request.url.includes('/storage/download-links/')&&request.method==='POST');
    expect(JSON.parse(revoke?.body||'{}')).toEqual({confirmed:true});
  },15000);

  it('keeps public link management available for a disabled worker without enabling downloads', async () => {
    enableDialogMethods();
    const requests: {url:string;method:string;body?:string}[] = [];
    let revoked = false;
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({url:url.pathname + url.search,method,body:typeof init?.body==='string'?init.body:undefined});
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[
        {name:'local',url:'http://worker-local',public_url:'https://local.files.test',enabled:true},
        {name:'remote-1',url:'http://worker-remote',public_url:'https://remote.files.test',enabled:false},
      ]}),{status:200});
      if (url.pathname.endsWith('/profiles/local') || url.pathname.endsWith('/profiles/remote-1')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local','remote-1']}],
        runtime_readiness:{checked_at:'2026-11-01T00:00:00Z',workers:[
          {name:'local',status:'success',checked_at:'now',reason_code:''},
          {name:'remote-1',status:'success',checked_at:'now',reason_code:''},
        ],cells:[
          {worker:'local',profile:null,runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'remote-1',profile:null,runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'remote-1',profile:null,runtime:'rclone_storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'remote-1',profile:'default',runtime:'download',status:'ready',checked_at:'now',reason_code:''},
        ]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/download-links')) return new Response(JSON.stringify({items:
        url.searchParams.get('worker')==='remote-1' && !revoked ? [{
          id:'disabled-worker-link',worker:'remote-1',relative_path:'archive/retained.zip',file_name:'retained.zip',provider:'telegram',job_id:'old-job',created_at:'2026-11-01T00:00:00Z',url:'https://remote.files.test/public/download/token',
        }] : []
      }),{status:200});
      if (url.pathname.includes('/storage/download-links/') && method==='POST') {
        revoked = true;
        return new Response(JSON.stringify({cleanup_status:'deleted'}),{status:200});
      }
      if (url.pathname.endsWith('/jobs/metrics')) return new Response(JSON.stringify({}),{status:200});
      if (url.pathname.endsWith('/jobs')) return new Response(JSON.stringify({items:[]}),{status:200});
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);

    const workerPicker = await screen.findByLabelText('Worker target') as HTMLSelectElement;
    await fireEvent.change(workerPicker, {target:{value:'remote-1'}});
    expect(await screen.findByText('retained.zip')).toBeTruthy();
    expect(await screen.findByText(/Worker nonaktif untuk job baru/)).toBeTruthy();
    expect(requests.some((request)=>request.url==='/api/v1/storage/download-links?worker=remote-1')).toBe(true);
    await fireEvent.click(screen.getByRole('tab',{name:'Rclone'}));
    expect((await screen.findByRole('button',{name:'Upload ke folder ini'}) as HTMLButtonElement).disabled).toBe(true);
    expect(requests.some((request)=>request.url.startsWith('/api/v1/storage/downloads')&&request.method==='POST')).toBe(false);

    await fireEvent.click(screen.getByRole('button',{name:'Cabut & hapus file'}));
    expect(await screen.findByRole('heading',{name:'Cabut link dan hapus file worker?'})).toBeTruthy();
    await fireEvent.click(screen.getAllByRole('button',{name:'Cabut & hapus file'})[1]);
    await waitFor(() => expect(requests.some((request)=>request.url.includes('/storage/download-links/disabled-worker-link/revoke?worker=remote-1')&&request.method==='POST')).toBe(true));
  },15000);

  it('syncs the selected worker using only a profile with ready Storage and Upload evidence', async () => {
    enableDialogMethods();
    const requests: {url:string;method:string;body?:string}[] = [];
    let submitted = false;
    const syncJob = {
      id:'sync-job-1', kind:'storage_sync', profile:'default', worker:'local',
      actor_user_id:1, status:'running', created_at:'2026-11-01T00:00:00Z',
      payload:{channel_id:123}, progress:{phase:'exporting',message:'Mengekspor seluruh riwayat channel Storage',indeterminate:true},
    };
    vi.stubGlobal('fetch', vi.fn(async (input:string, init?:RequestInit) => {
      const url = new URL(String(input), 'https://ui.test');
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({url:url.pathname,method,body:typeof init?.body==='string'?init.body:undefined});
      if (url.pathname.endsWith('/auth/browser/session')) return new Response(JSON.stringify({
        authenticated:true,profiles:['default'],actor:{telegram_user_id:1,profile:'default',worker_route:'local'},
      }),{status:200});
      if (url.pathname.endsWith('/workers')) return new Response(JSON.stringify({items:[{name:'local',url:'http://worker',enabled:true}]}),{status:200});
      if (url.pathname.endsWith('/profiles/local')) return new Response(JSON.stringify({
        profiles:[{name:'default',workers:['local']},{name:'archive',workers:['local']}],
        runtime_readiness:{checked_at:'2026-11-01T00:00:00Z',workers:[{name:'local',status:'success',checked_at:'2026-11-01T00:00:00Z',reason_code:''}],cells:[
          {worker:'local',profile:'default',runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'local',profile:'default',runtime:'upload',status:'ready',checked_at:'now',reason_code:''},
          {worker:'local',profile:'archive',runtime:'storage',status:'ready',checked_at:'now',reason_code:''},
          {worker:'local',profile:'archive',runtime:'upload',status:'not_ready',checked_at:'now',reason_code:'TDL_ACCESS_NOT_VERIFIED'},
        ]},
      }),{status:200});
      if (url.pathname.endsWith('/storage/browser')) return new Response(JSON.stringify({current_folder:null,breadcrumbs:[],folders:[],items:[],total_folders:0,total_items:0}),{status:200});
      if (url.pathname.endsWith('/storage/folders/tree')) return new Response(JSON.stringify({items:[]}),{status:200});
      if (url.pathname.endsWith('/utility/tree')) return new Response(JSON.stringify({path:'/workspace',items:[]}),{status:200});
      if (url.pathname.endsWith('/storage/sync') && method==='POST') {
        submitted = true;
        return new Response(JSON.stringify({id:syncJob.id}),{status:200});
      }
      if (url.pathname.endsWith('/jobs/metrics')) return new Response(JSON.stringify({}),{status:200});
      if (url.pathname.endsWith('/jobs') && url.searchParams.get('kind')==='storage_sync') {
        return new Response(JSON.stringify({items:submitted?[syncJob]:[]}),{status:200});
      }
      if (url.pathname.endsWith('/jobs/sync-job-1/events')) return new Response(JSON.stringify({items:[{sequence:3,event_type:'completed',status:'succeeded',result:{value:{catalog:{recovered:1,updated:2,restored:3,deleted:0,deletion_held:4}}}}]}),{status:200});
      if (url.pathname.endsWith('/jobs/sync-job-1/log-snapshot')) return new Response(JSON.stringify({log:{lines:[]}}),{status:200});
      if (url.pathname.endsWith('/jobs/sync-job-1')) return new Response(JSON.stringify({
        ...syncJob,status:'succeeded',result:{value:{messages_scanned:5,history_complete:false,catalog:{recovered:1,updated:2,restored:3,deleted:0,deletion_held:4}}},
      }),{status:200});
      return new Response(JSON.stringify({items:[]}),{status:200});
    }));
    await session.restore();
    render(StoragePage);

    const profileSelect = await screen.findByLabelText('Profil sumber') as HTMLSelectElement;
    expect([...profileSelect.options].map((option)=>option.value)).toEqual(['default']);
    await fireEvent.click(screen.getByRole('button',{name:'Sinkronkan sekarang'}));
    expect(await screen.findByText('Mengekspor seluruh riwayat channel Storage')).toBeTruthy();

    const syncRequest = requests.find((request)=>request.url.endsWith('/storage/sync')&&request.method==='POST');
    expect(JSON.parse(syncRequest?.body||'{}')).toEqual({worker:'local',profile:'default'});
    window.dispatchEvent(new CustomEvent('tme3:job-finished',{detail:{jobIds:['sync-job-1']}}));
    expect(await screen.findByText(/1 dipulihkan, 2 diperbarui, 3 dari Trash dipulihkan, 0 dihapus, 4 penghapusan ditahan/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button',{name:'Toggle detail progress'}));
    await fireEvent.click(screen.getByRole('button',{name:'Buka Report Lengkap'}));
    expect(await screen.findByText('Detail storage sync')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button',{name:'Raw JSON'}));
    expect(await screen.findByText(/"recovered": 1/)).toBeTruthy();
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
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(fileButton);

    await fireEvent.click(fileButton);
    dialog = await screen.findByRole('dialog', {name:'Detail file'});
    const backdrop = screen.getByRole('button', {name:'Tutup detail file melalui latar'});
    await fireEvent.click(backdrop);
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(fileButton);

    await fireEvent.click(fileButton);
    dialog = await screen.findByRole('dialog', {name:'Detail file'});
    await fireEvent.keyDown(dialog, {key:'Escape'});
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
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
          trash_supported:false,permanent_delete_supported:false,
          items:nested?[{name:'report.txt',path:'docs/report.txt',is_dir:false,size:12,updated_at:''}]:[{name:'docs',path:'docs',is_dir:true,size:0,updated_at:''}]}),{status:200});
      }
      return new Response(JSON.stringify({items:[]}),{status:200});
    });
    vi.stubGlobal('fetch',fetcher);
    await session.restore();
    render(StoragePage);
    await fireEvent.click(await screen.findByRole('tab',{name:'Rclone'}));
    expect(await screen.findByText('Remote rclone')).toBeTruthy();
    await screen.findByRole('button',{name:/^docs/});
    await fireEvent.click(screen.getByRole('checkbox',{name:'Pilih folder docs'}));
    expect((screen.getByRole('button',{name:'Hapus tidak didukung'}) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole('checkbox',{name:'Pilih folder docs'}));
    await fireEvent.click(await screen.findByRole('button',{name:/^docs/}));
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
