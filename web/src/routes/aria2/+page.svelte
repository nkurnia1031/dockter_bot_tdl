<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { Activity, FolderOpen, RefreshCw, Save, Settings2, X } from '@lucide/svelte';
  import { fade, fly } from 'svelte/transition';
  import { api } from '$lib/api';
  import WorkspaceExplorer from '$lib/components/WorkspaceExplorer.svelte';

  type Worker = { name: string; enabled: boolean };
  type Health = {
    worker: string;
    ready: boolean;
    reason_code: string;
    engine: { ready: boolean; version: string | null };
    hook: {
      ready: boolean;
      script_present: boolean;
      configured: boolean;
      run_count?: number;
      last_run_at?: string | null;
      last_result?: string;
    };
    recovery?: { speed_threshold_bytes_per_second: number; external_retry_limit?: number };
  };
  type RecoverySettings = { speed_threshold_bytes_per_second: number };
  type TransferSettings = {
    'max-overall-download-limit': string;
    'max-overall-upload-limit': string;
    'max-concurrent-downloads': string;
    'max-connection-per-server': string;
    split: string;
    'retry-wait': string;
    timeout: string;
    'connect-timeout': string;
    'disk-cache': string;
  };
  type SettingKey = keyof TransferSettings;
  type AriaRpcResponse = { result?: unknown; error?: { message?: string } };

  const defaultSettings: TransferSettings = {
    'max-overall-download-limit': '0',
    'max-overall-upload-limit': '0',
    'max-concurrent-downloads': '3',
    'max-connection-per-server': '5',
    split: '5',
    'retry-wait': '0',
    timeout: '60',
    'connect-timeout': '10',
    'disk-cache': '64M'
  };
  const settingFields: { key: SettingKey; label: string; hint: string; text?: boolean }[] = [
    { key: 'max-overall-download-limit', label: 'Batas kecepatan unduh', hint: '0 tanpa batas; contoh 2M.', text: true },
    { key: 'max-overall-upload-limit', label: 'Batas kecepatan unggah', hint: '0 tanpa batas; contoh 512K.', text: true },
    { key: 'max-concurrent-downloads', label: 'Unduhan bersamaan', hint: '1–20.' },
    { key: 'max-connection-per-server', label: 'Koneksi per server', hint: '1–16.' },
    { key: 'split', label: 'Koneksi per unduhan', hint: '1–32.' },
    { key: 'retry-wait', label: 'Jeda retry (detik)', hint: '0–3600.' },
    { key: 'timeout', label: 'Timeout (detik)', hint: '1–600.' },
    { key: 'connect-timeout', label: 'Timeout koneksi (detik)', hint: '1–60.' },
    { key: 'disk-cache', label: 'Cache disk', hint: 'Maksimum 512M; contoh 64M.', text: true }
  ];

  let workers: Worker[] = $state([]);
  let selectedWorker = $state('');
  let ariaNgZoom = $state(100);
  let selectedFolders = $state<string[]>([]);
  let health = $state<Health | null>(null);
  let iframeSrc = $state('');
  let loading = $state(true);
  let inspecting = $state(false);
  let inspectionSequence = 0;
  let settings = $state<TransferSettings>({ ...defaultSettings });
  let loadingSettings = $state(false);
  let savingSettings = $state(false);
  let settingsMessage = $state('');
  let settingsError = $state('');
  let recoveryThreshold = $state(100000);
  let loadingRecoverySettings = $state(false);
  let savingRecoverySettings = $state(false);
  let recoverySettingsMessage = $state('');
  let recoverySettingsError = $state('');
  let settingsOpen = $state(false);
  let folderPickerOpen = $state(false);
  let folderSelectionBeforeOpen: string[] = [];
  let settingsButton: HTMLButtonElement | undefined = $state();
  let settingsCloseButton: HTMLButtonElement | undefined = $state();
  let error = $state('');

  function modalDuration(duration: number) {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      ? 1
      : duration;
  }

  function presentModal(node: HTMLDialogElement) {
    if (typeof node.showModal === 'function') node.showModal();
    else node.setAttribute('open', '');
    return {
      destroy() {
        if (typeof node.close === 'function' && node.open) node.close();
        else node.removeAttribute('open');
      }
    };
  }

  function folderStorageKey(worker: string) { return `tme3-aria2-folder:${worker}`; }
  function zoomStorageKey(worker: string) { return `tme3-aria2-zoom:${worker}`; }
  function readZoom(worker: string) {
    if (typeof window === 'undefined') return 100;
    const stored = Number(localStorage.getItem(zoomStorageKey(worker)));
    if (!Number.isFinite(stored) || stored < 80 || stored > 150) return 100;
    return 80 + Math.round((stored - 80) / 10) * 10;
  }
  function setZoom(value: number) {
    if (!selectedWorker) return;
    ariaNgZoom = Math.max(80, Math.min(150, Math.round(value / 10) * 10));
    localStorage.setItem(zoomStorageKey(selectedWorker), String(ariaNgZoom));
  }
  function changeZoom(amount: number) { setZoom(ariaNgZoom + amount); }
  function resetZoom() { setZoom(100); }
  function selectedFolder(worker = selectedWorker) {
    return selectedFolders[0] || (typeof window !== 'undefined' ? localStorage.getItem(folderStorageKey(worker)) : '') || '/workspace/aria2';
  }

  function makeAriaNgUrl(worker: string) {
    const protocol = window.location.protocol === 'https:' ? 'https' : 'http';
    const port = window.location.port || (protocol === 'https' ? '443' : '80');
    const config = new URLSearchParams({
      protocol,
      host: window.location.hostname,
      port,
      interface: `api/v1/aria2-rpc-${worker}`
    });
    return `/api/v1/aria2-ui/${encodeURIComponent(worker)}/index.html#!/settings/rpc/set?${config.toString()}`;
  }

  async function callAria2(worker: string, method: string, params: unknown[] = []) {
    const result = await api<AriaRpcResponse>(`/aria2-rpc-${encodeURIComponent(worker)}`, {
      method: 'POST',
      body: JSON.stringify({ jsonrpc: '2.0', id: `tme3-${method}`, method, params })
    });
    if (result.error) throw new Error(result.error.message || 'Aria2 menolak permintaan.');
    return result.result;
  }

  async function loadSettings(worker = selectedWorker) {
    if (!worker) return;
    loadingSettings = true;
    settingsError = '';
    settingsMessage = '';
    try {
      const result = await callAria2(worker, 'aria2.getGlobalOption') as Record<string, unknown>;
      if (worker !== selectedWorker || !result || typeof result !== 'object') return;
      const next = { ...defaultSettings };
      for (const field of settingFields) {
        const value = result[field.key];
        if (typeof value === 'string' || typeof value === 'number') next[field.key] = String(value);
      }
      settings = next;
    } catch (cause) {
      if (worker === selectedWorker) settingsError = cause instanceof Error ? cause.message : 'Pengaturan aria2 gagal dimuat.';
    } finally {
      if (worker === selectedWorker) loadingSettings = false;
    }
  }

  async function loadRecoverySettings(worker = selectedWorker) {
    if (!worker) return;
    loadingRecoverySettings = true;
    recoverySettingsError = '';
    recoverySettingsMessage = '';
    try {
      const result = await api<RecoverySettings>(`/workers/${encodeURIComponent(worker)}/aria2/recovery-settings`);
      if (worker === selectedWorker) recoveryThreshold = result.speed_threshold_bytes_per_second;
    } catch (cause) {
      if (worker === selectedWorker) recoverySettingsError = cause instanceof Error ? cause.message : 'Ambang pemulihan gagal dimuat.';
    } finally {
      if (worker === selectedWorker) loadingRecoverySettings = false;
    }
  }

  async function saveRecoverySettings() {
    const worker = selectedWorker;
    if (!worker || !Number.isSafeInteger(recoveryThreshold) || recoveryThreshold < 0 || recoveryThreshold > 1_073_741_824) {
      recoverySettingsError = 'Ambang harus berupa bilangan bulat 0–1.073.741.824 B/s.';
      return;
    }
    savingRecoverySettings = true;
    recoverySettingsError = '';
    recoverySettingsMessage = '';
    try {
      const result = await api<RecoverySettings>(`/workers/${encodeURIComponent(worker)}/aria2/recovery-settings`, {
        method: 'PUT',
        body: JSON.stringify({ speed_threshold_bytes_per_second: recoveryThreshold })
      });
      if (worker === selectedWorker) {
        recoveryThreshold = result.speed_threshold_bytes_per_second;
        if (health?.worker === worker) {
          health = {
            ...health,
            recovery: { ...health.recovery, speed_threshold_bytes_per_second: recoveryThreshold }
          };
        }
        recoverySettingsMessage = 'Ambang diperbarui langsung untuk unduhan worker ini.';
      }
    } catch (cause) {
      if (worker === selectedWorker) recoverySettingsError = cause instanceof Error ? cause.message : 'Ambang pemulihan gagal disimpan.';
    } finally {
      if (worker === selectedWorker) savingRecoverySettings = false;
    }
  }

  function updateSetting(key: SettingKey, event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    settings = { ...settings, [key]: input.value };
    settingsMessage = '';
    settingsError = '';
  }

  async function saveSettings() {
    const worker = selectedWorker;
    if (!worker) return;
    savingSettings = true;
    settingsError = '';
    settingsMessage = '';
    try {
      await callAria2(worker, 'aria2.changeGlobalOption', [{ ...settings }]);
      if (worker === selectedWorker) {
        settingsMessage = 'Pengaturan tersimpan dan akan dipertahankan setelah worker dimulai ulang.';
      }
    } catch (cause) {
      if (worker === selectedWorker) {
        settingsError = cause instanceof Error ? cause.message : 'Pengaturan aria2 gagal disimpan.';
      }
    } finally {
      if (worker === selectedWorker) savingSettings = false;
    }
  }

  async function openSettings() {
    settingsOpen = true;
    await tick();
    settingsCloseButton?.focus();
  }

  function closeSettings() {
    settingsOpen = false;
    settingsButton?.focus();
  }

  function openFolderPicker() {
    folderSelectionBeforeOpen = [...selectedFolders];
    folderPickerOpen = true;
  }

  function closeFolderPicker(save: boolean) {
    if (!save) selectedFolders = folderSelectionBeforeOpen;
    folderPickerOpen = false;
  }

  function handleModalKeydown(event: KeyboardEvent, close: () => void) {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  }

  async function loadWorkers() {
    loading = true;
    error = '';
    try {
      const response = await api<{ items: Worker[] }>('/workers');
      workers = response.items || [];
      if (!selectedWorker || !workers.some((item) => item.name === selectedWorker)) {
        const initial = workers.find((item) => item.enabled) || workers[0];
        selectedWorker = initial?.name || '';
        selectedFolders = selectedWorker
          ? [localStorage.getItem(folderStorageKey(selectedWorker)) || '/workspace/aria2']
          : [];
      }
      if (selectedWorker) {
        ariaNgZoom = readZoom(selectedWorker);
        await inspect(selectedWorker);
      }
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Daftar worker gagal dimuat.';
    } finally {
      loading = false;
    }
  }

  async function inspect(name = selectedWorker) {
    if (!name) return;
    const sequence = ++inspectionSequence;
    inspecting = true;
    error = '';
    iframeSrc = '';
    try {
      const result = await api<Health>(`/workers/${encodeURIComponent(name)}/aria2/health`);
      if (name !== selectedWorker) return;
      health = result;
      if (result.ready) {
        iframeSrc = makeAriaNgUrl(name);
        await Promise.all([loadSettings(name), loadRecoverySettings(name)]);
      }
    } catch (cause) {
      if (name === selectedWorker) {
        health = null;
        error = cause instanceof Error ? cause.message : `Status Aria2 ${name} gagal diperiksa.`;
      }
    } finally {
      if (sequence === inspectionSequence) inspecting = false;
    }
  }

  function changeWorker(event: Event) {
    selectedWorker = (event.currentTarget as HTMLSelectElement).value;
    ariaNgZoom = readZoom(selectedWorker);
    selectedFolders = selectedWorker
      ? [localStorage.getItem(folderStorageKey(selectedWorker)) || '/workspace/aria2']
      : [];
    health = null;
    iframeSrc = '';
    settings = { ...defaultSettings };
    loadingSettings = false;
    savingSettings = false;
    settingsError = '';
    loadingRecoverySettings = false;
    savingRecoverySettings = false;
    recoveryThreshold = 100000;
    recoverySettingsMessage = '';
    recoverySettingsError = '';
    settingsMessage = '';
    settingsOpen = false;
    void inspect(selectedWorker);
  }

  $effect(() => {
    if (typeof window !== 'undefined' && selectedWorker && selectedFolders[0]) {
      localStorage.setItem(folderStorageKey(selectedWorker), selectedFolders[0]);
    }
  });

  onMount(() => { void loadWorkers(); });
