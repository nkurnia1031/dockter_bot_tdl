<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, remove } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { CircleAlert, KeyRound, Plus, RefreshCw, ShieldCheck, Upload, UserRoundPlus, X } from '@lucide/svelte';

  type Worker = { name: string; enabled: boolean; online: boolean; secure: boolean };
  type WorkerState = { worker: string; status: string; error?: string };
  type Profile = { name: string; active: boolean; status: string; source?: string; vault: boolean; adoptable?: boolean; operation_id?: string; workers: WorkerState[] };
  type Operation = { id: string; profile: string; status: string; source: string; error?: string; workers: WorkerState[]; login?: { status: string; step?: string; qr_text?: string; error?: string } };

  let profiles = $state<Profile[]>([]);
  let workers = $state<Worker[]>([]);
  let name = $state('');
  let worker = $state('');
  let method = $state<'qr' | 'code'>('qr');
  let phone = $state('');
  let loginInput = $state('');
  let file = $state<File | null>(null);
  let mode = $state<'upload' | 'login'>('upload');
  let operation = $state<Operation | null>(null);
  let adopting = $state('');
  let adoptWorker = $state('');
  let loading = $state(false);
  let saving = $state(false);
  let message = $state('');
  let failure = $state('');

  const availableWorkers = $derived(workers.filter((item) => item.online && item.secure));
  const workerStatus = (value: string) => ({ ready: 'Siap', waiting: 'Menunggu', failed: 'Perlu dicoba ulang' } as Record<string, string>)[value] || value;
  const profileStatus = (value: string) => ({ active: 'Aktif', legacy: 'Belum diadopsi', authenticating: 'Login TDL', validating: 'Memvalidasi sesi', distributing: 'Sinkronisasi', failed: 'Gagal' } as Record<string, string>)[value] || value;

  async function load() {
    loading = true;
    try {
      const result = await api<{ items: Profile[]; workers: Worker[] }>('/profiles/management');
      profiles = result.items || [];
      workers = result.workers || [];
      if (!operation) {
        const pending = profiles.find((item) => item.operation_id && item.status !== 'active' && item.status !== 'legacy');
        if (pending?.operation_id) {
          operation = {
            id: pending.operation_id,
            profile: pending.name,
            status: pending.status,
            source: pending.source || 'upload',
            workers: pending.workers || []
          };
        }
      }
      if (!worker || !availableWorkers.some((item) => item.name === worker)) worker = availableWorkers[0]?.name || '';
      if (operation?.id) await refreshOperation(operation.id, false);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Data profil gagal dimuat.';
    } finally {
      loading = false;
    }
  }

  async function refreshOperation(id: string, showErrors = true) {
    try {
      const previousStatus = operation?.status;
      operation = await api<Operation>(`/profiles/provisionings/${encodeURIComponent(id)}`);
      if (operation.status === 'active' && previousStatus !== 'active') {
        message = `Profil ${operation.profile} siap digunakan.`;
        session.restore();
        name = '';
        phone = '';
        loginInput = '';
        file = null;
      }
    } catch (cause) {
      if (showErrors) failure = cause instanceof Error ? cause.message : 'Status provisioning gagal dimuat.';
    }
  }

  async function submitUpload() {
    if (!file || !name.trim() || !worker || saving) return;
    saving = true; failure = ''; message = '';
    try {
      const query = new URLSearchParams({ name: name.trim(), worker });
      const result = await api<{ id: string; status: string }>(`/profiles/provisionings/upload?${query}`, {
        method: 'POST', body: file, headers: { 'content-type': 'application/zip' }
      });
      operation = { id: result.id, profile: name.trim(), status: result.status, source: 'upload', workers: [] };
      message = 'Sesi valid. Distribusi ke seluruh worker dimulai.';
      await load();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Upload sesi gagal.';
    } finally { saving = false; }
  }

  async function startLogin() {
    if (!name.trim() || !worker || saving || (method === 'code' && !phone.trim())) return;
    saving = true; failure = ''; message = '';
    try {
      const result = await post<{ id: string; status: string }>('/profiles/provisionings/login', {
        name: name.trim(), worker, method, phone: method === 'code' ? phone.trim() : ''
      });
      operation = { id: result.id, profile: name.trim(), status: result.status, source: 'login', workers: [] };
      message = method === 'qr' ? 'QR sedang disiapkan pada worker.' : 'Menunggu kode verifikasi Telegram.';
      await refreshOperation(result.id);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Login TDL gagal dimulai.';
    } finally { saving = false; }
  }

  async function sendLoginInput() {
    if (!operation || !loginInput.trim() || saving) return;
    const step = operation.login?.step || '';
    const field = step === 'password' ? 'password' : 'code';
    saving = true; failure = '';
    try {
      await post(`/profiles/provisionings/${encodeURIComponent(operation.id)}/input`, { field, value: loginInput });
      loginInput = '';
      await refreshOperation(operation.id);
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Input login gagal dikirim.';
    } finally { saving = false; }
  }

  async function cancelOperation() {
    if (!operation || saving) return;
    saving = true; failure = '';
    try {
      await remove(`/profiles/provisionings/${encodeURIComponent(operation.id)}`);
      operation = null; message = 'Provisioning dibatalkan.'; await load();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Provisioning tidak dapat dibatalkan.';
    } finally { saving = false; }
  }

  async function retryOperation(id: string) {
    failure = '';
    try { await post(`/profiles/provisionings/${encodeURIComponent(id)}/retry`); await load(); }
    catch (cause) { failure = cause instanceof Error ? cause.message : 'Retry distribusi gagal.'; }
  }

  async function adoptProfile(profileName: string) {
    if (!adopting || !adoptWorker) return;
    failure = ''; saving = true;
    try {
      const result = await post<{ id: string; status: string }>(`/profiles/${encodeURIComponent(profileName)}/adopt`, { worker: adoptWorker });
      operation = { id: result.id, profile: profileName, status: result.status, source: 'adoption', workers: [] };
      message = `Sesi ${profileName} disalin dari ${adoptWorker} ke semua worker. Profil dijeda sementara sinkronisasi berlangsung.`;
      adopting = ''; adoptWorker = ''; await load();
    } catch (cause) {
      failure = cause instanceof Error ? cause.message : 'Adopsi profil gagal.';
    } finally { saving = false; }
  }

  onMount(() => {
    void load();
  });
