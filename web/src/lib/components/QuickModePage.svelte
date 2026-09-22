<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import type { LabelItem } from '$lib/presentation';
  import TargetPicker from './TargetPicker.svelte';
  import JobTable from './JobTable.svelte';
  import { CheckCircle2, Clock3, Download, FileDown, FolderOpen, Gauge, Image, Plus, RefreshCw, ShieldCheck, Upload, XCircle, Zap } from '@lucide/svelte';

  type Job = Record<string, any>;
  type Stage = Record<string, any>;
  type Verification = {
    verified: boolean;
    purpose: string;
    worker: string;
    profile?: string | null;
    quick_mode?: boolean;
    [key: string]: any;
  };

  let sources = $state<any[]>([]);
  let labels = $state<LabelItem[]>([]);
  let chatRef = $state('');
  let url = $state('');
  let startId = $state('1');
  let overwriteStartId = $state(false);
  let saveNumericSource = $state(false);
  let label = $state('');
  let selected = $state('');
  let targetProfile = $state('');
  let targetWorker = $state('');
  let targetVerified = $state<Verification | null>(null);
  let message = $state('');
  let submitting = $state(false);
  let cooldown = $state(false);
  let cooldownTimer: ReturnType<typeof setTimeout> | undefined;
  let sourceLoading = $state(false);
  let statsLoading = $state(false);
  let allJobs = $state<Job[]>([]);
  let staging = $state<Stage[]>([]);
  let stagingErrors = $state<{worker: string; error: string}[]>([]);
  let stagingLoading = $state(false);
  let stagingRequested = $state(false);
  let stageAction = $state<string | null>(null);
  let filterProfile = $state('');
  let filterWorker = $state('');
  let filterStatus = $state('');
  let lastStatsRefreshed = $state<Date | null>(null);
  let lastStagingRefreshed = $state<Date | null>(null);
  let mounted = false;
  let lastProfile = '';

  const activeStatuses = ['queued', 'dispatched', 'running'];
  const statuses = ['failed', 'cancelled', 'succeeded'];
  const isNumeric = (value: string) => /^-?\d+$/.test(value.trim());
  const activeJobs = $derived(allJobs.filter((job) => activeStatuses.includes(job.status)));
  const stats = $derived({
    queued: allJobs.filter((job) => job.status === 'queued' || job.status === 'dispatched').length,
    running: allJobs.filter((job) => job.status === 'running').length,
    failed: allJobs.filter((job) => job.status === 'failed').length,
    cancelled: allJobs.filter((job) => job.status === 'cancelled').length,
    succeeded: allJobs.filter((job) => job.status === 'succeeded').length
  });
  const filteredStaging = $derived(staging.filter((item) =>
    !item.scan_missing &&
    (!filterProfile || item.profile === filterProfile || item.backend_job?.profile === filterProfile) &&
    (!filterWorker || item.worker === filterWorker) &&
    (!filterStatus || item.backend_job?.status === filterStatus)
  ));

  function formatClock(d: Date | null): string {
    if (!d) return '-';
    return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function getStageResumePhase(item: Stage): { phase: string; label: string; icon: any } {
    if (item.orphan && !item.json_present && !item.actual_media_count && !item.archive_parts) {
      return { phase: 'exporting', label: 'Import orphan', icon: ShieldCheck };
    }
    if (item.archive_parts && item.thumbnail_present) {
      return { phase: 'uploading', label: 'Upload', icon: Upload };
    }
    if (item.json_present && item.expected_media_count && item.actual_media_count < item.expected_media_count) {
      return { phase: 'downloading', label: 'Resume Download', icon: Download };
    }
    if (item.actual_media_count > 0 && !item.thumbnail_present) {
      return { phase: 'thumbnailing', label: 'Thumbnail', icon: Image };
    }
    if (item.thumbnail_present && !item.archive_parts) {
      return { phase: 'compressing', label: 'Compress', icon: ShieldCheck };
    }
    return { phase: 'exporting', label: 'Re-Export', icon: ShieldCheck };
  }

  function findActiveJobForStage(item: Stage): Job | null {
    const matching = activeJobs.find(
      (j) =>
        j.worker === item.worker &&
        (String(j.payload?.quick_retry?.stage_job_id || j.result?.stage_job_id || j.id) === item.stage_job_id ||
         (item.backend_job_id && j.id === item.backend_job_id))
    );
    if (matching) return matching;
    if (item.backend_job && activeStatuses.includes(item.backend_job.status)) {
      return item.backend_job;
    }
    return null;
  }

  async function loadSources(profile = targetProfile) {
    sourceLoading = true;
    try {
      const [sourceResponse, labelResponse] = await Promise.all([
        api<any>(profile ? `/sources?profile=${encodeURIComponent(profile)}` : '/sources'),
        api<any>('/labels')
      ]);
      sources = sourceResponse.items || [];
      labels = (labelResponse.items || []).filter((item: unknown): item is LabelItem => Boolean(item && typeof item === 'object' && typeof (item as LabelItem).label === 'string'));
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Source tidak dapat dimuat.';
    } finally {
      sourceLoading = false;
    }
  }

  async function loadStats() {
    statsLoading = true;
    try {
      const response = await api<{items: Job[]}>(`/jobs?limit=200&scope=global&kind=export&quick_mode=true&archived=false`);
      allJobs = response.items || [];
      lastStatsRefreshed = new Date();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Statistik Quick Mode tidak dapat dimuat.';
    } finally { statsLoading = false; }
  }

  async function loadStaging() {
    stagingRequested = true;
    stagingLoading = true;
    try {
      const response = await api<{items: Stage[]; errors?: {worker: string; error: string}[]}>(`/quick-mode/staging`);
      staging = response.items || [];
      stagingErrors = response.errors || [];
      lastStagingRefreshed = new Date();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Scan staging Quick Mode gagal.';
    } finally {
      stagingLoading = false;
    }
  }

  function stageProfile(item: Stage) {
    return String(item.profile || item.backend_job?.profile || targetProfile || '');
  }

  function stageSourcePayload(): Record<string, unknown> {
    return {
      ...(url.trim() ? { url: url.trim() } : chatRef.trim() ? { chat_ref: chatRef.trim() } : {}),
      ...(label.trim() ? { label: label.trim() } : {}),
      ...(overwriteStartId ? { start_id: Number(startId), use_url_message_id: true } : {})
    };
  }

  async function recoverStage(item: Stage, resumePhase?: string) {
    const profile = stageProfile(item);
    if (!profile) {
      message = 'Pilih profile pada form Quick Mode sebelum mengimport folder ini.';
      return;
    }
    const source = stageSourcePayload();
    if (!item.json_present && !item.actual_media_count && !item.archive_parts && !source.url && !source.chat_ref) {
      message = 'Folder ini tidak memiliki JSON. Isi URL atau chat ID untuk export ulang.';
      return;
    }
    const key = `${item.worker}:${item.stage_job_id}`;
    stageAction = key;
    try {
      await post('/quick-mode/recover', {
        worker: item.worker,
        stage_job_id: item.stage_job_id,
        profile,
        resume_phase: resumePhase,
        single_phase: Boolean(resumePhase && !['auto', 'exporting'].includes(resumePhase)),
        ...source
      });
      message = 'Folder Quick Mode dimasukkan kembali ke antrean.';
      await Promise.all([loadStaging(), loadStats()]);
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Recovery Quick Mode gagal.';
    } finally {
      stageAction = null;
    }
  }

  async function cancelStage(item: Stage) {
    const jobId = item.backend_job_id || item.backend_job?.id;
    if (!jobId) return;
    const actionKey = `${item.worker}:${item.stage_job_id}`;
    stageAction = actionKey;
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/cancel`);
      message = 'Permintaan cancel dikirim ke worker.';
      await Promise.all([loadStats(), loadStaging()]);
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Cancel Quick Mode gagal.';
    } finally {
      stageAction = null;
    }
  }

  function choose(value: string) {
    selected = value;
    const found = sources.find((source) => source.chat_ref === value);
    overwriteStartId = false;
    url = '';
    if (found) {
      chatRef = found.chat_ref;
      startId = String(Number(found.last_id || 0) + 1);
      label = found.label || '';
      saveNumericSource = isNumeric(found.chat_ref);
    } else {
      chatRef = '';
      startId = '1';
      label = '';
      saveNumericSource = false;
    }
  }

  function updateChatRef(value: string) {
    chatRef = value;
    url = '';
    if (selected && selected.replace(/^@/, '').toLowerCase() !== value.replace(/^@/, '').toLowerCase()) {
      selected = '';
      overwriteStartId = false;
      startId = '1';
      saveNumericSource = false;
    }
  }

  function updateUrl(value: string) {
    url = value;
    if (value.trim()) chatRef = '';
  }

  function resetForm() {
    chatRef = '';
    url = '';
    startId = '1';
    overwriteStartId = false;
    saveNumericSource = false;
    label = '';
    selected = '';
    targetVerified = null;
    message = '';
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldownTimer = undefined;
    cooldown = false;
  }

  function beginCooldown() {
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldown = true;
    cooldownTimer = setTimeout(() => {
      cooldownTimer = undefined;
      cooldown = false;
    }, 500);
  }

  async function submit() {
    if (submitting || cooldown) return;
    if (!targetVerified || targetVerified.profile !== targetProfile || targetVerified.worker !== targetWorker || targetVerified.quick_mode !== true) {
      message = 'Verifikasi profile dan worker Quick Mode terlebih dahulu.';
      return;
    }
    if (!chatRef.trim() && !url.trim()) {
      message = 'Masukkan username/chat ID atau URL Telegram.';
      return;
    }
    const manualStartId = Number(startId);
    if (overwriteStartId && (!Number.isInteger(manualStartId) || manualStartId < 1)) {
      message = 'Start ID manual harus berupa angka minimal 1.';
      return;
    }
    submitting = true;
    message = '';
    try {
      const payload: Record<string, unknown> = {
        ...(url.trim() ? { url: url.trim() } : { chat_ref: chatRef.trim() }),
        label: label || undefined,
        use_url_message_id: overwriteStartId,
        profile: targetProfile,
        worker: targetWorker,
        quick_mode: true
      };
      if (isNumeric(chatRef)) payload.save_source = saveNumericSource;
      if (overwriteStartId) payload.start_id = manualStartId;
      await post('/exports', payload);
      beginCooldown();
      message = 'Quick Mode berhasil masuk antrean.';
      await loadStats();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Quick Mode gagal dibuat.';
      if (cooldownTimer) clearTimeout(cooldownTimer);
      cooldownTimer = undefined;
      cooldown = false;
    } finally {
      submitting = false;
    }
  }

  function clearMessage() { message = ''; }

  $effect(() => {
    if (targetProfile && targetProfile !== lastProfile) {
      lastProfile = targetProfile;
      sources = [];
      loadSources(targetProfile);
    }
  });

  onMount(() => {
    mounted = true;
    loadSources(targetProfile);
    loadStats();
    const jobFinished = () => { loadStats(); loadStaging(); };
    window.addEventListener('tme3:job-finished', jobFinished);
    return () => {
      mounted = false;
      if (cooldownTimer) clearTimeout(cooldownTimer);
      window.removeEventListener('tme3:job-finished', jobFinished);
    };
  });
</script>

<header class="flex flex-wrap items-end justify-between gap-4">
  <div><p class="eyebrow">QUICK MODE MANAGER</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Pantau dan ulangi Quick Mode</h1><p class="muted mt-2">Satu antrean global untuk seluruh profile-worker yang dapat Anda akses.</p></div>
  <div class="hidden rounded-2xl bg-violet-50 p-3 text-violet-700 sm:block dark:bg-violet-950 dark:text-violet-200"><Zap size={25}/></div>
</header>

<div class="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
  {#each [{label:'Queued', key:'queued', icon:Clock3}, {label:'Running', key:'running', icon:Gauge}, {label:'Failed', key:'failed', icon:RefreshCw}, {label:'Cancelled', key:'cancelled', icon:RefreshCw}, {label:'Succeeded', key:'succeeded', icon:CheckCircle2}] as item}
    {@const Icon = item.icon}
    <div class="card flex items-center gap-3 p-4"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Icon size={18}/></div><div><p class="muted text-xs font-bold uppercase">{item.label}</p><b class="mt-1 block text-2xl">{stats[item.key as keyof typeof stats]}</b></div></div>
  {/each}
</div>

<section class="card mt-6 p-5 sm:p-6">
  <div class="flex flex-wrap items-center justify-between gap-3"><div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Plus size={20}/></div><div><h2 class="font-extrabold">Tambah Quick Mode</h2><p class="muted text-sm">Form ini selalu mengirim job dengan Quick Mode aktif.</p></div></div><span class="badge running">Quick Mode aktif</span></div>
  <div class="mt-5"><TargetPicker purpose="export" quickMode={true} bind:profile={targetProfile} bind:worker={targetWorker} bind:verified={targetVerified}/></div>
  <div class="mt-5 grid gap-4 lg:grid-cols-2">
    <label class="block text-sm font-bold">Pilih source tersimpan<select class="field mt-2" value={selected} onchange={(event) => choose((event.currentTarget as HTMLSelectElement).value)} disabled={sourceLoading}><option value="">Source baru...</option>{#each sources as source}<option value={source.chat_ref}>{source.label ? `${source.label} — ` : ''}{source.chat_ref} (berikutnya: {Number(source.last_id) + 1})</option>{/each}</select></label>
    <label class="block text-sm font-bold">Username atau chat ID<input class="field mt-2" value={chatRef} oninput={(event) => updateChatRef((event.currentTarget as HTMLInputElement).value)} placeholder="username atau numeric ID" /></label>
    <label class="block text-sm font-bold lg:col-span-2">URL Telegram manual <span class="muted font-normal">(opsional, mengesampingkan chat ID)</span><input class="field mt-2" value={url} oninput={(event) => updateUrl((event.currentTarget as HTMLInputElement).value)} placeholder="https://t.me/c/..." /></label>
    <label class="block text-sm font-bold">Start message ID<input class="field mt-2 disabled:cursor-not-allowed disabled:opacity-60" type="number" min="1" bind:value={startId} disabled={!overwriteStartId}/></label>
    <label class="block text-sm font-bold">Label<input class="field mt-2" list="quick-mode-labels" bind:value={label} placeholder="Opsional"/><datalist id="quick-mode-labels">{#each labels as item}<option value={item.label}></option>{/each}</datalist></label>
  </div>
  <label class="mt-4 flex cursor-pointer items-start gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface-soft)] p-4"><input class="mt-1 size-4 accent-violet-600" type="checkbox" role="switch" bind:checked={overwriteStartId}/><span><span class="block text-sm font-extrabold">Overwrite Start ID</span><span class="muted mt-1 block text-xs">Gunakan Start ID manual untuk job ini.</span></span></label>
  {#if isNumeric(chatRef)}<label class="mt-3 flex cursor-pointer items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"><input class="mt-1 size-4 accent-amber-600" type="checkbox" role="switch" bind:checked={saveNumericSource}/><span><span class="block text-sm font-extrabold">Simpan source numeric</span><span class="muted mt-1 block text-xs">Simpan Last ID numeric source untuk penggunaan berikutnya.</span></span></label>{/if}
  {#if labels.length}<div class="mt-3 flex flex-wrap gap-2">{#each labels as item}<button class="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-bold text-violet-700 dark:border-violet-900 dark:bg-violet-950 dark:text-violet-200" onclick={() => { label = item.label; clearMessage(); }}>{item.label}</button>{/each}</div>{/if}
  <div class="mt-5 flex flex-wrap justify-end gap-3"><button class="button secondary" onclick={resetForm} disabled={submitting}>Reset form</button><button class="button" onclick={submit} disabled={submitting || cooldown || !targetVerified}>{submitting ? 'Mengirim...' : cooldown ? 'Tunggu sebentar...' : 'Tambah Quick Mode'}<FileDown size={16}/></button></div>
  {#if message}<p class={`mt-3 rounded-xl px-3 py-2 text-sm ${message.includes('berhasil') ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-200'}`}>{message}</p>{/if}
</section>

<JobTable kind="export" title="Quick Mode berjalan dan antri" scope="global" profile={filterProfile} worker={filterWorker} quickMode={true} view="active"/>

<section class="card mt-6 p-4 sm:p-5">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div><p class="eyebrow">HISTORY FILTER</p><h2 class="mt-1 text-lg font-extrabold">Filter history Quick Mode</h2></div>
    <div class="flex items-center gap-2">
      {#if lastStatsRefreshed}<span class="muted text-xs">Terakhir diperbarui: {formatClock(lastStatsRefreshed)}</span>{/if}
      <button class="button secondary !py-1.5 !px-3 text-xs" onclick={loadStats} disabled={statsLoading} aria-label="Refresh statistik Quick Mode">
        <RefreshCw size={14} class={statsLoading ? 'animate-spin' : ''}/>Refresh statistik
      </button>
    </div>
  </div>
  <div class="mt-4 grid gap-3 sm:grid-cols-3">
    <label class="text-sm font-bold">Profile<select class="field mt-2" bind:value={filterProfile}><option value="">Semua profile</option>{#each session.current.profiles as item}<option value={item}>{item}</option>{/each}</select></label>
    <label class="text-sm font-bold">Worker<select class="field mt-2" bind:value={filterWorker}><option value="">Semua worker</option>{#each session.workers as item}<option value={item.name}>{item.name}</option>{/each}</select></label>
    <label class="text-sm font-bold">Status<select class="field mt-2" bind:value={filterStatus}><option value="">Semua status</option>{#each statuses as item}<option value={item}>{item}</option>{/each}</select></label>
  </div>
</section>

<section class="card mt-6 p-4 sm:p-5">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-3"><div class="grid size-10 place-items-center rounded-xl bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-200"><FolderOpen size={19}/></div><div><p class="eyebrow">PHYSICAL STAGING</p><h2 class="mt-1 text-lg font-extrabold">Folder Quick Mode di worker</h2><p class="muted text-sm">Scan langsung dari workspace, termasuk folder orphan setelah restart worker.</p></div></div>
    <div class="flex items-center gap-3">
      {#if lastStagingRefreshed}<span class="muted text-xs">Terakhir discan: {formatClock(lastStagingRefreshed)}</span>{/if}
      <button class="button secondary" onclick={loadStaging} disabled={stagingLoading}><RefreshCw size={15} class={stagingLoading ? 'animate-spin' : ''}/>Refresh scan</button>
    </div>
  </div>
  {#if stagingErrors.length}<div class="mt-4 space-y-2">{#each stagingErrors as item}<p class="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">Worker {item.worker} tidak dapat discan: {item.error}</p>{/each}</div>{/if}
  {#if !stagingRequested && !stagingLoading}<p class="muted mt-5 rounded-xl border border-dashed border-[var(--line)] p-5 text-center text-sm">Tekan <b>Refresh scan</b> untuk memuat folder staging Quick Mode.</p>{:else if !filteredStaging.length && !stagingLoading}<p class="muted mt-5 rounded-xl border border-dashed border-[var(--line)] p-5 text-center text-sm">Belum ada folder staging Quick Mode.</p>{/if}
  <div class="mt-4 space-y-3">
    {#each filteredStaging as item}
      {@const linked = item.backend_job}
      {@const activeJob = findActiveJobForStage(item)}
      {@const targetAction = getStageResumePhase(item)}
      {@const ActionIcon = targetAction.icon}
      {@const actionKey = `${item.worker}:${item.stage_job_id}`}
      {@const backendId = item.backend_job_id || item.backend_job?.id || (activeJob ? activeJob.id : null)}
      <article class="rounded-2xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              {#if backendId}
                <span class="font-mono text-xs font-semibold text-slate-500" title="Job backend: {backendId}">#{backendId.slice(0, 8)}</span>
              {/if}
              <b class="truncate">{item.folder_name || item.stage_job_id}</b>
              {#if item.orphan}<span class="badge failed">Orphan</span>{/if}
              <span class="badge running">{item.phase}</span>
              {#if item.backend_job}<span class={`badge ${item.backend_job.status}`}>{item.backend_job.status}</span>{/if}
            </div>
            <p class="muted mt-1 break-all text-xs">{item.worker} · {stageProfile(item) || 'profile belum dipilih'} · {item.staging_path}</p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            {#if activeJob}
              <span class="badge running animate-pulse">Sedang processing (#{activeJob.id.slice(0, 8)})</span>
              <button class="button danger !py-1.5 !px-3 text-xs" onclick={() => cancelStage(item)} disabled={stageAction === actionKey}>
                <XCircle size={15}/>Cancel
              </button>
            {:else}
              <button class="button secondary !py-1.5 !px-3 text-xs" onclick={() => recoverStage(item, targetAction.phase)} disabled={stageAction === actionKey}>
                <ActionIcon size={15}/>{targetAction.label}
              </button>
            {/if}
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-2 text-xs font-bold"><span class={`rounded-full px-2.5 py-1 ${item.json_present ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>JSON {item.json_present ? 'ada' : 'tidak ada'}</span><span class={`rounded-full px-2.5 py-1 ${item.actual_media_count ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>Media {item.actual_media_count}/{item.expected_media_count || '?'}</span><span class={`rounded-full px-2.5 py-1 ${item.thumbnail_present ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>PNG {item.thumbnail_present ? 'ada' : 'belum'}</span><span class={`rounded-full px-2.5 py-1 ${item.archive_parts ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>Archive {item.archive_parts}</span><span class={`rounded-full px-2.5 py-1 ${item.tdl_export_present && item.tdl_download_present ? 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>.tdl {item.tdl_export_present ? 'E' : '-'} / {item.tdl_download_present ? 'D' : '-'}</span><span class={`rounded-full px-2.5 py-1 ${item.worker_log_present ? 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800'}`}>Log {item.worker_log_present ? `${Math.ceil((item.worker_log_bytes || 0) / 1024)} KB` : 'belum'}</span></div>
        {#if item.cleanup_verification}
          {@const verification = item.cleanup_verification}
          <div class={`mt-3 rounded-xl px-3 py-2 text-xs ${verification.status === 'verified' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200' : 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200'}`}>
            <b>Crosscheck upload: {verification.status}</b>
            <span class="ml-2">Telegram {verification.channel_found ?? 0}/{verification.channel_expected ?? 0} · Google Drive {verification.drive_found ?? 0}/{verification.drive_expected ?? 0}</span>
            {#if verification.reason}<p class="mt-1">{verification.reason}</p>{/if}
          </div>
        {/if}
        {#if item.staging_cleaned}<p class="mt-3 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200">Staging dibersihkan setelah archive dan thumbnail terverifikasi.</p>{/if}
        {#if item.last_error}<p class="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">{item.last_error}</p>{/if}
        {#if backendId}<p class="muted mt-2 text-xs">Job backend: {backendId} · storage: {item.storage_folder || '-'}</p>{/if}
      </article>
    {/each}
  </div>
</section>

<JobTable kind="export" title="History Quick Mode lintas worker" scope="global" profile={filterProfile} worker={filterWorker} status={filterStatus} quickMode={true} retryable={true} view="history"/>
