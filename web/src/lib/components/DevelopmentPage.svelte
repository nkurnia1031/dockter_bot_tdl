<script lang="ts">
  import {
    ArrowUpRight, Check, CircleAlert, Clock3, Code2, Database, Gauge,
    GitBranch, ListChecks, ShieldCheck
  } from '@lucide/svelte';

  const backendCandidates = [
    {
      title: 'Query status job',
      evidence: 'Monitor aktif refresh tiap 2,5 detik. Empat status saat ini menghasilkan empat operasi list dan empat count.',
      suggestion: 'Satukan filter status dan pagination global di SQLite; kandidat ini paling konkret untuk diukur lebih dulu.',
      priority: 'Utama'
    },
    {
      title: 'Metrik monitor',
      evidence: 'Setiap refresh menghitung ulang job aktif dan job 24 jam terakhir, termasuk parse payload dan progress.',
      suggestion: 'Ukur durasi serta jumlah row sebelum memilih ringkasan inkremental atau pengurangan frekuensi.',
      priority: 'Ukur dulu'
    },
    {
      title: 'Sequence event saat dispatch',
      evidence: 'Dispatch membaca seluruh event job hanya untuk menemukan sequence tertinggi.',
      suggestion: 'Baca sequence terbaru langsung dari SQLite dan pastikan retry tetap monoton.',
      priority: 'Terukur'
    },
    {
      title: 'Scan Profil',
      evidence: 'Koordinasi probe, canary, dan penyimpanan snapshot masih banyak berada di route worker.',
      suggestion: 'Kumpulkan alur scan supaya aturan readiness dan tes fake worker/store lebih terlokalisasi.',
      priority: 'Struktur'
    }
  ];
</script>

<svelte:head>
  <title>Pengembangan · tme3</title>
  <meta name="description" content="Catatan internal tentang pengujian, keamanan production, dan arah optimasi tme3." />
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">CATATAN INTERNAL · SNAPSHOT 26 OKTOBER 2026</p>
    <h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Pengembangan</h1>
    <p class="muted mt-2 max-w-3xl">Aplikasi sudah stabil. Halaman ini merangkum keputusan penting dan pekerjaan berikutnya untuk tahap deployment awal; isinya catatan, bukan status realtime.</p>
  </div>
  <span class="inline-flex items-center gap-2 rounded-full border border-violet-200 bg-violet-50 px-3 py-2 text-sm font-bold text-violet-800 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200">
    <Code2 size={16}/> Fokus: kualitas rilis
  </span>
</header>

<section class="mt-6 rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-white p-5 dark:border-indigo-900 dark:from-indigo-950/70 dark:to-[var(--panel)] sm:p-6" aria-labelledby="focus-title">
  <div class="flex items-start gap-4">
    <div class="grid size-11 shrink-0 place-items-center rounded-xl bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200"><Gauge size={21}/></div>
    <div>
      <p class="eyebrow">SARAN SAYA</p>
      <h2 id="focus-title" class="mt-1 text-lg font-extrabold">Ukur sebelum mengoptimalkan</h2>
      <p class="muted mt-1 max-w-3xl text-sm leading-6">Mulai dari query monitor job karena jalurnya berulang dan terlihat jelas di source. Ambil baseline waktu respons serta jumlah operasi database, lalu bandingkan setelah perbaikan. Kandidat di bawah belum menjadi perubahan kode.</p>
    </div>
  </div>
</section>