</script>

<svelte:head><title>Profil TDL · tme3</title></svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">AKUN TELEGRAM</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Profil TDL</h1><p class="muted mt-2">Tambahkan sesi dari ZIP atau login TDL, lalu distribusikan ke semua worker.</p></div>
  <div class="page-icon"><UserRoundPlus size={23}/></div>
</header>

{#if message}<div class="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">{message}</div>{/if}
{#if failure}<div class="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-100"><CircleAlert size={17} class="mt-0.5 shrink-0"/>{failure}</div>{/if}

<div class="mt-7 grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
  <section class="card p-5 sm:p-6">
    <div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={19}/></div><div><h2 class="font-extrabold">Tambah profil</h2><p class="muted text-sm">Gunakan sesi Telegram yang akan menjadi identitas profil.</p></div></div>
    <div class="mt-5 space-y-4">
      <label class="block text-sm font-bold">Nama profil<input class="field mt-2" bind:value={name} maxlength="48" autocomplete="off" placeholder="contoh: irang"/></label>
      <label class="block text-sm font-bold">Worker untuk menyiapkan sesi<select class="field mt-2" bind:value={worker}><option value="">Pilih worker online</option>{#each availableWorkers as item}<option value={item.name}>{item.name}{item.enabled ? '' : ' · nonaktif untuk job baru'}</option>{/each}</select></label>
      {#if availableWorkers.length === 0}<p class="muted rounded-xl border border-amber-300/40 bg-amber-50 p-3 text-sm dark:bg-amber-950/30">Tidak ada worker online dengan transport aman untuk memvalidasi sesi. Worker disabled tetap dapat dipilih jika sedang online. Worker remote perlu URL HTTPS.</p>{/if}
      <div class="grid grid-cols-2 gap-2 rounded-xl bg-[var(--panel-strong)] p-1"><button class:active={mode === 'upload'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => mode = 'upload'}><Upload size={15} class="mr-1 inline"/>Upload ZIP</button><button class:active={mode === 'login'} class="rounded-lg px-3 py-2 text-sm font-bold" onclick={() => mode = 'login'}><KeyRound size={15} class="mr-1 inline"/>Login TDL</button></div>
      {#if mode === 'upload'}
        <label class="block text-sm font-bold">ZIP berisi folder <code>.tdl/</code><input class="field mt-2" type="file" accept=".zip,application/zip" onchange={(event) => file = (event.currentTarget as HTMLInputElement).files?.[0] || null}/></label>
        <p class="muted text-xs">Maksimum 128 MiB. Sesi akan disalin terpisah ke `root/.tdl` dan `user1/.tdl`.</p>
        <button class="button w-full" onclick={submitUpload} disabled={saving || !file || !name.trim() || !worker}><Upload size={16}/>{saving ? 'Memvalidasi...' : 'Validasi dan sebarkan'}</button>
      {:else}
        <div class="grid grid-cols-2 gap-2"><button class:active={method === 'qr'} class="button secondary justify-center" onclick={() => method = 'qr'}>QR</button><button class:active={method === 'code'} class="button secondary justify-center" onclick={() => method = 'code'}>Nomor dan kode</button></div>
        {#if method === 'code'}<label class="block text-sm font-bold">Nomor telepon Telegram<input class="field mt-2" bind:value={phone} type="tel" autocomplete="tel" placeholder="+62..."/></label>{/if}
        <button class="button w-full" onclick={startLogin} disabled={saving || !name.trim() || !worker || (method === 'code' && !phone.trim())}><KeyRound size={16}/>{saving ? 'Menyiapkan...' : 'Mulai login TDL'}</button>
      {/if}
    </div>
  </section>

  <section class="card p-5 sm:p-6">
    <div class="flex items-center justify-between gap-3"><div><h2 class="font-extrabold">Status profil dan worker</h2><p class="muted mt-1 text-sm">Profil baru aktif setelah semua worker awal mengonfirmasi sesi.</p></div><button class="button secondary !px-3" onclick={load} disabled={loading} aria-label="Muat ulang"><RefreshCw size={16}/></button></div>

    {#if operation}
      <article class="mt-5 rounded-2xl border border-violet-300/50 bg-violet-50/50 p-4 dark:bg-violet-950/20">
        <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="text-xs font-bold uppercase tracking-wider text-violet-600">Provisioning {operation.profile}</p><p class="mt-1 font-bold">{profileStatus(operation.status)}</p></div><div class="flex gap-2"><button class="button secondary !px-3 !py-2" onclick={() => refreshOperation(operation!.id)} disabled={loading || saving} aria-label="Perbarui status provisioning"><RefreshCw size={15}/>Perbarui status</button>{#if operation.source !== 'adoption'}<button class="button secondary !px-3 !py-2" onclick={cancelOperation} disabled={saving || operation.status === 'active'}><X size={15}/>Batalkan</button>{/if}</div></div>
        {#if operation.login && operation.status === 'authenticating'}
          <div class="mt-4 space-y-3">
            {#if operation.login.step === 'qr'}
              <p class="muted text-sm">Pindai QR dengan Telegram pada perangkat yang ingin ditambahkan.</p>
              <pre class="qr-screen overflow-x-auto rounded-xl bg-slate-950 p-4 text-center font-mono text-[9px] leading-[.85] text-white">{operation.login.qr_text || 'Menunggu QR dari worker...'}</pre>
            {:else if operation.login.step === 'code' || operation.login.step === 'password'}
              <label class="block text-sm font-bold">{operation.login.step === 'password' ? 'Password 2FA' : 'Kode Telegram'}<input class="field mt-2" bind:value={loginInput} type={operation.login.step === 'password' ? 'password' : 'text'} autocomplete="one-time-code"/></label>
              <button class="button" onclick={sendLoginInput} disabled={saving || !loginInput.trim()}>{operation.login.step === 'password' ? 'Kirim password 2FA' : 'Kirim kode'}</button>
            {:else}<p class="muted text-sm">Menunggu prompt login dari worker...</p>{/if}
            {#if operation.login.error}<p class="text-sm text-rose-600">{operation.login.error}</p>{/if}
          </div>
        {/if}
        {#if operation.status === 'validating'}<p class="muted mt-3 text-sm">Worker memvalidasi sesi TDL di background. Perbarui status untuk melihat hasilnya.</p>{/if}
        {#if operation.error}<p class="mt-3 text-sm text-rose-600">{operation.error}</p>{/if}
        {#if operation.workers?.length}<div class="mt-4 grid gap-2 sm:grid-cols-2">{#each operation.workers as item}<div class="rounded-lg border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm"><div class="flex items-center justify-between gap-2"><span class="font-semibold">{item.worker}</span><span class="badge">{workerStatus(item.status)}</span></div>{#if item.error}<p class="muted mt-1 text-xs">{item.error}</p>{/if}</div>{/each}</div>{/if}
      </article>
    {/if}

    <div class="mt-5 space-y-3">
      {#each profiles as profile}
        <article class="rounded-2xl border border-[var(--line)] p-4">
          <div class="flex flex-wrap items-center justify-between gap-2"><div class="flex items-center gap-2"><h3 class="font-extrabold">{profile.name}</h3><span class="badge">{profileStatus(profile.status)}</span></div>{#if profile.vault && profile.operation_id && (profile.status !== 'active' || profile.workers.some((item) => item.status !== 'ready'))}<button class="button secondary !px-3 !py-2" onclick={() => retryOperation(profile.operation_id!)}><RefreshCw size={14}/>Retry</button>{/if}</div>
          {#if profile.workers?.length}<div class="mt-3 grid gap-2 sm:grid-cols-2">{#each profile.workers as item}<div class="rounded-lg bg-[var(--panel-strong)] px-3 py-2 text-xs"><div class="flex items-center justify-between gap-2"><span class="font-semibold">{item.worker}</span><span class={item.status === 'ready' ? 'text-emerald-600' : 'text-amber-600'}>{workerStatus(item.status)}</span></div>{#if item.error}<p class="muted mt-1">{item.error}</p>{/if}</div>{/each}</div>{/if}
          {#if profile.status === 'legacy' && profile.adoptable !== false}
            {#if adopting === profile.name}
              <div class="mt-4 rounded-xl border border-amber-300/50 bg-amber-50 p-3 text-sm dark:bg-amber-950/20"><p>Sesi `root` dan `user1` dari worker terpilih akan menggantikan sesi profil ini di semua worker. Profil sementara tidak dapat dipakai sampai seluruh worker selesai.</p><div class="mt-3 flex flex-wrap gap-2"><select class="field min-w-44 flex-1" bind:value={adoptWorker}><option value="">Worker sumber</option>{#each availableWorkers as item}<option value={item.name}>{item.name}</option>{/each}</select><button class="button" onclick={() => adoptProfile(profile.name)} disabled={saving || !adoptWorker}>Adopsi dan sebarkan</button><button class="button secondary" onclick={() => adopting = ''}>Batal</button></div></div>
            {:else}<button class="button secondary mt-3" onclick={() => { adopting = profile.name; adoptWorker = availableWorkers[0]?.name || ''; }} disabled={!availableWorkers.length}>Adopsi ke vault</button>{/if}
          {/if}
        </article>
      {:else}<p class="muted rounded-xl border border-dashed border-[var(--line)] p-5 text-center">{loading ? 'Memuat profil...' : 'Belum ada profil.'}</p>{/each}
    </div>
    <p class="muted mt-4 flex items-start gap-2 text-xs"><ShieldCheck size={15} class="mt-0.5 shrink-0 text-emerald-600"/>Sesi disimpan terenkripsi di backend. ZIP, kode, password, dan isi QR tidak ditampilkan di log.</p>
  </section>
</div>

<style>
  button.active { background: var(--brand-soft); color: var(--brand-strong); }
  .qr-screen { min-height: 12rem; white-space: pre; }
</style>
