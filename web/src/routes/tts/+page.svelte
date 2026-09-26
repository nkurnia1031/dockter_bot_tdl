<script lang="ts">
  import { Volume2 } from '@lucide/svelte';
  import JobTable from '$lib/components/JobTable.svelte';
  import { post } from '$lib/api';

  let title = $state('');
  let text = $state('');
  let submitting = $state(false);
  let error = $state('');
  let notice = $state('');
  const maxChars = 100_000;

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
      await post('/tts/jobs', { title: title.trim(), text: text.trim() });
      notice = 'Job TTS masuk antrean.';
      text = '';
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Job TTS gagal dibuat.';
    } finally {
      submitting = false;
    }
  }
</script>

<svelte:head>
  <title>TTS Novel · tme3</title>
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">TEXT TO SPEECH</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">TTS Novel</h1>
    <p class="muted mt-2 max-w-2xl">Ubah teks menjadi audio. Job diproses oleh worker TTS yang siap, lalu dikirim ke chat Telegram tujuan.</p>
  </div>
  <div class="grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Volume2 size={23}/></div>
</header>

<section class="card mt-7 p-4 sm:p-6">
  <div class="mb-5">
    <h2 class="text-lg font-extrabold">Buat audio</h2>
    <p class="muted mt-1 text-sm">Teks maksimal 100.000 karakter. Monitor hanya menampilkan judul, jumlah karakter, progress, dan status.</p>
  </div>
  <form class="grid gap-4" onsubmit={submit}>
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
      <button class="button primary" type="submit" disabled={submitting || !title.trim() || !text.trim() || text.length > maxChars}>
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
