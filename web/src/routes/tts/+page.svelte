<script lang="ts">
  import { onMount } from 'svelte';
  import { RefreshCw, Volume2 } from '@lucide/svelte';
  import JobTable from '$lib/components/JobTable.svelte';
  import { api, post, put } from '$lib/api';
  import { normalizeTdlChatRef } from '$lib/chatRef';

  type Helper = { slot: number; status: string; bootstrap_percent?: number | null };
  type TtsWorker = {
    name: string;
    enabled: boolean;
    ready: boolean;
    queued_jobs: number;
    reason_code: string;
    helpers: Helper[];
    verified_profiles?: string[];
    profile_sync_ready?: boolean;
    profile_session_ready?: boolean;
  };
  type AccessOperation = { operation_id: string; status: string; phase: string; job_id?: string | null };
  type AccessProfile = { profile: string; ready: boolean; error_code?: string | null; error_message?: string | null; session_status?: string; command_attempted?: boolean };
  type AccessJob = { progress?: { message?: string | null }; result?: { value?: { profiles?: AccessProfile[]; command_template?: string; summary?: { total: number; tested: number; ready: number; failed: number } } } };

  let title = $state('');
  let text = $state('');
  let workers = $state<TtsWorker[]>([]);
  let workersRefreshing = $state(false);
  let worker = $state('');
  let workersLoading = $state(true);
  let chatConfigured = $state(false);
  let chatDraft = $state('');
  let chatSaving = $state(false);
  let chatMessage = $state('');
  let chatError = $state('');
  let submitting = $state(false);
  let error = $state('');
  let notice = $state('');
  let accessOperation = $state<(AccessOperation & { worker: string }) | null>(null);
  let accessProfiles = $state<AccessProfile[]>([]);
  let accessLoading = $state(false);
  let accessError = $state('');
  let accessProgress = $state('');
  let accessCommand = $state('');
  let accessSummary = $state<{ total: number; tested: number; ready: number; failed: number } | null>(null);
  const maxChars = 100_000;
  const readyWorkers = $derived(workers.filter((item) => item.ready));
  const workerReason = (code: string) => ({
    ready: 'Siap menerima job',
    worker_disabled: 'Dinonaktifkan untuk job baru',
    worker_unavailable: 'Worker tidak dapat dihubungi',
    worker_update_required: 'Perlu update worker',
    helpers_not_ready: 'Helper gTTS atau Tor belum siap',
    tdl_access_unverified: 'Belum ada profil yang terverifikasi ke chat tujuan',
    tts_capability_missing: 'Capability TTS belum dilaporkan',
    capability_unavailable: 'Capability worker belum dapat diperiksa',
  } as Record<string, string>)[code] || code;

  async function loadWorkers() {
    workersLoading = true;
    try {
      const result = await api<{ items: TtsWorker[] }>('/tts/workers');
      workers = result.items || [];
      if (worker && !workers.some((item) => item.name === worker && item.ready)) worker = '';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Daftar worker TTS gagal dimuat.';
    } finally {
      workersLoading = false;
      workersRefreshing = false;
    }
  }

  async function refreshWorkers() {
    if (workersRefreshing) return;
    workersRefreshing = true;
    await loadWorkers();
  }

  async function loadChatStatus() {
    try {
      const result = await api<{ telegram_tts_chat_configured: boolean }>('/runtime/secrets');
      chatConfigured = result.telegram_tts_chat_configured;
    } catch (cause) {
      chatError = cause instanceof Error ? cause.message : 'Status chat tujuan gagal dimuat.';
    }
  }

  async function saveChatId(clear = false) {
    chatMessage = '';
    chatError = '';
    const chatId = normalizeTdlChatRef(chatDraft);
    if (!clear && !chatId) {
      chatError = 'Masukkan ID numeric, @username, username, link publik t.me, atau nomor telepon internasional.';
      return;
    }
    chatSaving = true;
    try {
      const result = await put<{ telegram_tts_chat_configured: boolean }>(
        '/runtime/secrets',
        { telegram_tts_chat_id: clear ? '' : (chatId || '') }
      );
      chatConfigured = result.telegram_tts_chat_configured;
      chatDraft = '';
      chatMessage = clear
        ? 'ID chat dihapus. Job TTS berikutnya tidak akan dikirim sampai tujuan baru diatur.'
        : 'ID chat tersimpan. Verifikasi akses kirim untuk worker yang akan dipakai.';
      accessProfiles = [];
      void loadWorkers();
    } catch (cause) {
      chatError = cause instanceof Error ? cause.message : 'ID chat gagal disimpan.';
    } finally {
      chatSaving = false;
    }
  }

  function idempotencyKey() {
    return globalThis.crypto?.randomUUID?.() || `tdl-access-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  async function verifyTdlAccess(workerName: string) {
    accessError = '';
    accessProfiles = [];
    accessProgress = '';
    accessCommand = '';
    accessSummary = null;
    accessLoading = true;
    try {
      accessOperation = {
        ...(await api<AccessOperation>('/tdl-access/verification', {
          method: 'POST',
          headers: { 'Idempotency-Key': idempotencyKey() },
          body: JSON.stringify({ purpose: 'tts', worker: workerName }),
        })),
        worker: workerName,
      };
      localStorage.setItem('tts-tdl-access-operation', JSON.stringify(accessOperation));
    } catch (cause) {
      accessError = cause instanceof Error ? cause.message : 'Verifikasi akses TDL gagal dimulai.';
    } finally {
      accessLoading = false;
    }
  }

  async function refreshTdlAccess() {
    if (!accessOperation) return;
    accessError = '';
    accessLoading = true;
    try {
      let hasOperationResult = false;
      const operation = await api<AccessOperation>(`/operations/${accessOperation.operation_id}`);
      accessOperation = { ...operation, worker: accessOperation.worker };
      localStorage.setItem('tts-tdl-access-operation', JSON.stringify(accessOperation));
      if (operation.job_id) {
        const job = await api<AccessJob>(`/jobs/${operation.job_id}`);
        accessProgress = job.progress?.message || '';
        const result = job.result?.value;
        if (result) {
          hasOperationResult = true;
          accessProfiles = result.profiles || [];
          accessCommand = result.command_template || '';
          accessSummary = result.summary || null;
        }
      }
      const current = await api<{ profiles: AccessProfile[] }>(
        `/tdl-access/verification?purpose=tts&worker=${encodeURIComponent(accessOperation.worker)}`
      );
      if (!hasOperationResult && current.profiles) accessProfiles = current.profiles;
      await loadWorkers();
    } catch (cause) {
      accessError = cause instanceof Error ? cause.message : 'Status verifikasi akses TDL gagal dimuat.';
    } finally {
      accessLoading = false;
    }
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    notice = '';
    if (!title.trim() || !text.trim()) {
      error = 'Judul dan teks wajib diisi.';
      return;
    }
    submitting = true;
    try {
      const payload: { title: string; text: string; worker?: string } = {
        title: title.trim(),
        text: text.trim(),
      };
      if (worker) payload.worker = worker;
      await post('/tts/jobs', payload);
      notice = 'Job TTS masuk antrean.';
      text = '';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Job TTS gagal dibuat.';
    } finally {
      submitting = false;
    }
  }

  onMount(() => {
    try {
      const saved = localStorage.getItem('tts-tdl-access-operation');
      if (saved) accessOperation = JSON.parse(saved) as AccessOperation & { worker: string };
    } catch { localStorage.removeItem('tts-tdl-access-operation'); }
    void Promise.all([loadWorkers(), loadChatStatus()]);
  });
</script>

<svelte:head>
  <title>TTS Novel · tme3</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">TEXT TO SPEECH</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">TTS Novel</h1>
    <p class="muted mt-2 max-w-2xl">Ubah teks menjadi audio. Pilih worker TTS tertentu atau biarkan sistem memilih antrean terpendek.</p>
  </div>
  <div class="grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Volume2 size={23}/></div>
</header>

<section class="card mt-6 grid gap-5 p-4 sm:p-6 lg:grid-cols-[1fr_1.15fr]">
  <div>
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="text-lg font-extrabold">Chat tujuan MP3</h2>
      <span class="badge" class:succeeded={chatConfigured}>{chatConfigured ? 'ID tersimpan' : 'Belum diatur'}</span>
    </div>
    <p class="muted mt-1 text-sm">ID chat hanya untuk pengiriman TTS. Nilai tersimpan tidak ditampilkan kembali.</p>
    <div class="mt-4 flex flex-wrap gap-2">
      <label class="min-w-56 flex-1 text-sm font-semibold">ID chat Telegram
        <input class="field mt-1.5" bind:value={chatDraft} autocomplete="off" placeholder="-100123456789 · @iyear · https://t.me/iyear" />
      </label>
      <button class="button self-end" onclick={() => saveChatId()} disabled={chatSaving || !chatDraft.trim()}>{chatSaving ? 'Menyimpan...' : 'Simpan ID chat'}</button>
      {#if chatConfigured}<button class="button secondary self-end" onclick={() => saveChatId(true)} disabled={chatSaving}>Hapus</button>{/if}
    </div>
    {#if chatError}<p role="alert" class="mt-2 text-sm text-rose-600">{chatError}</p>{/if}
    {#if chatMessage}<p role="status" class="mt-2 text-sm text-emerald-700 dark:text-emerald-300">{chatMessage}</p>{/if}
    <p class="muted mt-2 text-xs">Terima ID numeric, username, link publik t.me, dan nomor telepon internasional. Job dapat memakai profil lokal mana pun yang sudah lolos verifikasi akses kirim.</p>
  </div>
  <div>
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-lg font-extrabold">Worker TTS</h2>
      <button class="button secondary !px-3 !py-2" onclick={refreshWorkers} disabled={workersLoading || workersRefreshing}>
        <RefreshCw size={15}/>{workersRefreshing ? 'Memeriksa...' : 'Periksa ulang'}
      </button>
    </div>
    <p class="muted mt-1 text-sm">Helper/Tor dan akses profil ke chat tujuan diperiksa terpisah. Sinkronisasi vault hanya informasi diagnosis.</p>
    {#if workersLoading}
      <p class="muted mt-3 text-sm">Memeriksa worker...</p>
    {:else}
      {#if workers.length === 0}<p class="muted mt-3 text-sm">Belum ada worker terdaftar.</p>{/if}
      {#if workers.length > 0 && readyWorkers.length === 0}<p class="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">Belum ada worker dengan helper siap dan profil pengirim yang terverifikasi. Jalankan verifikasi akses pada worker yang akan dipakai.</p>{/if}
      <div class="mt-3 space-y-2">
        {#each workers as option}
          <div class="rounded-xl border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-sm">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-bold">{option.name}</span>
              <span class={option.ready ? 'text-emerald-600' : 'text-amber-600'}>{workerReason(option.reason_code)}</span>
            </div>
            <p class="muted mt-1 text-xs">Helper/Tor: {option.helpers?.length ? option.helpers.map((helper) => `H${helper.slot}: ${helper.status}`).join(' · ') : 'belum diperiksa'} · Profil pengirim: {option.verified_profiles?.length ? option.verified_profiles.join(', ') : 'belum terverifikasi'} · Sync vault: {option.profile_sync_ready ? 'siap' : 'tertunda (tidak menghalangi job)'}</p>
            <button class="button secondary mt-2 !px-3 !py-2 text-xs" onclick={() => verifyTdlAccess(option.name)} disabled={accessLoading || !chatConfigured}>{accessLoading && accessOperation?.worker === option.name ? 'Memulai verifikasi...' : 'Verifikasi akses kirim'}</button>
          </div>
        {/each}
      </div>
      <a class="muted mt-2 inline-block text-xs underline" href="/api/v1/diagnostics/tts/logs?limit=100" target="_blank" rel="noreferrer">Buka log diagnosis JSON</a>
    {/if}
    {#if accessOperation}
      <div class="mt-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3 text-sm">
        <div class="flex flex-wrap items-center justify-between gap-2"><b>Verifikasi {accessOperation.worker}</b><button class="button secondary !px-3 !py-2 text-xs" onclick={refreshTdlAccess} disabled={accessLoading}><RefreshCw size={14}/>{accessLoading ? 'Memuat...' : 'Muat status'}</button></div>
        <p class="muted mt-1 text-xs">Operation {accessOperation.status} · tahap {accessOperation.phase}. Pemeriksaan mengirim satu pesan penanda per profil; pesan tersebut tidak dihapus otomatis.</p>
        {#if accessProgress}<p role="status" class="mt-2 text-sm">{accessProgress}</p>{/if}
        {#if accessSummary}<p class="muted mt-2 text-xs">{accessSummary.ready} profil dapat mengirim dari {accessSummary.total} · {accessSummary.tested} perintah TDL dijalankan · {accessSummary.failed} gagal atau dilewati.</p>{/if}
        {#if accessCommand}<details class="mt-2 text-xs"><summary class="cursor-pointer font-semibold">Lihat bentuk perintah TDL</summary><code class="mt-2 block overflow-x-auto rounded-lg bg-[var(--surface-soft)] p-2">{accessCommand}</code><span class="muted mt-1 block">Tujuan chat, path sesi, dan nama file sementara disamarkan.</span></details>{/if}
        {#if accessProfiles.length}<ul class="mt-2 space-y-2 text-xs">{#each accessProfiles as item}<li class="rounded-lg border border-[var(--line)] p-2"><div><b>{item.profile}</b> · {item.ready ? 'dapat mengirim' : `gagal (${item.error_code || 'VERIFICATION_FAILED'})`}</div>{#if !item.ready && item.error_message}<p class="mt-1 text-rose-700 dark:text-rose-300">{item.error_message}</p>{/if}{#if item.command_attempted === false}<span class="muted block">Perintah TDL tidak dijalankan karena sesi tidak tersedia.</span>{:else if item.command_attempted === true}<span class="muted block">Perintah TDL dijalankan dengan sesi export profil ini.</span>{/if}</li>{/each}</ul>{:else}<p class="muted mt-2 text-xs">Belum ada hasil pemeriksaan profil. Tekan Muat status untuk mengambil hasil terbaru.</p>{/if}
        {#if accessError}<p role="alert" class="mt-2 text-xs text-rose-600">{accessError}</p>{/if}
      </div>
    {/if}
  </div>
</section>

<section class="card mt-7 p-4 sm:p-6">
  <div class="mb-5">
    <h2 class="text-lg font-extrabold">Buat audio</h2>
    <p class="muted mt-1 text-sm">Teks maksimal 100.000 karakter. Monitor hanya menampilkan judul, jumlah karakter, progress, dan status.</p>
  </div>
  <form class="grid gap-4" onsubmit={submit}>
    {#if readyWorkers.length > 0 && !workersLoading}
      <label class="grid gap-1.5 text-sm font-semibold">Worker untuk job ini
        <select class="field" bind:value={worker}>
          <option value="">Otomatis — antrean terpendek</option>
          {#each readyWorkers as option}<option value={option.name}>{option.name} · {option.queued_jobs} job dalam antrean</option>{/each}
        </select>
      </label>
    {/if}
    <label class="grid gap-1.5 text-sm font-semibold">
      Judul audio
      <input class="field" bind:value={title} maxlength="200" autocomplete="off" placeholder="Contoh: Bab 1 — Awal Perjalanan" required />
    </label>
    <label class="grid gap-1.5 text-sm font-semibold">
      Teks
      <textarea class="field min-h-64 resize-y leading-6" bind:value={text} maxlength={maxChars} placeholder="Tempel teks novel di sini..." required></textarea>
      <span class="muted text-right text-xs">{text.length.toLocaleString('id-ID')} / {maxChars.toLocaleString('id-ID')} karakter</span>
    </label>
    {#if error}<p role="alert" class="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}
    {#if notice}<p role="status" class="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>{/if}
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="muted text-xs">Pause berlaku setelah batch aktif selesai. Resume melanjutkan dari checkpoint.</p>
      <button class="button primary" type="submit" disabled={submitting || workersLoading || readyWorkers.length === 0 || !title.trim() || !text.trim() || text.length > maxChars}>
        <Volume2 size={16}/>{submitting ? 'Mengirim...' : 'Buat job TTS'}
      </button>
    </div>
  </form>
</section>

<JobTable kind="tts" title="Antrean dan riwayat TTS" retryable={true} />

<style>
  .field { width: 100%; border: 1px solid var(--line); border-radius: .8rem; background: var(--panel-strong); padding: .75rem .85rem; color: var(--ink); outline: none; }
  .field:focus { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 16%, transparent); }
</style>
