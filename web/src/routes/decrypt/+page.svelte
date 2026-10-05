<script lang="ts">
  import CryptoJS from 'crypto-js';
  import { Check, Clipboard, KeyRound, RotateCcw, ShieldCheck, Trash2 } from '@lucide/svelte';

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

  function decrypt() {
    error = '';
    notice = '';
    plaintext = '';
    copied = false;

    const value = encrypted.trim().replace(/\s+/g, '');
    if (!value) {
      error = 'Masukkan teks terenkripsi terlebih dahulu.';
      return;
    }
    if (!/^[\da-f]+$/i.test(value) || value.length < 48 || (value.length - 16) % 32 !== 0) {
      error = 'Format tidak valid. Masukkan hex: 16 karakter salt, diikuti ciphertext AES dalam blok 32 karakter.';
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
      notice = 'Dekripsi selesai di browser ini.';
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

  function clearAll() {
    encrypted = '';
    plaintext = '';
    error = '';
    notice = '';
    copied = false;
  }
</script>

<svelte:head>
  <title>Dekripsi teks · tme3</title>
  <meta name="description" content="Dekripsi teks Safelink secara lokal di browser." />
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
      <p class="muted mt-1 text-sm">Tempel nilai hex yang berisi salt dan ciphertext.</p>
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
