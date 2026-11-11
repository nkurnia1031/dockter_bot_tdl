<script setup lang="ts">
const completedOptimizations = [
  {
    title: "Query status job",
    detail:
      "Query multi-status kini memakai satu operasi list dan satu count dengan pagination global serta urutan stabil.",
    commit: "be43f9a",
  },
  {
    title: "Metrik batas Quick Mode",
    detail:
      "Pembacaan batas dan counter Quick Mode digabung dari tiga SELECT menjadi satu, dengan hasil yang sama.",
    commit: "523f39c",
  },
  {
    title: "Sequence event saat dispatch",
    detail:
      "Dispatch mengambil sequence terakhir dari SQLite tanpa memuat seluruh riwayat event job.",
    commit: "594d66d",
  },
  {
    title: "Scan Profil",
    detail:
      "Backend memakai diagnosis TDL dari canary sebagai sumber fingerprint, menghilangkan probe diagnosis kedua, dan tetap merahasiakan fingerprint dari respons publik.",
    commit: "d65b9ff",
  },
];

const nextCandidates = [
  {
    title: "Kerja ulang pada metrik monitor",
    evidence:
      "Monitor aktif refresh tiap 2,5 detik. monitor_metrics() masih membaca payload/progress job aktif dan job 24 jam terakhir, mengurai JSON, lalu mengagregasi di Python.",
    suggestion:
      "Ukur durasi query, jumlah row, dan biaya parse di GitHub Actions dengan volume fixture bertingkat. Pilih ringkasan inkremental atau pembacaan lebih sempit hanya jika metrik menunjukkan biaya yang berarti.",
    source:
      "Monitor aktivitas · SqliteJobRepository.monitor_metrics()",
    priority: "Prioritas berikutnya",
  },
  {
    title: "Setup koneksi SQLite",
    evidence:
      "SqliteJobRepository._db() membuka koneksi per operasi dan _connect() menjalankan PRAGMA journal_mode=WAL pada setiap koneksi.",
    suggestion:
      "Bandingkan biaya koneksi dan PRAGMA pada beban baca/tulis bersamaan. Jika signifikan, pindahkan konfigurasi WAL ke inisialisasi database; pertahankan foreign keys dan batas transaksi per koneksi.",
    source: "tme3bot/infrastructure/job_store.py · _db() / _connect()",
    priority: "Ukur dulu",
  },
];
</script>

<template>
  <main class="page-stack development-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">CATATAN INTERNAL · SNAPSHOT 28 OKTOBER 2026</p>
        <h1>Pengembangan</h1>
        <p class="muted">Aplikasi sudah stabil. Halaman ini merangkum keputusan penting dan pekerjaan berikutnya untuk tahap deployment awal; isinya catatan, bukan status realtime.</p>
      </div>
      <span class="status-pill status-neutral">Fokus: kualitas rilis</span>
    </header>

    <section class="focus-card" aria-labelledby="focus-title">
      <p class="eyebrow">SARAN SAYA</p>
      <h2 id="focus-title">Prioritas berikutnya: ukur metrik monitor</h2>
      <p>Empat optimasi backend terbaru sudah selesai. Metrik monitor masih mengurai data job setiap refresh 2,5 detik; ukur dulu dengan fixture bertingkat di GitHub Actions sebelum memilih perubahan berikutnya.</p>
    </section>

    <div class="guidance-grid">
      <section class="panel guidance-card" aria-labelledby="tests-title">
        <h2 id="tests-title">Tes otomatis</h2>
        <ul>
          <li><strong>Backend:</strong> compile, unit, dan integration tests Python.</li>
          <li><strong>Web:</strong> Vue type-check, Vitest, build static, dan browser E2E berjalan di GitHub Actions dengan API palsu.</li>
          <li><strong>Browser E2E:</strong> trusted-device flow di Linux dan Windows.</li>
        </ul>
        <a href="https://github.com/nkurnia1031/dockter_bot_tdl/actions" target="_blank" rel="noopener noreferrer">Buka GitHub Actions ↗</a>
        <p class="muted">Runner standar gratis untuk repo publik. Batas artifact dan cache tetap berlaku; tes tidak perlu menyimpan artifact.</p>
      </section>
      <section class="panel guidance-card" aria-labelledby="production-title">
        <h2 id="production-title">Batas tes production</h2>
        <p>Tes production hanya dijalankan dari mesin/workspace ini melalui tooling lokal dan dengan izin eksplisit. GitHub Actions memakai fixture, data sementara, serta server lokal/terisolasi.</p>
        <div class="warning-box"><strong>Production tidak masuk CI</strong><p>Jangan masukkan URL, credential, sesi browser, atau cookie production ke workflow.</p></div>
      </section>
      <section class="panel guidance-card" aria-labelledby="branch-title">
        <h2 id="branch-title">Status aturan branch</h2>
        <p>Pada pemeriksaan 26 Oktober 2026, branch <code>main</code> belum memiliki required status checks. CI dapat melaporkan kegagalan, tetapi belum menghalangi merge atau push langsung.</p>
        <p class="soft-note">Required checks akan mengubah alur kerja menjadi PR sebelum merge. Catat keputusan ini sebelum mengaktifkannya.</p>
      </section>
    </div>

    <section class="panel optimization-panel" aria-labelledby="backend-title">
      <header class="optimization-heading">
        <div><p class="eyebrow">PEMBARUAN 28 OKTOBER 2026 · SOURCE + CI</p><h2 id="backend-title">Optimasi backend</h2></div>
        <span class="muted">4 perubahan selesai</span>
      </header>
      <h3 class="section-label done-label">Selesai</h3>
      <div class="report-list">
        <article v-for="(item, index) in completedOptimizations" :key="item.commit" class="report-row">
          <span class="report-number">0{{ index + 1 }}</span><div><h4>{{ item.title }}</h4><p class="muted">{{ item.detail }}</p></div>
          <a :href="`https://github.com/nkurnia1031/dockter_bot_tdl/commit/${item.commit}`" target="_blank" rel="noopener noreferrer">{{ item.commit }}</a>
        </article>
      </div>
      <h3 class="section-label next-label">Ide berikutnya</h3>
      <div class="report-list">
        <article v-for="(candidate, index) in nextCandidates" :key="candidate.title" class="report-row">
          <span class="report-number">0{{ index + 1 }}</span><div><h4>{{ candidate.title }}</h4><p class="muted">{{ candidate.evidence }}</p><p><strong>Arah:</strong> {{ candidate.suggestion }}</p><p class="muted report-source">Source: {{ candidate.source }}</p></div>
          <span class="status-pill status-neutral">{{ candidate.priority }}</span>
        </article>
      </div>
      <p class="muted report-note">Ide baru adalah hipotesis dari source, bukan benchmark production. Ukur lewat fixture dan data sementara di CI; jangan kirim permintaan uji ke production dari workflow.</p>
    </section>
  </main>