<div class="mt-5 grid gap-4 xl:grid-cols-3">
  <section class="card p-5" aria-labelledby="tests-title">
    <div class="flex items-center gap-3">
      <div class="grid size-10 place-items-center rounded-xl bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"><ListChecks size={19}/></div>
      <h2 id="tests-title" class="font-extrabold">Tes otomatis</h2>
    </div>
    <ul class="mt-4 space-y-3 text-sm leading-6">
      <li class="flex gap-2"><Check class="mt-1 shrink-0 text-emerald-600" size={16}/><span><b>Backend:</b> compile, unit, dan integration tests Python.</span></li>
      <li class="flex gap-2"><Check class="mt-1 shrink-0 text-emerald-600" size={16}/><span><b>Web:</b> Svelte check, Vitest, dan build static.</span></li>
      <li class="flex gap-2"><Check class="mt-1 shrink-0 text-emerald-600" size={16}/><span><b>Browser E2E:</b> trusted-device flow di Linux dan Windows.</span></li>
    </ul>
    <a class="mt-4 inline-flex items-center gap-1 text-sm font-bold text-violet-700 underline dark:text-violet-300" href="https://github.com/nkurnia1031/dockter_bot_tdl/actions" target="_blank" rel="noopener noreferrer">Buka GitHub Actions <ArrowUpRight size={15}/></a>
    <p class="muted mt-3 text-xs">Runner standar gratis untuk repo publik. Batas artifact dan cache tetap berlaku; tes tidak perlu menyimpan artifact.</p>
  </section>

  <section class="card p-5" aria-labelledby="production-title">
    <div class="flex items-center gap-3">
      <div class="grid size-10 place-items-center rounded-xl bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"><ShieldCheck size={19}/></div>
      <h2 id="production-title" class="font-extrabold">Batas tes production</h2>
    </div>
    <p class="muted mt-4 text-sm leading-6">Tes production hanya dijalankan dari mesin/workspace ini melalui tooling lokal dan dengan izin eksplisit. GitHub Actions memakai fixture, data sementara, serta server lokal/terisolasi.</p>
    <div class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-100">
      <b class="flex items-center gap-2"><CircleAlert size={16}/>Production tidak masuk CI</b>
      <p class="mt-1">Jangan masukkan URL, credential, sesi browser, atau cookie production ke workflow.</p>
    </div>
  </section>

  <section class="card p-5" aria-labelledby="branch-title">
    <div class="flex items-center gap-3">
      <div class="grid size-10 place-items-center rounded-xl bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300"><GitBranch size={19}/></div>
      <h2 id="branch-title" class="font-extrabold">Status aturan branch</h2>
    </div>
    <p class="muted mt-4 text-sm leading-6">Pada pemeriksaan 26 Oktober 2026, branch <code>main</code> belum memiliki required status checks. CI dapat melaporkan kegagalan, tetapi belum menghalangi merge atau push langsung.</p>
    <p class="mt-3 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-3 text-xs leading-5">Required checks akan mengubah alur kerja menjadi PR sebelum merge. Catat keputusan ini sebelum mengaktifkannya.</p>
  </section>
</div>

<section class="card mt-5 p-5 sm:p-6" aria-labelledby="backend-title">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <p class="eyebrow">LAPORAN SOURCE · BELUM BENCHMARK</p>
      <h2 id="backend-title" class="mt-1 text-xl font-extrabold">Kandidat optimasi backend</h2>
    </div>
    <span class="muted inline-flex items-center gap-1 text-xs"><Clock3 size={14}/>Ditinjau 26 Okt 2026</span>
  </div>

  <div class="mt-4 divide-y divide-[var(--line)]">
    {#each backendCandidates as candidate, index}
      <article class="grid gap-2 py-4 first:pt-1 last:pb-1 md:grid-cols-[2rem_1fr_auto] md:items-start md:gap-4">
        <span class="grid size-7 place-items-center rounded-lg bg-[var(--surface-soft)] text-xs font-black text-[var(--muted)]">0{index + 1}</span>
        <div>
          <h3 class="font-bold">{candidate.title}</h3>
          <p class="muted mt-1 text-sm leading-6">{candidate.evidence}</p>
          <p class="mt-1 text-sm leading-6"><span class="font-semibold">Arah:</span> {candidate.suggestion}</p>
        </div>
        <span class="w-fit rounded-full border border-[var(--line)] px-2.5 py-1 text-xs font-semibold text-[var(--muted)]">{candidate.priority}</span>
      </article>
    {/each}
  </div>

  <div class="mt-5 grid gap-3 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4 sm:grid-cols-[auto_1fr] sm:items-center">
    <Database class="text-violet-600 dark:text-violet-300" size={20}/>
    <p class="muted text-sm leading-6">Angka di sini berasal dari bentuk kode yang dibaca, bukan hasil ukur production. Bandingkan durasi dan jumlah row di data uji yang representatif sebelum memilih cache atau perubahan perilaku.</p>
  </div>
</section>
