<script lang="ts">
  import { onMount } from 'svelte';
  import { Activity, RefreshCw, Save } from '@lucide/svelte';
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
  };
  type TransferSettings = {
    'max-overall-download-limit': string;
    'max-overall-upload-limit': string;
    'max-concurrent-downloads': string;
    'max-connection-per-server': string;
    split: string;
    'lowest-speed-limit': string;
    'max-tries': string;
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
    'lowest-speed-limit': '102400',
    'max-tries': '0',
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
    { key: 'lowest-speed-limit', label: 'Batas minimum hook', hint: '0 menonaktifkan batas; contoh 100K.', text: true },
    { key: 'max-tries', label: 'Jumlah percobaan', hint: '0 tanpa batas; maksimum 100.' },
    { key: 'retry-wait', label: 'Jeda retry (detik)', hint: '0–3600.' },
    { key: 'timeout', label: 'Timeout (detik)', hint: '1–600.' },
    { key: 'connect-timeout', label: 'Timeout koneksi (detik)', hint: '1–60.' },
    { key: 'disk-cache', label: 'Cache disk', hint: 'Maksimum 512M; contoh 64M.', text: true }
  ];

  let workers: Worker[] = $state([]);
  let selectedWorker = $state('');
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
  let error = $state('');

  function folderStorageKey(worker: string) { return `tme3-aria2-folder:${worker}`; }
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
      interface: `/api/v1/aria2-rpc-${worker}`
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
      if (selectedWorker) await inspect(selectedWorker);
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
        await loadSettings(name);
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
    selectedFolders = selectedWorker
      ? [localStorage.getItem(folderStorageKey(selectedWorker)) || '/workspace/aria2']
      : [];
    health = null;
    iframeSrc = '';
    settings = { ...defaultSettings };
    loadingSettings = false;
    savingSettings = false;
    settingsError = '';
    settingsMessage = '';
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

<section class="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
  <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
    <div>
      <p class="muted text-sm font-bold uppercase tracking-[.14em]">Transfer</p>
      <h1 class="mt-1 text-3xl font-black">AriaNg</h1>
      <p class="muted mt-2 max-w-2xl">Pilih worker dan folder Workspace untuk membuka pengelola aria2. RPC dan secret tetap melalui backend.</p>
    </div>
    <button class="button secondary" onclick={loadWorkers} disabled={loading}>
      <RefreshCw size={16} class={loading ? 'animate-spin' : ''} /> Muat ulang
    </button>
  </div>

  {#if error}<div class="alert error mb-4" role="alert">{error}</div>{/if}
  {#if loading}
    <div class="card p-6" role="status">Memuat worker…</div>
  {:else if !workers.length}
    <div class="card p-6">Belum ada worker terdaftar.</div>
  {:else}
    <div class="card mb-5 grid gap-4 p-4 sm:grid-cols-[minmax(14rem,1fr)_auto] sm:items-end">
      <label class="text-sm font-bold">Worker
        <select class="field mt-1" value={selectedWorker} onchange={changeWorker}>
          {#each workers as worker (worker.name)}
            <option value={worker.name}>{worker.name}{worker.enabled ? '' : ' (nonaktif)'}</option>
          {/each}
        </select>
      </label>
      <button class="button secondary" onclick={() => inspect()} disabled={inspecting || !selectedWorker}>
        <RefreshCw size={15} class={inspecting ? 'animate-spin' : ''} />
        {inspecting ? 'Memeriksa…' : 'Periksa layanan'}
      </button>
    </div>

    {#if health}
      <div class="card mb-5 p-4" role="status">
        <div class="flex flex-wrap items-center gap-3">
          <span class={`rounded-full px-3 py-1 text-sm font-bold ${health.ready ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
            {health.ready ? 'Siap' : health.reason_code || 'Belum siap'}
          </span>
          <span class="muted text-sm">Engine: {health.engine.ready ? `aria2 ${health.engine.version || ''}` : 'tidak tersedia'}</span>
          <span class="muted text-sm">Hook low-speed: {health.hook.ready ? 'siap' : 'tidak siap'}</span>
          {#if health.hook.last_result && health.hook.last_result !== 'never'}
            <span class="muted text-sm">Percobaan hook terakhir: {health.hook.last_result}</span>
          {/if}
        </div>
      </div>
    {/if}

    {#if health?.ready}
      <section class="card mb-5 p-4" aria-labelledby="aria2-settings-title">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="aria2-settings-title" class="font-extrabold">Pengaturan transfer</h2>
            <p class="muted mt-1 text-sm">Limit dan retry berlaku untuk worker terpilih, tersimpan di database worker, dan tidak mengubah RPC atau hook.</p>
          </div>
          <div class="flex gap-2">
            <button class="button secondary" onclick={() => loadSettings()} disabled={loadingSettings || savingSettings}>
              <RefreshCw size={15} class={loadingSettings ? 'animate-spin' : ''}/>{loadingSettings ? 'Memuat…' : 'Muat pengaturan'}
            </button>
            <button class="button primary" onclick={saveSettings} disabled={loadingSettings || savingSettings}>
              <Save size={15}/>{savingSettings ? 'Menyimpan…' : 'Simpan pengaturan'}
            </button>
          </div>
        </div>
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
      </section>

      <div class="grid gap-5 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <aside class="card min-w-0 p-4">
          <div class="mb-3">
            <h2 class="font-extrabold">Folder unduhan</h2>
            <p class="muted mt-1 break-all font-mono text-xs">{selectedFolder()}</p>
          </div>
          <WorkspaceExplorer bind:selected={selectedFolders} single worker={selectedWorker}/>
          <p class="muted mt-3 text-xs">Folder ini dipakai untuk URL yang dikirim dari AriaNg. Tujuan dibatasi ke Workspace worker.</p>
        </aside>
        <div class="card min-w-0 overflow-hidden p-0">
          {#if iframeSrc}
            <iframe class="h-[78vh] min-h-[640px] w-full border-0 bg-white" src={iframeSrc} title={`aria2 ${selectedWorker}`} referrerpolicy="no-referrer"></iframe>
          {:else}
            <div class="grid min-h-80 place-items-center p-8 text-center">
              <div><Activity class="mx-auto mb-3 text-violet-500" size={28}/><h2 class="font-extrabold">Aria2 belum siap</h2><p class="muted mt-1 text-sm">Perbaiki status engine dan hook worker, lalu periksa layanan kembali.</p></div>
            </div>
          {/if}
        </div>
      </div>
    {:else if !health && !inspecting}
      <div class="card p-6"><p class="muted">Periksa layanan worker untuk membuka AriaNg.</p></div>
    {/if}
  {/if}
</section>
