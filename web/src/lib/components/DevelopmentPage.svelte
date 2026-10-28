<script lang="ts">
  import {
    ArrowUpRight, Check, CircleAlert, Clock3, Code2, Database, Gauge,
    GitBranch, ListChecks, ShieldCheck
  } from '@lucide/svelte';

  const completedOptimizations = [
    {
      title: 'Query status job',
      detail: 'Query multi-status kini memakai satu operasi list dan satu count dengan pagination global serta urutan stabil.',
      commit: 'be43f9a'
    },
    {
      title: 'Metrik batas Quick Mode',
      detail: 'Pembacaan batas dan counter Quick Mode digabung dari tiga SELECT menjadi satu, dengan hasil yang sama.',
      commit: '523f39c'
    },
    {
      title: 'Sequence event saat dispatch',
      detail: 'Dispatch mengambil sequence terakhir dari SQLite tanpa memuat seluruh riwayat event job.',
      commit: '594d66d'
    },
    {
      title: 'Scan Profil',
      detail: 'Backend memakai diagnosis TDL dari canary sebagai sumber fingerprint, menghilangkan probe diagnosis kedua, dan tetap merahasiakan fingerprint dari respons publik.',
      commit: 'd65b9ff'
    }
  ];

  const nextCandidates = [
    {
      title: 'Kerja ulang pada metrik monitor',
      evidence: 'Monitor aktif refresh tiap 2,5 detik. `monitor_metrics()` masih membaca payload/progress job aktif dan job 24 jam terakhir, mengurai JSON, lalu mengagregasi di Python.',
      suggestion: 'Ukur durasi query, jumlah row, dan biaya parse di GitHub Actions dengan volume fixture bertingkat. Pilih ringkasan inkremental atau pembacaan lebih sempit hanya jika metrik menunjukkan biaya yang berarti.',
      source: 'JobTable.svelte · SqliteJobRepository.monitor_metrics()',
      priority: 'Prioritas berikutnya'
    },
    {
      title: 'Setup koneksi SQLite',
      evidence: '`SqliteJobRepository._db()` membuka koneksi per operasi dan `_connect()` menjalankan `PRAGMA journal_mode=WAL` pada setiap koneksi.',
      suggestion: 'Bandingkan biaya koneksi dan PRAGMA pada beban baca/tulis bersamaan. Jika signifikan, pindahkan konfigurasi WAL ke inisialisasi database; pertahankan foreign keys dan batas transaksi per koneksi.',
      source: 'tme3bot/infrastructure/job_store.py · _db() / _connect()',
      priority: 'Ukur dulu'
    }
  ];
</script>

<svelte:head>
  <title>Pengembangan · tme3</title>
  <meta name="description" content="Catatan internal tentang pengujian, keamanan production, dan arah optimasi tme3." />
</svelte:head>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div>
    <p class="eyebrow">CATATAN INTERNAL · SNAPSHOT 28 OKTOBER 2026</p>
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
      <h2 id="focus-title" class="mt-1 text-lg font-extrabold">Prioritas berikutnya: ukur metrik monitor</h2>
      <p class="muted mt-1 max-w-3xl text-sm leading-6">Empat optimasi backend terbaru sudah selesai. Metrik monitor masih mengurai data job setiap refresh 2,5 detik; ukur dulu dengan fixture bertingkat di GitHub Actions sebelum memilih perubahan berikutnya.</p>
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
      <p class="eyebrow">PEMBARUAN 28 OKTOBER 2026 · SOURCE + CI</p>
      <h2 id="backend-title" class="mt-1 text-xl font-extrabold">Optimasi backend</h2>
    </div>
    <span class="muted inline-flex items-center gap-1 text-xs"><Clock3 size={14}/>4 perubahan selesai</span>
  </div>

  <h3 class="mt-5 text-sm font-extrabold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Selesai</h3>
  <div class="mt-4 divide-y divide-[var(--line)]">
    {#each completedOptimizations as item, index}
      <article class="grid gap-2 py-4 first:pt-1 last:pb-1 md:grid-cols-[2rem_1fr_auto] md:items-start md:gap-4">
        <span class="grid size-7 place-items-center rounded-lg bg-[var(--surface-soft)] text-xs font-black text-[var(--muted)]">0{index + 1}</span>
        <div>
          <h4 class="font-bold">{item.title}</h4>
          <p class="muted mt-1 text-sm leading-6">{item.detail}</p>
        </div>
        <a class="w-fit rounded-full border border-emerald-200 px-2.5 py-1 text-xs font-semibold text-emerald-700 underline dark:border-emerald-900 dark:text-emerald-300" href={`https://github.com/nkurnia1031/dockter_bot_tdl/commit/${item.commit}`} target="_blank" rel="noopener noreferrer">{item.commit}</a>
      </article>
    {/each}
  </div>

  <h3 class="mt-6 text-sm font-extrabold uppercase tracking-wide text-violet-700 dark:text-violet-300">Ide berikutnya</h3>
  <div class="mt-2 divide-y divide-[var(--line)]">
    {#each nextCandidates as candidate, index}
      <article class="grid gap-2 py-4 first:pt-2 last:pb-1 md:grid-cols-[2rem_1fr_auto] md:items-start md:gap-4">
        <span class="grid size-7 place-items-center rounded-lg bg-[var(--surface-soft)] text-xs font-black text-[var(--muted)]">0{index + 1}</span>
        <div>
          <h4 class="font-bold">{candidate.title}</h4>
          <p class="muted mt-1 text-sm leading-6">{candidate.evidence}</p>
          <p class="mt-1 text-sm leading-6"><span class="font-semibold">Arah:</span> {candidate.suggestion}</p>
          <p class="muted mt-1 font-mono text-xs">Source: {candidate.source}</p>
        </div>
        <span class="w-fit rounded-full border border-[var(--line)] px-2.5 py-1 text-xs font-semibold text-[var(--muted)]">{candidate.priority}</span>
      </article>
    {/each}
  </div>

  <div class="mt-5 grid gap-3 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4 sm:grid-cols-[auto_1fr] sm:items-center">
    <Database class="text-violet-600 dark:text-violet-300" size={20}/>
    <p class="muted text-sm leading-6">Ide baru adalah hipotesis dari source, bukan benchmark production. Ukur lewat fixture dan data sementara di CI; jangan kirim permintaan uji ke production dari workflow.</p>
  </div>
</section>
