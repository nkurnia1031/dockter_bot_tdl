<script lang="ts">
  import { api } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import WorkspaceExplorer from './WorkspaceExplorer.svelte';
  import JobTable from './JobTable.svelte';
  import { MessageCircle, Send } from '@lucide/svelte';

  type LocalProfile = { name: string; ready?: boolean; reason_codes?: string[] };
  type Job = Record<string, any>;

  let worker = $state('');
  let chatRef = $state('');
  let profiles = $state<LocalProfile[]>([]);
  let selectedProfiles = $state<string[]>([]);
  let folders = $state<string[]>([]);
  let transferMode = $state<'copy'|'move'>('copy');
  let profilesLoading = $state(false);
  let submitting = $state(false);
  let loadingError = $state('');
  let error = $state('');
  let notice = $state('');
  let profileLoadGeneration = 0;

  const availableWorkers = $derived(session.workers.filter((item) => item.enabled !== false));

  $effect(() => {
    const workers = availableWorkers;
    if (worker || !workers.length) return;
    const initialWorker = workers.find((item) => item.name === session.current.actor?.worker_route)?.name
      || workers[0]?.name || '';
    if (!initialWorker) return;
    worker = initialWorker;
    void loadProfiles(initialWorker);
  });

  async function loadProfiles(target: string) {
    const generation = ++profileLoadGeneration;
    profilesLoading = true;
    loadingError = '';
    profiles = [];
    selectedProfiles = [];
    try {
      const response = await api<{items?: LocalProfile[]}>(`/workers/${encodeURIComponent(target)}/profiles/local`);
      if (generation !== profileLoadGeneration) return;
      profiles = (response.items || []).filter((item) => typeof item.name === 'string' && item.name.trim());
      const preferred = session.current.actor?.profile;
      selectedProfiles = profiles.some((item) => item.name === preferred)
        ? [preferred as string]
        : profiles.slice(0, 1).map((item) => item.name);
    } catch (cause) {
      if (generation !== profileLoadGeneration) return;
      loadingError = cause instanceof Error ? cause.message : 'Daftar profil worker tidak dapat dimuat.';
    } finally {
      if (generation === profileLoadGeneration) profilesLoading = false;
    }
  }

  function changeWorker(target: string) {
    if (target === worker) return;
    worker = target;
    folders = [];
    if (target) void loadProfiles(target);
  }

  function toggleProfile(name: string) {
    selectedProfiles = selectedProfiles.includes(name)
      ? selectedProfiles.filter((item) => item !== name)
      : [...selectedProfiles, name];
  }

  function selectionOrder(name: string): number | undefined {
    const index = selectedProfiles.indexOf(name);
    return index < 0 ? undefined : index + 1;
  }

  function idempotencyKey() {
    return globalThis.crypto?.randomUUID?.()
      || `chat-send-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  async function submit() {
    error = '';
    notice = '';
    if (!worker || !selectedProfiles.length || !folders.length || !chatRef.trim()) {
      error = 'Pilih worker, satu atau beberapa profil, folder Workspace, dan chat tujuan.';
      return;
    }
    if (transferMode === 'move' && !window.confirm('Move akan menghapus setiap file sumber setelah TDL mengonfirmasi file terkirim. Lanjutkan?')) return;

    submitting = true;
    try {
      const result = await api<Job>('/chat-send/jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey() },
        body: JSON.stringify({
          worker,
          chat_ref: chatRef.trim(),
          folders,
          profiles: selectedProfiles,
          transfer_mode: transferMode,
          move_confirmed: transferMode === 'move'
        })
      });
      window.dispatchEvent(new CustomEvent('tme3:data-mutated', { detail: { path: '/chat-send/jobs' } }));
      notice = `Job Kirim ke Chat diterima${result.id ? ` (#${String(result.id).slice(0, 8)})` : ''}.`;
      folders = [];
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Job Kirim ke Chat gagal dibuat.';
    } finally {
      submitting = false;
    }
  }
</script>

<svelte:head><title>Kirim ke Chat · tme3bot</title></svelte:head>

<div class="space-y-6">
  <header class="flex flex-wrap items-start gap-3">
    <div class="grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><MessageCircle size={23}/></div>
    <div><h1 class="text-2xl font-black tracking-tight">Kirim ke Chat</h1><p class="muted mt-1">Kirim file Workspace sebagai dokumen Telegram, satu file dalam satu waktu.</p></div>
  </header>

  <section class="grid gap-5 xl:grid-cols-[minmax(20rem,.85fr)_minmax(28rem,1.15fr)]">
    <div class="space-y-4 rounded-2xl border border-[var(--line)] bg-[var(--panel-strong)] p-4 sm:p-5">
      <h2 class="text-lg font-extrabold">Tujuan dan pengiriman</h2>
      <label class="block text-sm font-bold">Worker
        <select class="field mt-2" value={worker} onchange={(event) => changeWorker(event.currentTarget.value)} disabled={submitting}>
          <option value="" disabled>Pilih worker</option>
          {#each availableWorkers as item}<option value={item.name}>{item.name}</option>{/each}
        </select>
      </label>

      <fieldset class="space-y-2">
        <legend class="text-sm font-bold">Profil TDL bergiliran</legend>
        {#if profilesLoading}<p class="muted text-sm">Memuat profil worker…</p>
        {:else if loadingError}<p class="text-sm text-rose-700 dark:text-rose-300">{loadingError}</p>
        {:else if !profiles.length}<p class="muted text-sm">Worker belum melaporkan profil lokal.</p>
        {:else}
          <div class="grid gap-2 sm:grid-cols-2">
            {#each profiles as profile (profile.name)}
              <label class="flex items-center gap-2 rounded-xl border border-[var(--line)] p-3 text-sm">
                <input type="checkbox" checked={selectedProfiles.includes(profile.name)} onchange={() => toggleProfile(profile.name)} disabled={submitting}/>
                <span class="font-semibold">{profile.name}</span>
                {#if selectionOrder(profile.name)}<span class="ms-auto rounded bg-violet-100 px-1.5 py-0.5 text-xs font-bold text-violet-800 dark:bg-violet-950 dark:text-violet-200">Urutan {selectionOrder(profile.name)}</span>{/if}
                {#if profile.ready === false}<span class="muted ms-auto text-xs">status informatif</span>{/if}
              </label>
            {/each}
          </div>
          <p class="muted text-xs">Status scan hanya informasi; TDL menentukan akses saat file dikirim.</p>
        {/if}
      </fieldset>

      <label class="block text-sm font-bold">Chat tujuan
        <input class="field mt-2" bind:value={chatRef} maxlength="2048" placeholder="ID, @username, atau tautan t.me" disabled={submitting}/>
      </label>

      <fieldset class="space-y-2">
        <legend class="text-sm font-bold">Perilaku file</legend>
        <label class="flex items-start gap-2 rounded-xl border border-[var(--line)] p-3 text-sm">
          <input type="radio" name="chat-send-mode" value="copy" bind:group={transferMode} disabled={submitting}/>
          <span><b>Copy</b><small class="muted block">File tetap di Workspace.</small></span>
        </label>
        <label class="flex items-start gap-2 rounded-xl border border-[var(--line)] p-3 text-sm">
          <input type="radio" name="chat-send-mode" value="move" bind:group={transferMode} disabled={submitting}/>
          <span><b>Move</b><small class="muted block">Sumber dihapus per file setelah TDL mengonfirmasi `message_id`.</small></span>
        </label>
      </fieldset>

      {#if error}<p role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}
      {#if notice}<p role="status" class="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>{/if}
      <button class="button primary w-full" onclick={submit} disabled={submitting || profilesLoading}>
        <Send size={16} class={submitting ? 'animate-pulse' : ''}/>{submitting ? 'Mengirim job…' : 'Kirim ke Chat'}
      </button>
    </div>

    <div class="space-y-3">
      <div><h2 class="text-lg font-extrabold">Folder Workspace</h2><p class="muted mt-1 text-sm">Pilih satu atau beberapa folder. Semua isi diproses rekursif sebagai dokumen terpisah.</p></div>
      <WorkspaceExplorer bind:selected={folders} worker={worker}/>
    </div>
  </section>

  <JobTable kind="chat_send" title="Riwayat Kirim ke Chat" retryable={true}/>
</div>
