<script lang="ts">
  import { onMount } from 'svelte';
  import { Volume2 } from '@lucide/svelte';
  import JobTable from '$lib/components/JobTable.svelte';
  import { api, post, put } from '$lib/api';
  import { normalizeTdlChatRef } from '$lib/chatRef';

  type TtsWorker = { name: string; queued_jobs: number };

  let title = $state('');
  let text = $state('');
  let workers = $state<TtsWorker[]>([]);
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
  const maxChars = 100_000;

  async function loadWorkers() {
    workersLoading = true;
    try {
      const result = await api<{ items: TtsWorker[] }>('/tts/workers');
      workers = result.items || [];
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Daftar worker TTS gagal dimuat.';
    } finally {
      workersLoading = false;
    }
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
        : 'ID chat tersimpan. Job TTS berikutnya akan dikirim lewat profil TDL aktif.';
    } catch (cause) {
      chatError = cause instanceof Error ? cause.message : 'ID chat gagal disimpan.';
    } finally {
      chatSaving = false;
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
    <p class="muted mt-2 text-xs">Terima ID numeric, username, link publik t.me, dan nomor telepon internasional. Tujuan harus bisa dijangkau sesi TDL pada profile aktif.</p>
  </div>
  <div>
    <h2 class="text-lg font-extrabold">Worker TTS</h2>
    <p class="muted mt-1 text-sm">Worker yang ditampilkan sudah melaporkan helper gTTS dan jalur Tor siap.</p>
    {#if workersLoading}
      <p class="muted mt-3 text-sm">Memeriksa worker...</p>
    {:else if workers.length === 0}
      <p class="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">Belum ada worker TTS yang siap untuk profile aktif. Periksa helper, Tor, dan sesi TDL profile dari halaman Workers.</p>
    {:else}
      <div class="mt-3 flex flex-wrap gap-2">{#each workers as option}<span class="badge">{option.name} · {option.queued_jobs} job</span>{/each}</div>
    {/if}
  </div>
</section>

<section class="card mt-7 p-4 sm:p-6">
  <div class="mb-5">
    <h2 class="text-lg font-extrabold">Buat audio</h2>
    <p class="muted mt-1 text-sm">Teks maksimal 100.000 karakter. Monitor hanya menampilkan judul, jumlah karakter, progress, dan status.</p>
  </div>
  <form class="grid gap-4" onsubmit={submit}>
    {#if workers.length > 0 && !workersLoading}
      <label class="grid gap-1.5 text-sm font-semibold">Worker untuk job ini
        <select class="field" bind:value={worker}>
          <option value="">Otomatis — antrean terpendek</option>
          {#each workers as option}<option value={option.name}>{option.name} · {option.queued_jobs} job dalam antrean</option>{/each}
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
      <button class="button primary" type="submit" disabled={submitting || workersLoading || workers.length === 0 || !title.trim() || !text.trim() || text.length > maxChars}>
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
