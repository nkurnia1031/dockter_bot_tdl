<script lang="ts">
  import CryptoJS from 'crypto-js';
  import { onMount } from 'svelte';
  import { Check, Clipboard, KeyRound, RotateCcw, ShieldCheck, Trash2, Link, RefreshCw, XCircle } from '@lucide/svelte';
  import { api } from '$lib/api';

  const PASSPHRASE = 'root';
  const EXAMPLE = 'a77894319ebfd94509a5db3c280d9aee30d8f20e48773993e3a07eda5632fcf4050a8da670fb4831a28b1f68f6cef20af063b32024485302';
  interface SafelinkFormatter {
    stringify(params: CryptoJS.lib.CipherParams): string;
    parse(value: string): CryptoJS.lib.CipherParams;
  }

  const formatter: SafelinkFormatter = {
    stringify(params) {
      return `${params.salt?.toString() ?? ''}${params.ciphertext.toString()}`;
    },
    parse(value) {
      return CryptoJS.lib.CipherParams.create({
        salt: CryptoJS.enc.Hex.parse(value.substring(0, 16)),
        ciphertext: CryptoJS.enc.Hex.parse(value.substring(16))
      });
    }
  };

  let encrypted = $state('');
  let plaintext = $state('');
  let error = $state('');
  let notice = $state('');
  let copied = $state(false);
  let shortlink = $state('');
  let resolverError = $state('');
  let resolverNotice = $state('');
  let resolverBusy = $state(false);
  let resolverCopied = $state(false);
  let resolverJobs = $state<Record<string, any>[]>([]);
  let selectedResolverJobId = $state('');
  let resolverTimer: number | undefined;
  let resolverRequestActive = $state(false);
  let resolverMounted = false;
  const resolverActiveStatuses = new Set(['queued', 'dispatched', 'running', 'paused', 'cancelling']);

  const selectedResolverJob = $derived(
    resolverJobs.find((job) => String(job.id) === selectedResolverJobId) || resolverJobs[0] || null
  );
  const resolverResult = $derived.by(() => {
    const result = selectedResolverJob?.result?.value ?? selectedResolverJob?.result;
    return typeof result?.destination_url === 'string' ? result.destination_url : '';
  });

  function readEncryptedValue(input: string): { value: string; fromParameter: boolean } {
    const raw = input.trim();
    const links = raw.match(/https?:\/\/[^\s)\]]+/gi) || [];

    for (const link of links) {
      try {
        const url = new URL(link);
        const fragment = url.hash.replace(/^#/, '');
        const fragmentQuery = fragment.includes('?') ? fragment.slice(fragment.indexOf('?') + 1) : fragment;
        const value = url.searchParams.get('o') || new URLSearchParams(fragmentQuery).get('o');
        if (value !== null && value !== undefined) return { value, fromParameter: true };
      } catch {
        // A pasted Markdown link may contain punctuation around the URL; try the next match.
      }
    }

    const parameter = raw.match(/(?:[?&#]|^)o=([^&#\s\])]+)/i);
    if (parameter) {
      let value = parameter[1];
      try { value = decodeURIComponent(value.replace(/\+/g, ' ')); } catch { /* keep the copied value */ }
      return { value, fromParameter: true };
    }
    if (links.length) throw new Error('URL tidak memiliki parameter o.');
    return { value: raw.replace(/\s+/g, ''), fromParameter: false };
  }

  function decrypt() {
    error = '';
    notice = '';
    plaintext = '';
    copied = false;

    let input: { value: string; fromParameter: boolean };
    try {
      input = readEncryptedValue(encrypted);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Tidak dapat membaca input.';
      return;
    }
    const value = input.value.replace(/\s+/g, '');
    if (!value) {
      error = input.fromParameter ? 'Parameter o pada URL kosong.' : 'Masukkan teks terenkripsi atau URL Safelink terlebih dahulu.';
      return;
    }
    if (!/^[\da-f]+$/i.test(value) || value.length < 48 || (value.length - 16) % 32 !== 0) {
      error = input.fromParameter
        ? 'Nilai parameter o bukan hex Safelink yang valid.'
        : 'Format tidak valid. Masukkan hex: 16 karakter salt, diikuti ciphertext AES dalam blok 32 karakter.';
      return;
    }

    try {
      const result = CryptoJS.AES.decrypt(value, PASSPHRASE, { format: formatter });
      const decoded = result.toString(CryptoJS.enc.Utf8);
      if (!decoded) {
        error = 'Hasil dekripsi kosong. Periksa kembali teks dan kunci yang digunakan.';
        return;
      }
      plaintext = decoded;
      notice = input.fromParameter ? 'Parameter o ditemukan dan berhasil didekripsi di browser ini.' : 'Dekripsi selesai di browser ini.';
    } catch {
      error = 'Dekripsi gagal. Periksa teks terenkripsi dan kecocokan kunci.';
    }
  }

  async function copyOutput() {
    if (!plaintext) return;
    try {
      await navigator.clipboard.writeText(plaintext);
      copied = true;
      notice = 'Hasil disalin ke clipboard.';
      window.setTimeout(() => copied = false, 1800);
    } catch {
      error = 'Clipboard tidak dapat diakses. Pilih dan salin hasil secara manual.';
    }
  }

  function fillExample() {
    encrypted = EXAMPLE;
    plaintext = '';
    error = '';
    notice = 'Contoh siap. Tekan Dekripsi untuk memprosesnya.';
  }

  function requestKey() {
    return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function scheduleResolverRefresh() {
    if (!resolverMounted || resolverTimer) return;
    if (!resolverJobs.some((job) => resolverActiveStatuses.has(String(job.status)))) return;
    resolverTimer = window.setTimeout(() => {
      resolverTimer = undefined;
      void loadResolverJobs();
    }, 2500);
  }

  async function loadResolverJobs() {
    if (resolverRequestActive) return;
    resolverRequestActive = true;
    if (resolverTimer) {
      clearTimeout(resolverTimer);
      resolverTimer = undefined;
    }
    try {
      const result = await api<{ items: Record<string, any>[] }>(
        '/jobs?kind=safelink_resolve&scope=current&archived=false&limit=50'
      );
      resolverJobs = result.items || [];
      if (!resolverJobs.some((job) => String(job.id) === selectedResolverJobId)) {
        selectedResolverJobId = String(resolverJobs[0]?.id || '');
      }
      resolverError = '';
    } catch (cause) {
      resolverError = cause instanceof Error ? cause.message : 'Riwayat resolver tidak dapat dimuat.';
    } finally {
      resolverRequestActive = false;
      scheduleResolverRefresh();
    }
  }

  async function resolveShortlink() {
    resolverError = '';
    resolverNotice = '';
    resolverCopied = false;
    if (!shortlink.trim()) {
      resolverError = 'Tempel URL shortlink terlebih dahulu.';
      return;
    }
    resolverBusy = true;
    try {
      const job = await api<Record<string, any>>('/safelink/jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': requestKey() },
        body: JSON.stringify({ url: shortlink.trim() })
      });
      selectedResolverJobId = String(job.id || '');
      resolverNotice = 'Job resolver masuk antrean. Kamu dapat menutup halaman; hasilnya tersimpan di riwayat.';
      await loadResolverJobs();
      selectedResolverJobId = String(job.id || '');
      scheduleResolverRefresh();
    } catch (cause) {
      resolverError = cause instanceof Error ? cause.message : 'Job resolver gagal dikirim.';
    } finally {
      resolverBusy = false;
    }
  }

  async function resolverAction(job: Record<string, any>, action: 'cancel' | 'retry') {
    resolverError = '';
    try {
      await api(`/safelink/jobs/${encodeURIComponent(String(job.id))}/${action}`, {
        method: 'POST',
        headers: { 'Idempotency-Key': requestKey() }
      });
      resolverNotice = action === 'cancel' ? 'Permintaan pembatalan dikirim.' : 'Job masuk antrean ulang.';
      await loadResolverJobs();
      selectedResolverJobId = String(job.id);
    } catch (cause) {
      resolverError = cause instanceof Error ? cause.message : 'Aksi job gagal.';
    }
  }

  async function copyResolverOutput() {
    if (!resolverResult) return;
    try {
      await navigator.clipboard.writeText(resolverResult);
      resolverCopied = true;
      resolverNotice = 'URL tujuan disalin ke clipboard.';
      window.setTimeout(() => resolverCopied = false, 1800);
    } catch {
      resolverError = 'Clipboard tidak dapat diakses. Pilih dan salin hasil secara manual.';
    }
  }

  onMount(() => {
    resolverMounted = true;
    const refresh = () => { void loadResolverJobs(); };
    window.addEventListener('tme3:data-mutated', refresh);
    void loadResolverJobs();
    return () => {
      resolverMounted = false;
      if (resolverTimer) clearTimeout(resolverTimer);
      window.removeEventListener('tme3:data-mutated', refresh);
    };
  });

  function clearAll() {
    encrypted = '';
    plaintext = '';
    error = '';
    notice = '';
    copied = false;
  }
</script>

<svelte:head>
  <title>Dekripsi teks dan resolver shortlink · tme3</title>
  <meta name="description" content="Dekripsi parameter Safelink di browser dan resolve shortlink melalui job worker." />
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">ALAT BROWSER</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Dekripsi teks</h1>
    <p class="muted mt-2 max-w-2xl">Dekripsi teks Safelink dengan format yang kompatibel dengan script CryptoJS.</p>
  </div>
  <div class="page-icon"><KeyRound size={22}/></div>
</header>

<section class="card mt-7 p-4 sm:p-6" aria-labelledby="decrypt-title">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 id="decrypt-title" class="font-extrabold">Teks terenkripsi</h2>
      <p class="muted mt-1 text-sm">Tempel nilai hex langsung atau URL Safelink; jika berupa URL, yang diproses hanya parameter <code>o</code>.</p>
    </div>
    <button class="button secondary" type="button" onclick={fillExample}><RotateCcw size={15}/>Isi contoh</button>
  </div>

  <label class="sr-only" for="encrypted-text">Teks terenkripsi</label>
  <textarea
    id="encrypted-text"
    class="field mt-4 min-h-40 resize-y font-mono text-sm leading-6"
    bind:value={encrypted}
    placeholder="Tempel teks terenkripsi di sini…"
    spellcheck="false"
    autocomplete="off"
    autocapitalize="off"
  ></textarea>

  <div class="mt-4 flex flex-wrap items-center gap-2">
    <button class="button" type="button" onclick={decrypt}><KeyRound size={16}/>Dekripsi</button>
    <button class="button secondary" type="button" onclick={clearAll}><Trash2 size={15}/>Bersihkan</button>
  </div>

  {#if error}<p class="mt-4 rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200" role="alert">{error}</p>{/if}
  {#if notice}<p class="mt-4 flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300" role="status"><Check size={16}/>{notice}</p>{/if}
</section>

<section class="card mt-5 p-4 sm:p-6" aria-labelledby="plaintext-title">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <h2 id="plaintext-title" class="font-extrabold">Hasil dekripsi</h2>
      <p class="muted mt-1 text-sm">Hasil hanya disimpan di halaman ini sampai dibersihkan atau halaman ditutup.</p>
    </div>
    <button class="button secondary" type="button" onclick={copyOutput} disabled={!plaintext}><Clipboard size={15}/>{copied ? 'Tersalin' : 'Salin hasil'}</button>
  </div>

  <label class="sr-only" for="decrypted-text">Hasil dekripsi</label>
  <textarea
    id="decrypted-text"
    class="field mt-4 min-h-48 resize-y font-mono text-sm leading-6"
    bind:value={plaintext}
    placeholder="Hasil dekripsi akan muncul di sini…"
    readonly
    spellcheck="false"
  ></textarea>
</section>

<p class="muted mt-4 flex items-start gap-2 text-xs leading-5"><ShieldCheck size={15} class="mt-0.5 shrink-0"/>Pemrosesan dilakukan sepenuhnya di browser. Teks tidak dikirim ke backend atau worker. Kunci mengikuti script contoh.</p>

<section class="card mt-7 p-4 sm:p-6" aria-labelledby="resolver-title">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div>
      <p class="eyebrow">JOB WORKER</p>
      <h2 id="resolver-title" class="mt-1 font-extrabold">Resolver shortlink</h2>
      <p class="muted mt-1 max-w-2xl text-sm">Ikuti langkah shortlink pndk.to atau go.fakta.id di browser worker. Fitur ini hanya mencari URL tujuan dan tidak mengunduh file.</p>
    </div>
    <button class="button secondary" type="button" onclick={loadResolverJobs} disabled={resolverRequestActive}><RefreshCw size={15} class={resolverRequestActive ? 'animate-spin' : ''}/>Refresh job</button>
  </div>

  <label class="mt-4 block text-sm font-bold" for="shortlink-input">URL shortlink</label>
  <textarea
    id="shortlink-input"
    class="field mt-2 min-h-24 resize-y font-mono text-sm leading-6"
    bind:value={shortlink}
    maxlength="2048"
    placeholder="https://pndk.to/... atau https://go.fakta.id/..."
    spellcheck="false"
    autocomplete="off"
    autocapitalize="off"
  ></textarea>
  <div class="mt-3 flex flex-wrap items-center gap-2">
    <button class="button" type="button" onclick={resolveShortlink} disabled={resolverBusy}><Link size={16} class={resolverBusy ? 'animate-pulse' : ''}/>{resolverBusy ? 'Mengirim…' : 'Resolve'}</button>
    <span class="muted text-xs">Input dibatasi ke domain yang didukung; URL tidak ditampilkan di log job.</span>
  </div>

  {#if resolverError}<p class="mt-4 rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-200" role="alert">{resolverError}</p>{/if}
  {#if resolverNotice}<p class="mt-4 flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300" role="status"><Check size={16}/>{resolverNotice}</p>{/if}

  <div class="mt-6 border-t border-[var(--line)] pt-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div><h3 class="font-extrabold">Hasil URL tujuan</h3><p class="muted mt-1 text-xs">Hasil hanya ditampilkan sebagai teks. Buka sendiri setelah memeriksanya.</p></div>
      <button class="button secondary" type="button" onclick={copyResolverOutput} disabled={!resolverResult}><Clipboard size={15}/>{resolverCopied ? 'Tersalin' : 'Salin URL'}</button>
    </div>
    <label class="sr-only" for="resolver-output">URL tujuan</label>
    <textarea id="resolver-output" class="field mt-3 min-h-24 resize-y font-mono text-sm leading-6" value={resolverResult} readonly placeholder="URL tujuan muncul setelah job selesai." spellcheck="false"></textarea>
  </div>

  <div class="mt-6 border-t border-[var(--line)] pt-5">
    <div class="mb-3 flex items-center justify-between gap-3"><h3 class="font-extrabold">Job resolver</h3><span class="muted text-xs">{resolverJobs.length} job tersimpan</span></div>
    {#if resolverJobs.length}
      <div class="space-y-2">
        {#each resolverJobs as job (job.id)}
          {@const active = resolverActiveStatuses.has(String(job.status))}
          {@const output = typeof (job.result?.value?.destination_url || job.result?.destination_url) === 'string' ? (job.result?.value?.destination_url || job.result?.destination_url) : ''}
          <article class={`rounded-xl border p-3 ${selectedResolverJobId === String(job.id) ? 'border-violet-400 bg-[var(--brand-soft)]/30' : 'border-[var(--line)] bg-[var(--surface-soft)]'}`}>
            <button class="w-full text-left" type="button" onclick={() => selectedResolverJobId = String(job.id)}>
              <span class="flex flex-wrap items-center gap-2"><span class="font-mono text-xs text-slate-500">#{String(job.id).slice(0, 8)}</span><span class={`badge ${job.status}`}>{job.status}</span><span class="muted text-xs">{job.worker}</span></span>
              <span class="mt-2 block text-sm font-semibold">{job.progress?.message || job.error?.message || (output ? 'URL tujuan berhasil ditemukan.' : job.status === 'queued' ? 'Menunggu worker resolver.' : 'Resolver shortlink')}</span>
              {#if active}<span class="muted mt-1 block text-xs">{job.progress?.phase || 'queued'}{job.progress?.updated_at ? ` · ${job.progress.updated_at}` : ''}</span>{/if}
              {#if output}<span class="mt-2 block truncate font-mono text-xs text-emerald-700 dark:text-emerald-300">{output}</span>{/if}
            </button>
            {#if job.error?.message}<p class="mt-2 text-sm text-rose-700 dark:text-rose-300">{job.error.message}</p>{/if}
            <div class="mt-3 flex flex-wrap gap-2">
              {#if active}<button class="button danger" type="button" onclick={() => resolverAction(job, 'cancel')}><XCircle size={14}/>Batalkan</button>{/if}
              {#if ['failed','cancelled'].includes(String(job.status))}<button class="button secondary" type="button" onclick={() => resolverAction(job, 'retry')}><RefreshCw size={14}/>Coba lagi</button>{/if}
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <p class="muted rounded-xl border border-dashed border-[var(--line)] p-5 text-center text-sm">Belum ada job resolver. Setelah dikirim, status dan hasil tersimpan di sini.</p>
    {/if}
  </div>
</section>