</template>

<style scoped>
.focus-card { padding:1rem 1.15rem; border:1px solid var(--line); border-radius:1rem; background:linear-gradient(135deg,var(--panel-soft),var(--panel)); }
.focus-card h2,.optimization-heading h2 { margin:.25rem 0; font-size:1.05rem; }
.focus-card p:last-child { margin:0; max-width:64rem; color:var(--muted); font-size:.83rem; line-height:1.6; }
.guidance-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; }
.guidance-card { display:grid; align-content:start; gap:.7rem; padding:1rem; }
.guidance-card h2 { margin:0; font-size:.9rem; }
.guidance-card p,.guidance-card li { font-size:.78rem; line-height:1.55; }
.guidance-card p { margin:0; }
.guidance-card ul { display:grid; gap:.35rem; margin:0; padding-left:1.1rem; }
.guidance-card a,.report-row a { width:max-content; color:var(--accent); font-size:.78rem; font-weight:700; text-decoration:underline; }
.warning-box,.soft-note { padding:.7rem; border:1px solid var(--line); border-radius:.65rem; background:var(--panel-soft); font-size:.76rem; }
.warning-box p { margin-top:.25rem; }
.optimization-panel { display:grid; gap:.75rem; padding:1rem; }
.optimization-heading { display:flex; align-items:end; justify-content:space-between; gap:.7rem; }
.optimization-heading .muted { font-size:.72rem; }
.section-label { margin:0; font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; }
.done-label { color:var(--success); }
.next-label { color:var(--accent); }
.report-list { display:grid; }
.report-row { display:grid; grid-template-columns:2rem minmax(0,1fr) auto; align-items:start; gap:.7rem; padding:.75rem 0; border-bottom:1px solid var(--line); }
.report-row:last-child { border:0; }
.report-row h4 { margin:0; font-size:.82rem; }
.report-row p { margin:.25rem 0 0; font-size:.76rem; line-height:1.55; }
.report-number { display:grid; width:1.7rem; height:1.7rem; place-items:center; border-radius:.5rem; background:var(--panel-soft); color:var(--muted); font-size:.7rem; font-weight:800; }
.report-source { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.68rem !important; }
.report-note { margin:0; padding:.7rem; border-radius:.6rem; background:var(--panel-soft); font-size:.73rem; }
@media(max-width:850px) { .guidance-grid { grid-template-columns:1fr; } }
@media(max-width:600px) { .report-row { grid-template-columns:2rem minmax(0,1fr); } .report-row > a,.report-row > .status-pill { grid-column:2; } }
</style>