</script>

<svelte:head>
  <title>AriaNg · tme3bot</title>
  <meta name="description" content="Aria2 download manager per worker." />
</svelte:head>

<section class="mx-auto max-w-[1600px] p-3 sm:p-4">
  <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-3">
      <Activity class="hidden text-violet-500 sm:block" size={24}/>
      <div>
        <p class="muted text-xs font-bold uppercase tracking-[.14em]">Transfer</p>
        <h1 class="mt-0.5 text-2xl font-black">AriaNg</h1>
      </div>
    </div>
    <button class="button secondary" onclick={loadWorkers} disabled={loading}>
      <RefreshCw size={16} class={loading ? 'animate-spin' : ''} /> Muat ulang
    </button>
  </div>

  {#if error}<div class="alert error mb-3" role="alert">{error}</div>{/if}
  {#if loading}
    <div class="card p-6" role="status">Memuat worker…</div>
  {:else if !workers.length}
    <div class="card p-6">Belum ada worker terdaftar.</div>
  {:else}
    <div class="card mb-3 flex flex-wrap items-center gap-2 p-3">
      <label class="min-w-52 flex-1 text-sm font-bold sm:max-w-xs">Worker
        <select class="field mt-1" value={selectedWorker} onchange={changeWorker}>
          {#each workers as worker (worker.name)}
            <option value={worker.name}>{worker.name}{worker.enabled ? '' : ' (nonaktif)'}</option>
          {/each}
        </select>
      </label>
      <button bind:this={settingsButton} class="button secondary" onclick={openSettings} disabled={!health?.ready || !selectedWorker} aria-haspopup="dialog">
        <Settings2 size={16}/> Pengaturan transfer
      </button>
      <button class="button secondary min-w-0" onclick={openFolderPicker} disabled={!selectedWorker} aria-haspopup="dialog" aria-label={`Pilih folder unduhan, saat ini ${selectedFolder()}`} title={selectedFolder()}>
        <FolderOpen size={16}/><span class="max-w-40 truncate">{selectedFolder()}</span>
      </button>
      <button class="button secondary" onclick={() => inspect()} disabled={inspecting || !selectedWorker}>
        <RefreshCw size={15} class={inspecting ? 'animate-spin' : ''} />
        {inspecting ? 'Memeriksa…' : 'Periksa layanan'}
      </button>
      {#if health}
        <div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 px-1 text-xs" role="status">
          <span class={`rounded-full px-3 py-1 text-sm font-bold ${health.ready ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
            {health.ready ? 'Siap' : health.reason_code || 'Belum siap'}
          </span>
          <span class="muted text-sm">Engine: {health.engine.ready ? `aria2 ${health.engine.version || ''}` : 'tidak tersedia'}</span>
          <span class="muted text-sm">Hook pemantau: {health.hook.ready ? 'siap' : 'tidak siap'}</span>
          {#if health.recovery}<span class="muted text-sm">Ambang: {health.recovery.speed_threshold_bytes_per_second.toLocaleString()} B/s</span>{/if}
          {#if health.hook.last_result && health.hook.last_result !== 'never'}
            <span class="muted text-sm">Pemanggilan hook terakhir: {health.hook.last_result}</span>
          {/if}
        </div>
      {/if}
    </div>

    {#if health?.ready}
      <div class="card min-w-0 overflow-auto p-0">
        {#if iframeSrc}
          <div class="flex items-center justify-end gap-1 border-b border-[var(--line)] bg-[var(--panel)] px-3 py-2" role="group" aria-label="Zoom AriaNg">
            <span class="muted mr-2 text-xs">Zoom</span>
            <button class="button secondary !px-2 !py-1" onclick={() => changeZoom(-10)} disabled={ariaNgZoom <= 80} aria-label="Perkecil tampilan AriaNg" title="Perkecil tampilan">−</button>
            <output class="min-w-12 text-center text-sm font-semibold tabular-nums" aria-live="polite">{ariaNgZoom}%</output>
            <button class="button secondary !px-2 !py-1" onclick={resetZoom} aria-label="Reset zoom AriaNg" title="Reset zoom">Reset</button>
            <button class="button secondary !px-2 !py-1" onclick={() => changeZoom(10)} disabled={ariaNgZoom >= 150} aria-label="Perbesar tampilan AriaNg" title="Perbesar tampilan">+</button>
          </div>
          <iframe class="h-[calc(100vh-18rem)] min-h-[460px] w-full border-0 bg-white sm:min-h-[500px]" style={`zoom: ${ariaNgZoom / 100};`} src={iframeSrc} title={`aria2 ${selectedWorker}`} referrerpolicy="no-referrer"></iframe>
        {:else}
          <div class="grid min-h-[480px] place-items-center p-8 text-center">
            <div><Activity class="mx-auto mb-3 text-violet-500" size={28}/><h2 class="font-extrabold">Aria2 belum siap</h2><p class="muted mt-1 text-sm">Perbaiki status engine dan hook worker, lalu periksa layanan kembali.</p></div>
          </div>
        {/if}
      </div>
    {:else if !health && !inspecting}
      <div class="card grid min-h-[480px] place-items-center p-6 text-center"><p class="muted">Periksa layanan worker untuk membuka AriaNg.</p></div>
    {/if}
  {/if}
</section>

{#if settingsOpen}
  <dialog
    use:presentModal
    transition:fade={{ duration: modalDuration(220) }}
    class="fixed inset-0 z-[100] m-0 flex h-full w-full max-w-none items-center justify-center overflow-y-auto border-0 bg-black/55 p-3 sm:p-5"
    aria-modal="true"
    aria-labelledby="aria2-settings-title"
    onkeydown={(event) => handleModalKeydown(event, closeSettings)}
    onclick={(event) => { if (event.target === event.currentTarget) closeSettings(); }}
  >
    <section transition:fly={{ y: 12, duration: modalDuration(220) }} class="max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4 shadow-2xl sm:p-6">
      <header class="mb-4 flex items-start justify-between gap-3">
        <div>
          <p class="eyebrow">WORKER {selectedWorker}</p>
          <h2 id="aria2-settings-title" class="mt-1 text-xl font-extrabold">Pengaturan transfer</h2>
          <p class="muted mt-1 text-sm">Pengaturan transfer aria2 dan ambang pengendali disimpan terpisah di database worker.</p>
        </div>
        <button bind:this={settingsCloseButton} class="button secondary !p-2" onclick={closeSettings} aria-label="Tutup pengaturan"><X size={17}/></button>
      </header>
      {#if settingsError}<div class="alert error mb-3" role="alert">{settingsError}</div>{/if}
      {#if settingsMessage}<div class="alert success mb-3" role="status">{settingsMessage}</div>{/if}
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {#each settingFields as field (field.key)}
          <label class="text-sm font-bold">{field.label}
            <input class="field mt-1" type={field.text ? 'text' : 'number'} min={field.text ? undefined : 0} value={settings[field.key]} oninput={(event) => updateSetting(field.key, event)} disabled={loadingSettings || savingSettings} />
            <span class="muted mt-1 block text-xs font-normal">{field.hint}</span>
          </label>
        {/each}
      </div>
      <section class="mt-5 rounded-xl border border-[var(--line)] bg-[var(--surface)] p-4" aria-labelledby="aria2-recovery-title">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="aria2-recovery-title" class="font-extrabold">Pemulihan kecepatan</h3>
            <p class="muted mt-1 max-w-2xl text-xs">Ambang rata-rata unduhan setelah pemanasan 60 detik. Pemantau memberi 10 detik pengukuran, lalu pause 3 detik dan resume. Nilai 0 menonaktifkan pemulihan kecepatan; retry error tetap aktif.</p>
          </div>
          <label class="w-full text-sm font-bold sm:max-w-xs">Ambang (B/s)
            <input class="field mt-1" type="number" min="0" max="1073741824" step="1" bind:value={recoveryThreshold} disabled={loadingRecoverySettings || savingRecoverySettings} />
            <span class="muted mt-1 block text-xs font-normal">Default 100.000 B/s · retry error eksternal maksimal 10 kali; retry bawaan aria2 tetap tanpa batas.</span>
          </label>
        </div>
        {#if recoverySettingsError}<div class="alert error mt-3" role="alert">{recoverySettingsError}</div>{/if}
        {#if recoverySettingsMessage}<div class="alert success mt-3" role="status">{recoverySettingsMessage}</div>{/if}
        <div class="mt-3 flex flex-wrap justify-end gap-2">
          <button class="button secondary" onclick={() => loadRecoverySettings()} disabled={loadingRecoverySettings || savingRecoverySettings}>
            <RefreshCw size={15} class={loadingRecoverySettings ? 'animate-spin' : ''}/>{loadingRecoverySettings ? 'Memuat…' : 'Muat ambang'}
          </button>
          <button class="button primary" onclick={saveRecoverySettings} disabled={loadingRecoverySettings || savingRecoverySettings}>
            <Save size={15}/>{savingRecoverySettings ? 'Menyimpan…' : 'Simpan ambang'}
          </button>
        </div>
      </section>
      <footer class="mt-5 flex flex-wrap justify-between gap-2 border-t border-[var(--line)] pt-4">
        <button class="button secondary" onclick={() => loadSettings()} disabled={loadingSettings || savingSettings}>
          <RefreshCw size={15} class={loadingSettings ? 'animate-spin' : ''}/>{loadingSettings ? 'Memuat…' : 'Muat pengaturan'}
        </button>
        <div class="flex gap-2">
          <button class="button secondary" onclick={closeSettings}>Tutup</button>
          <button class="button primary" onclick={saveSettings} disabled={loadingSettings || savingSettings}>
            <Save size={15}/>{savingSettings ? 'Menyimpan…' : 'Simpan pengaturan'}
          </button>
        </div>
      </footer>
    </section>
  </dialog>
{/if}

{#if folderPickerOpen}
  <dialog
    use:presentModal
    transition:fade={{ duration: modalDuration(220) }}
    class="fixed inset-0 z-[100] m-0 flex h-full w-full max-w-none items-center justify-center overflow-y-auto border-0 bg-black/55 p-3 sm:p-5"
    aria-modal="true"
    aria-labelledby="aria2-folder-title"
    onkeydown={(event) => handleModalKeydown(event, () => closeFolderPicker(false))}
    onclick={(event) => { if (event.target === event.currentTarget) closeFolderPicker(false); }}
  >
    <section transition:fly={{ y: 12, duration: modalDuration(220) }} class="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-4 shadow-2xl sm:p-5">
      <header class="mb-3 flex items-start justify-between gap-3">
        <div><p class="eyebrow">WORKER {selectedWorker}</p><h2 id="aria2-folder-title" class="mt-1 text-lg font-extrabold">Folder unduhan</h2><p class="muted mt-1 break-all font-mono text-xs">{selectedFolder()}</p></div>
        <button class="button secondary !p-2" onclick={() => closeFolderPicker(false)} aria-label="Tutup pemilih folder"><X size={17}/></button>
      </header>
      <WorkspaceExplorer bind:selected={selectedFolders} single worker={selectedWorker}/>
      <p class="muted mt-3 text-xs">Folder ini menjadi tujuan URL dari AriaNg dan dibatasi ke Workspace worker.</p>
      <footer class="mt-4 flex justify-end gap-2">
        <button class="button secondary" onclick={() => closeFolderPicker(false)}>Batal</button>
        <button class="button primary" onclick={() => closeFolderPicker(true)}>Gunakan folder</button>
      </footer>
    </section>
  </dialog>
{/if}
