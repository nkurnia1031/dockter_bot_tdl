<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post, put } from '$lib/api';
  import { formatDate } from '$lib/presentation';
  import JobTable from './JobTable.svelte';
  import { Archive, Clipboard, Download, Play, RefreshCw } from '@lucide/svelte';
  type Worker = { name: string; enabled?: boolean };
  type Profile = { name: string };
  type TdlSession = { name: 'root' | 'user1'; ready: boolean; code: string; identity_matches_metadata: boolean };
  type TdlDiagnostics = { worker: string; profile: string; checked_at: string; ready: boolean; identity_match: boolean; reason_codes: string[]; sessions: TdlSession[] };
  type BackupRun = { run_id: string; node_name: string; started_at?: string; status: string };
  let data = $state<any>({items:[]});
  let workers = $state<Worker[]>([]);
  let profiles = $state<Profile[]>([]);
  let diagnosticWorker = $state('');
  let diagnosticProfile = $state('');
  let diagnostics = $state<TdlDiagnostics | null>(null);
  let diagnosticFailure = $state('');
  let diagnosticMessage = $state('');
  let diagnosticChoicesFailure = $state('');
  let diagnosing = $state(false);
  let verifyRunId = $state('');
  let verificationJob = $state<any | null>(null);
  let verificationSubmitting = $state(false);
  let verificationRefreshing = $state(false);
  let verificationFailure = $state('');
  let verificationMessage = $state('');
  let verificationTimer: ReturnType<typeof setInterval> | undefined;
  const runsForSelectedWorker = $derived<BackupRun[]>(
    (data.items || []).filter((item: BackupRun) => item.node_name === diagnosticWorker && item.status === 'complete')
  );
  const verificationReport = $derived<any | null>(
    verificationJob?.result?.value?.report || verificationJob?.result?.report || null
  );
  let draft = $state<any>({ enabled: true, schedule: '03:00', timezone: 'Asia/Jakarta', retention: 7, volume_size: '45m', channel: '', storage_trash_retention_days: 30, job_stall_timeout_seconds: 600, job_cancel_grace_seconds: 30 });
  let message = $state('');
  let pending = $state(false);
  let saving = $state(false);
  async function load() {
    try {
      data = await api('/backups/status');
      draft = {
        enabled: data.enabled,
        schedule: data.schedule,
        timezone: data.timezone,
        retention: data.retention,
        volume_size: data.volume_size,
        channel: data.channel || '',
        storage_trash_retention_days: data.storage_trash_retention_days ?? 30,
        job_stall_timeout_seconds: data.job_stall_timeout_seconds ?? 600,
        job_cancel_grace_seconds: data.job_cancel_grace_seconds ?? 30,
      };
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Status backup gagal dimuat.';
    }
  }
  async function run() {
    pending = true;
    try { await post('/backups'); message = 'Backup seluruh node mulai dijalankan.'; await load(); }
    finally { pending = false; }
  }
  async function saveSettings() {
    saving = true;
    try {
      await put('/backups/settings', {
        ...draft,
        retention: Number(draft.retention),
        storage_trash_retention_days: Number(draft.storage_trash_retention_days),
        job_stall_timeout_seconds: Number(draft.job_stall_timeout_seconds),
        job_cancel_grace_seconds: Number(draft.job_cancel_grace_seconds),
      });
      message = 'Pengaturan disimpan dan langsung berlaku.';
      await load();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Pengaturan backup gagal disimpan.';
    } finally { saving = false; }
  }
  async function loadDiagnosticChoices() {
    diagnosticChoicesFailure = '';
    try {
      const [workerResult, profileResult] = await Promise.all([
        api<{ items: Worker[] }>('/workers'),
        api<{ items: Profile[] }>('/profiles'),
      ]);
      workers = workerResult.items || [];
      profiles = profileResult.items || [];
      diagnosticWorker = diagnosticWorker || workers[0]?.name || '';
      diagnosticProfile = diagnosticProfile || profiles[0]?.name || '';
    } catch (cause) {
      diagnosticChoicesFailure = cause instanceof Error ? cause.message : 'Daftar worker dan profil gagal dimuat.';
    }
  }
  async function createDiagnostics() {
    if (!diagnosticWorker || !diagnosticProfile) return;
    diagnosing = true;
    diagnostics = null;
    diagnosticFailure = '';
    diagnosticMessage = '';
    try {
      diagnostics = await post<TdlDiagnostics>('/backups/tdl-diagnostics', {
        worker: diagnosticWorker,
        profile: diagnosticProfile,
      });
      diagnosticMessage = 'JSON diagnosis dibuat dari worker dan profil yang dipilih.';
    } catch (cause) {
      diagnosticFailure = cause instanceof Error ? cause.message : 'Diagnosis TDL gagal dijalankan.';
    } finally {
      diagnosing = false;
    }
  }
  function diagnosticsJson() {
    return diagnostics ? `${JSON.stringify(diagnostics, null, 2)}\n` : '';
  }
  function downloadDiagnostics() {
    if (!diagnostics) return;
    const blob = new Blob([diagnosticsJson()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'tdl-diagnostics.json';
    link.click();
    URL.revokeObjectURL(url);
  }
  async function copyDiagnostics() {
    if (!diagnostics) return;
    try {
      await navigator.clipboard.writeText(diagnosticsJson());
      diagnosticMessage = 'JSON diagnosis disalin.';
    } catch {
      diagnosticFailure = 'Clipboard tidak tersedia. Gunakan tombol Unduh JSON.';
    }
  }
  function stopVerificationPolling() {
    if (verificationTimer) clearInterval(verificationTimer);
    verificationTimer = undefined;
  }
  async function refreshVerificationJob() {
    const id = String(verificationJob?.id || '');
    if (!id || verificationRefreshing) return;
    verificationRefreshing = true;
    try {
      verificationJob = await api(`/jobs/${encodeURIComponent(id)}`);
      if (['succeeded', 'failed', 'cancelled'].includes(String(verificationJob?.status || ''))) {
        stopVerificationPolling();
      }
    } catch (cause) {
      verificationFailure = cause instanceof Error ? cause.message : 'Status verifikasi backup gagal dimuat.';
    } finally {
      verificationRefreshing = false;
    }
  }
  async function verifyBackupFromChannel() {
    if (!diagnosticWorker || !diagnosticProfile || !verifyRunId) return;
    stopVerificationPolling();
    verificationSubmitting = true;
    verificationJob = null;
    verificationFailure = '';
    verificationMessage = '';
    try {
      verificationJob = await api('/backups/verify', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ worker: diagnosticWorker, profile: diagnosticProfile, run_id: verifyRunId }),
      });
      verificationMessage = 'Job diterima. Worker akan mengambil part dari channel backup lalu memeriksa arsip dan sesi.';
      if (!['succeeded', 'failed', 'cancelled'].includes(String(verificationJob?.status || ''))) {
        verificationTimer = setInterval(() => { void refreshVerificationJob(); }, 2500);
      }
    } catch (cause) {
      verificationFailure = cause instanceof Error ? cause.message : 'Job verifikasi backup gagal dibuat.';
    } finally {
      verificationSubmitting = false;
    }
  }
  function verificationJson() {
    return verificationReport ? `${JSON.stringify(verificationReport, null, 2)}\n` : '';
  }
  function downloadVerificationJson() {
    if (!verificationReport) return;
    const url = URL.createObjectURL(new Blob([verificationJson()], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `backup-verification-${verificationReport.worker}-${verificationReport.profile}-${verificationReport.run_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  async function copyVerificationJson() {
    if (!verificationReport) return;
    try {
      await navigator.clipboard.writeText(verificationJson());
      verificationMessage = 'JSON hasil verifikasi disalin.';
    } catch {
      verificationFailure = 'Clipboard tidak tersedia. Gunakan tombol Unduh JSON.';
    }
  }
  $effect(() => {
    if (!runsForSelectedWorker.some((item) => item.run_id === verifyRunId)) {
      verifyRunId = runsForSelectedWorker[0]?.run_id || '';
    }
  });
  onMount(() => {
    load();
    loadDiagnosticChoices();
    return () => stopVerificationPolling();
  });
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">BACKUP</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Backup terenkripsi</h1><p class="muted mt-2">Status per node, jadwal, dan hasil upload channel.</p></div><div class="page-icon"><Archive size={23}/></div></header>
<section class="card mt-7 p-5 sm:p-6">
  <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="font-extrabold">Konfigurasi aktif</h2><p class="muted mt-1 text-sm">{data.schedule || '-'} · {data.timezone || '-'} · retensi {data.retention ?? '-'} · volume {data.volume_size || '-'}</p></div><div class="flex gap-2"><button class="button secondary" onclick={load}><RefreshCw size={15}/>Refresh</button><button class="button" onclick={run} disabled={pending || data.enabled === false}><Play size={15}/>{pending ? 'Memulai...' : 'Backup sekarang'}</button></div></div>
  {#if message}<p class="mt-4 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
  <details class="mt-5 rounded-2xl border border-[var(--line)] p-4"><summary class="cursor-pointer font-bold">Ubah pengaturan backup dan operasi</summary>
    <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <label class="flex items-center gap-2 text-sm font-bold"><input type="checkbox" bind:checked={draft.enabled}/>Jadwal backup aktif</label>
      <label class="text-sm font-bold">Jadwal harian<input class="field mt-2" type="time" bind:value={draft.schedule}/></label>
      <label class="text-sm font-bold">Zona waktu<input class="field mt-2" bind:value={draft.timezone} placeholder="Asia/Jakarta"/></label>
      <label class="text-sm font-bold">Jumlah backup disimpan<input class="field mt-2" type="number" min="1" max="3650" bind:value={draft.retention}/></label>
      <label class="text-sm font-bold">Ukuran setiap arsip<input class="field mt-2" bind:value={draft.volume_size} placeholder="45m"/></label>
      <label class="text-sm font-bold">Tujuan channel backup Telegram<input class="field mt-2" bind:value={draft.channel} placeholder="-100123456789 · @channel · https://t.me/channel"/><span class="muted mt-1 block text-xs">Username atau link publik harus menunjuk channel yang dapat diakses bot. Nomor telepon tidak didukung.</span></label>
      <label class="text-sm font-bold">Retensi Trash Storage (hari)<input class="field mt-2" type="number" min="1" max="3650" bind:value={draft.storage_trash_retention_days}/></label>
      <label class="text-sm font-bold">Timeout job macet (detik)<input class="field mt-2" type="number" min="0" max="86400" bind:value={draft.job_stall_timeout_seconds}/></label>
      <label class="text-sm font-bold">Masa tunggu cancel (detik)<input class="field mt-2" type="number" min="0" max="3600" bind:value={draft.job_cancel_grace_seconds}/></label>
    </div>
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3"><p class="muted text-xs">Pengaturan ini tersimpan di volume backend dan berlaku langsung untuk jadwal serta job baru. Password arsip ada di Pengaturan Utility dan nilainya tidak ditampilkan kembali.</p><button class="button" onclick={saveSettings} disabled={saving}>{saving ? 'Menyimpan...' : 'Simpan pengaturan'}</button></div>
  </details>
  <section class="mt-5 rounded-2xl border border-[var(--line)] p-4 sm:p-5" aria-labelledby="backup-diagnostics-title">
    <div><h2 id="backup-diagnostics-title" class="font-extrabold">Diagnosis dan verifikasi backup worker</h2><p class="muted mt-1 text-sm">Diagnosis TDL menjalankan pemeriksaan identitas pada sesi root dan user1 tanpa mengubah sesi. Verifikasi mengekspor JSON channel dengan <code>--with-content</code>, mencocokkan caption berdasarkan worker, run, dan nama part, lalu mengunduh tiap file memakai message ID hasil pencocokan.</p></div>
    <div class="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <label class="text-sm font-bold">Worker<select class="field mt-2" bind:value={diagnosticWorker} disabled={diagnosing}><option value="">Pilih worker</option>{#each workers as worker}<option value={worker.name}>{worker.name}{worker.enabled === false ? ' (nonaktif)' : ''}</option>{/each}</select></label>
      <label class="text-sm font-bold">Profil<select class="field mt-2" bind:value={diagnosticProfile} disabled={diagnosing}><option value="">Pilih profil</option>{#each profiles as profile}<option value={profile.name}>{profile.name}</option>{/each}</select></label>
      <button class="button" onclick={createDiagnostics} disabled={diagnosing || !diagnosticWorker || !diagnosticProfile}><RefreshCw size={15}/>{diagnosing ? 'Memeriksa sesi...' : 'Buat JSON diagnosis'}</button>
    </div>
    {#if diagnosticChoicesFailure}<p class="mt-3 rounded-xl bg-rose-950/50 p-3 text-sm text-rose-200" role="alert">{diagnosticChoicesFailure}<button class="ml-2 underline" onclick={loadDiagnosticChoices}>Muat ulang pilihan</button></p>{/if}
    {#if diagnosticFailure}<p class="mt-3 rounded-xl bg-rose-950/50 p-3 text-sm text-rose-200" role="alert">{diagnosticFailure}</p>{/if}
    {#if diagnosticMessage}<p class="mt-3 rounded-xl bg-[var(--brand-soft)] p-3 text-sm" role="status">{diagnosticMessage}</p>{/if}
    {#if diagnostics}
      <div class="mt-4 rounded-xl border border-[var(--line)] p-4">
        <div class="flex flex-wrap items-center justify-between gap-3"><div><p class="font-bold">{diagnostics.worker} / {diagnostics.profile} · {diagnostics.ready ? 'Kedua sesi lolos' : 'Ada sesi yang gagal'}</p><p class="muted mt-1 text-xs">Diperiksa {diagnostics.checked_at} · identitas {diagnostics.identity_match ? 'cocok' : 'tidak cocok'}</p></div><div class="flex gap-2"><button class="button secondary !px-3 !py-2" onclick={copyDiagnostics}><Clipboard size={15}/>Salin JSON</button><button class="button secondary !px-3 !py-2" onclick={downloadDiagnostics}><Download size={15}/>Unduh JSON</button></div></div>
        {#if diagnostics.reason_codes.length}<p class="mt-3 text-sm text-rose-300">Alasan: {diagnostics.reason_codes.join(', ')}</p>{/if}
        <div class="mt-3 grid gap-2 sm:grid-cols-2">{#each diagnostics.sessions as item}<div class="rounded-lg bg-[var(--panel)] p-3 text-sm"><p class="font-bold">{item.name} · {item.ready ? 'Siap' : 'Gagal'}</p><p class="muted mt-1">{item.code} · identitas {item.identity_matches_metadata ? 'cocok' : 'tidak cocok'}</p></div>{/each}</div>
        <details class="mt-3"><summary class="cursor-pointer text-sm font-bold">Lihat JSON</summary><pre class="mt-2 max-h-72 overflow-auto rounded-lg bg-[var(--panel)] p-3 text-xs">{diagnosticsJson()}</pre></details>
      </div>
    {/if}
    <div class="mt-5 border-t border-[var(--line)] pt-5">
      <div class="flex flex-wrap items-start justify-between gap-3"><div><h3 class="font-extrabold">Unduh dan verifikasi arsip dari channel</h3><p class="muted mt-1 max-w-3xl text-sm">Worker mencocokkan node, run, dan nama part dari caption channel, lalu mengunduh hanya message ID yang cocok. Pemeriksaan mencakup password, integritas 7z, manifest, dan sesi profil; checksum katalog dicocokkan jika tersedia. File di channel tidak dikirim ulang atau dihapus.</p></div></div>
      <div class="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <label class="text-sm font-bold">Run backup lengkap untuk {diagnosticWorker || 'worker'}
          <select class="field mt-2" bind:value={verifyRunId} disabled={verificationSubmitting || !runsForSelectedWorker.length}>
            <option value="">Pilih run backup</option>
            {#each runsForSelectedWorker as item (item.run_id)}<option value={item.run_id}>{item.run_id} Â· {formatDate(item.started_at)}</option>{/each}
          </select>
        </label>
        <button class="button" onclick={verifyBackupFromChannel} disabled={verificationSubmitting || !diagnosticWorker || !diagnosticProfile || !verifyRunId || workers.find((item) => item.name === diagnosticWorker)?.enabled === false}>
          <Download size={15}/>{verificationSubmitting ? 'Mengirim job...' : 'Unduh dari channel & verifikasi'}
        </button>
      </div>
      {#if !runsForSelectedWorker.length}<p class="muted mt-2 text-xs">Belum ada run berstatus complete untuk worker ini.</p>{/if}
      {#if workers.find((item) => item.name === diagnosticWorker)?.enabled === false}<p class="mt-3 rounded-xl bg-amber-950/40 p-3 text-sm text-amber-200" role="status">Worker nonaktif. Aktifkan worker sebelum menjalankan verifikasi.</p>{/if}
      {#if verificationFailure}<p class="mt-3 rounded-xl bg-rose-950/50 p-3 text-sm text-rose-200" role="alert">{verificationFailure}</p>{/if}
      {#if verificationMessage}<p class="mt-3 rounded-xl bg-[var(--brand-soft)] p-3 text-sm" role="status">{verificationMessage}</p>{/if}
      {#if verificationJob}
        <div class="mt-4 rounded-xl border border-[var(--line)] p-4">
          <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="font-bold">Job verifikasi Â· {verificationJob.worker} / {verificationJob.profile}</p><p class="muted mt-1 font-mono text-xs">{verificationJob.id}</p></div><div class="flex items-center gap-2"><span class={`badge ${verificationJob.status}`}>{verificationJob.status}</span><button class="button secondary !px-3 !py-2" onclick={refreshVerificationJob} disabled={verificationRefreshing || !verificationJob.id}><RefreshCw size={14} class={verificationRefreshing ? 'animate-spin' : ''}/>Muat status</button></div></div>
          {#if verificationJob.progress?.message}<p class="muted mt-3 text-sm">{verificationJob.progress.message}</p>{/if}
          {#if verificationJob.error?.message}<p class="mt-3 text-sm text-rose-300">{verificationJob.error.message}</p>{/if}
          {#if verificationJob.status === 'succeeded' && verificationReport?.status === 'failed'}<p class="mt-3 rounded-lg bg-rose-950/40 p-3 text-sm text-rose-200">Job selesai dijalankan, tetapi arsip tidak lolos pemeriksaan. Status job hanya menandai prosesnya selesai; lihat kode alasan pada laporan JSON.</p>{/if}
          {#if verificationReport}
            <div class="mt-4 rounded-lg bg-[var(--panel)] p-3">
              {#if verificationReport.status === 'verified' && verificationReport.canary_evidence_status === 'ready_for_operator_review'}<p class="mb-3 rounded-lg bg-emerald-950/40 p-3 text-sm text-emerald-200">Sesi TDL lolos; bukti siap ditinjau untuk canary.</p>{:else if verificationReport.status === 'verified' && verificationReport.canary_evidence_status === 'tdl_failed'}<p class="mb-3 rounded-lg bg-rose-950/40 p-3 text-sm text-rose-200">Arsip valid, tetapi sesi TDL pada worker/profil ini gagal. Belum aman untuk canary.</p>{:else if verificationReport.status === 'verified' && verificationReport.canary_evidence_status !== 'backup_failed'}<p class="mb-3 rounded-lg bg-amber-950/40 p-3 text-sm text-amber-200">Arsip lolos pemeriksaan file, tetapi profil belum dinyatakan siap untuk canary. Periksa diagnosis TDL dan status bukti pada JSON.</p>{/if}
              <div class="flex flex-wrap items-center justify-between gap-2"><div><p class="font-bold">Arsip {verificationReport.status === 'verified' ? 'terverifikasi' : 'gagal diverifikasi'}</p><p class="muted mt-1 text-xs">{verificationReport.worker} / {verificationReport.profile} Â· run {verificationReport.run_id} Â· {verificationReport.part_count} part</p></div><div class="flex gap-2"><button class="button secondary !px-3 !py-2" onclick={copyVerificationJson}><Clipboard size={14}/>Salin JSON</button><button class="button secondary !px-3 !py-2" onclick={downloadVerificationJson}><Download size={14}/>Unduh JSON</button></div></div>
              {#if verificationReport.reason_codes?.length}<p class="mt-3 text-sm text-rose-300">Alasan: {verificationReport.reason_codes.join(', ')}</p>{/if}
              {#if verificationReport.tdl_diagnostics}<p class="muted mt-2 text-xs">Diagnosis TDL: {verificationReport.tdl_diagnostics.ready ? 'siap' : 'gagal'} Â· identitas {verificationReport.tdl_diagnostics.identity_match ? 'cocok' : 'tidak cocok'}</p>{/if}
              {#if verificationReport.checksum_validation && verificationReport.checksum_validation !== 'verified'}<p class="mt-3 rounded-lg bg-amber-950/40 p-3 text-sm text-amber-200">Checksum katalog {verificationReport.checksum_validation === 'partial' ? 'hanya tersedia untuk sebagian part' : 'tidak tersedia'}. Arsip tetap diperiksa melalui password, integritas 7z, dan manifest.</p>{/if}
              {#if verificationReport.download?.matched_parts?.length}<details class="mt-3"><summary class="cursor-pointer text-sm font-bold">Lihat part dan message ID yang diunduh</summary><ul class="mt-2 space-y-1 text-xs">{#each verificationReport.download.matched_parts as item}<li><code>{item.name}</code> · message ID <code>{item.message_id}</code></li>{/each}</ul></details>{/if}
              <details class="mt-3"><summary class="cursor-pointer text-sm font-bold">Lihat JSON canary lengkap</summary><pre class="mt-2 max-h-80 overflow-auto rounded-lg bg-[var(--panel-strong)] p-3 text-xs">{verificationJson()}</pre></details>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </section>
  <div class="mt-5 overflow-x-auto"><table class="w-full min-w-[850px] text-left text-sm"><thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="py-3">Node</th><th>Run ID lengkap</th><th>Status</th><th>Mulai</th><th>Selesai</th><th>Error</th></tr></thead><tbody class="divide-y border-[var(--line)]">{#each data.items || [] as item}<tr><td class="py-4 font-bold">{item.node_name}</td><td><code class="select-all break-all text-xs">{item.run_id || '-'}</code></td><td><span class={`badge ${item.status}`}>{item.status}</span></td><td>{formatDate(item.started_at)}</td><td>{formatDate(item.completed_at)}</td><td class="max-w-72 truncate text-rose-600">{item.error || '-'}</td></tr>{:else}<tr><td colspan="6" class="py-10 text-center muted">Belum ada riwayat backup.</td></tr>{/each}</tbody></table></div>
</section>
<JobTable kind="backup_node" title="Job backup"/>
<JobTable kind="backup_verify" title="Job verifikasi arsip backup" view="history"/>
