<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';
import WorkspaceExplorer from '../components/WorkspaceExplorer.vue';
import { api } from '../lib/api';

type Worker = { name: string; enabled?: boolean };
type Health = {
  worker: string;
  ready: boolean;
  reason_code: string;
  engine: { ready: boolean; version: string | null };
  hook: { ready: boolean; script_present: boolean; configured: boolean; run_count?: number; last_run_at?: string | null; last_result?: string };
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
  'max-overall-download-limit': '0', 'max-overall-upload-limit': '0',
  'max-concurrent-downloads': '3', 'max-connection-per-server': '5', split: '5',
  'lowest-speed-limit': '102400', 'max-tries': '0', 'retry-wait': '0', timeout: '60',
  'connect-timeout': '10', 'disk-cache': '64M'
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

const workers = ref<Worker[]>([]);
const selectedWorker = ref('');
const selectedFolder = ref('/workspace/aria2');
const folderDraft = ref<string[]>([]);
const health = ref<Health | null>(null);
const iframeGeneration = ref(0);
const loading = ref(true);
const inspecting = ref(false);
const reconnecting = ref(false);
const loadingSettings = ref(false);
const savingSettings = ref(false);
const settings = ref<TransferSettings>({ ...defaultSettings });
const settingsMessage = ref('');
const settingsError = ref('');
const error = ref('');
const recoveryMessage = ref('');
const settingsOpen = ref(false);
const folderPickerOpen = ref(false);
const settingsButton = ref<HTMLButtonElement | null>(null);
const settingsCloseButton = ref<HTMLButtonElement | null>(null);
const folderButton = ref<HTMLButtonElement | null>(null);
const folderCloseButton = ref<HTMLButtonElement | null>(null);
const workerOptions = computed(() => workers.value);
const iframeSrc = computed(() => selectedWorker.value && health.value?.ready ? ariaNgUrl(selectedWorker.value) : '');

let inspectionSequence = 0;

function validWorkspacePath(path: string): boolean {
  return path === '/workspace' || (path.startsWith('/workspace/') && path.slice(1).split('/').every((part) => part && part !== '.' && part !== '..'));
}

function folderStorageKey(worker: string) { return `tme3-aria2-folder:${worker}`; }
function storedFolder(worker: string) {
  const value = localStorage.getItem(folderStorageKey(worker)) || '/workspace/aria2';
  return validWorkspacePath(value) ? value : '/workspace/aria2';
}

function ariaNgUrl(worker: string): string {
  const protocol = window.location.protocol === 'https:' ? 'https' : 'http';
  const port = window.location.port || (protocol === 'https' ? '443' : '80');
  const config = new URLSearchParams({
    protocol,
    host: window.location.hostname,
    port,
    interface: `api/v1/aria2-rpc-${encodeURIComponent(worker)}`
  });
  return `/api/v1/aria2-ui/${encodeURIComponent(worker)}/index.html#!/settings/rpc/set?${config.toString()}`;
}

async function callAria2(worker: string, method: string, params: unknown[] = []) {
  const response = await api<AriaRpcResponse>(`/aria2-rpc-${encodeURIComponent(worker)}`, {
    method: 'POST',
    body: JSON.stringify({ jsonrpc: '2.0', id: `tme3-${method}`, method, params })
  });
  if (response.error) throw new Error(response.error.message || 'Aria2 menolak permintaan.');
  return response.result;
}

async function loadSettings(worker = selectedWorker.value) {
  if (!worker) return;
  loadingSettings.value = true;
  settingsError.value = '';
  settingsMessage.value = '';
  try {
    const result = await callAria2(worker, 'aria2.getGlobalOption') as Record<string, unknown>;
    if (worker !== selectedWorker.value || !result || typeof result !== 'object') return;
    const next = { ...defaultSettings };
    for (const field of settingFields) {
      const value = result[field.key];
      if (typeof value === 'string' || typeof value === 'number') next[field.key] = String(value);
    }
    settings.value = next;
  } catch (cause) {
    if (worker === selectedWorker.value) settingsError.value = cause instanceof Error ? cause.message : 'Pengaturan aria2 gagal dimuat.';
  } finally {
    if (worker === selectedWorker.value) loadingSettings.value = false;
  }
}

async function saveSettings() {
  const target = selectedWorker.value;
  if (!target) return;
  savingSettings.value = true;
  settingsError.value = '';
  settingsMessage.value = '';
  try {
    await callAria2(target, 'aria2.changeGlobalOption', [{ ...settings.value }]);
    if (target === selectedWorker.value) settingsMessage.value = 'Pengaturan tersimpan dan akan dipertahankan setelah worker dimulai ulang.';
  } catch (cause) {
    if (target === selectedWorker.value) settingsError.value = cause instanceof Error ? cause.message : 'Pengaturan aria2 gagal disimpan.';
  } finally {
    if (target === selectedWorker.value) savingSettings.value = false;
  }
}

async function inspect(worker = selectedWorker.value) {
  if (!worker) return;
  const sequence = ++inspectionSequence;
  inspecting.value = true;
  error.value = '';
  recoveryMessage.value = '';
  health.value = null;
  try {
    const result = await api<Health>(`/workers/${encodeURIComponent(worker)}/aria2/health`);
    if (sequence !== inspectionSequence || worker !== selectedWorker.value) return;
    health.value = result;
    if (result.ready) await loadSettings(worker);
  } catch (cause) {
    if (sequence === inspectionSequence && worker === selectedWorker.value) {
      error.value = cause instanceof Error ? cause.message : `Status Aria2 ${worker} gagal diperiksa.`;
    }
  } finally {
    if (sequence === inspectionSequence) inspecting.value = false;
  }
}

async function loadWorkers() {
  loading.value = true;
  error.value = '';
  try {
    const response = await api<{ items?: Worker[] }>('/workers');
    workers.value = response.items || [];
    if (!workers.value.some((worker) => worker.name === selectedWorker.value)) {
      selectedWorker.value = workers.value.find((worker) => worker.enabled !== false)?.name || workers.value[0]?.name || '';
    }
    if (!selectedWorker.value) health.value = null;
    selectedFolder.value = selectedWorker.value ? storedFolder(selectedWorker.value) : '/workspace/aria2';
    if (selectedWorker.value) await inspect(selectedWorker.value);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Daftar worker gagal dimuat.';
  } finally {
    loading.value = false;
  }
}

function changeWorker(event: Event) {
  const target = (event.currentTarget as HTMLSelectElement).value;
  if (target === selectedWorker.value) return;
  selectedWorker.value = target;
  selectedFolder.value = target ? storedFolder(target) : '/workspace/aria2';
  health.value = null;
  settings.value = { ...defaultSettings };
  loadingSettings.value = false;
  savingSettings.value = false;
  settingsError.value = '';
  settingsMessage.value = '';
  recoveryMessage.value = '';
  settingsOpen.value = false;
  folderPickerOpen.value = false;
  void inspect(target);
}

async function openSettings() {
  settingsOpen.value = true;
  await nextTick();
  settingsCloseButton.value?.focus();
}
async function closeSettings() {
  settingsOpen.value = false;
  await nextTick();
  settingsButton.value?.focus();
}
async function openFolderPicker() {
  folderDraft.value = [selectedFolder.value];
  folderPickerOpen.value = true;
  await nextTick();
  folderCloseButton.value?.focus();
}
async function closeFolderPicker(save: boolean) {
  if (save) {
    const chosen = folderDraft.value[0];
    if (chosen && validWorkspacePath(chosen)) {
      selectedFolder.value = chosen;
      if (selectedWorker.value) localStorage.setItem(folderStorageKey(selectedWorker.value), chosen);
    }
  }
  folderPickerOpen.value = false;
  await nextTick();
  folderButton.value?.focus();
}

async function reconnectAriaNg() {
  const target = selectedWorker.value;
  if (!target || reconnecting.value) return;
  reconnecting.value = true;
  recoveryMessage.value = '';
  error.value = '';
  try {
    // The shared API client refreshes an expired browser cookie and CSRF value
    // before retrying. Recreate only the AriaNg iframe after the RPC probe.
    await api('/auth/browser/session');
    await callAria2(target, 'aria2.getVersion');
    if (target === selectedWorker.value) {
      iframeGeneration.value += 1;
      recoveryMessage.value = 'Koneksi AriaNg diperbarui tanpa memuat ulang halaman.';
    }
  } catch (cause) {
    if (target === selectedWorker.value) error.value = cause instanceof Error ? cause.message : 'Koneksi AriaNg belum dapat dipulihkan.';
  } finally {
    reconnecting.value = false;
  }
}

function updateSetting(key: SettingKey, event: Event) {
  settings.value = { ...settings.value, [key]: (event.currentTarget as HTMLInputElement).value };
  settingsMessage.value = '';
  settingsError.value = '';
}

onMounted(() => { void loadWorkers(); });
</script>

<template>
  <main class="page-stack aria2-page">
    <header class="page-heading">
      <div><p class="eyebrow">TRANSFER · ARIA2</p><h1>AriaNg</h1><p class="muted">Antrean unduh terpisah per worker. Pengaturan dan RPC dikelola melalui gateway.</p></div>
      <button class="button button-secondary" type="button" :disabled="loading" @click="loadWorkers"><span class="refresh-icon" :class="{ spinning: loading }">↻</span>{{ loading ? 'Memuat…' : 'Muat ulang worker' }}</button>
    </header>

    <div v-if="error" class="notice notice-error" role="alert">{{ error }}</div>
    <div v-if="recoveryMessage" class="notice" role="status">{{ recoveryMessage }}</div>

    <section v-if="loading && !workers.length" class="panel empty-state" role="status">Memuat worker…</section>
    <section v-else-if="!workers.length" class="panel empty-state">Belum ada worker terdaftar.</section>
    <template v-else>
      <section class="panel aria2-toolbar" aria-label="Kontrol AriaNg">
        <label class="aria2-worker">Worker
          <select class="field" aria-label="Worker" :value="selectedWorker" @change="changeWorker"><option v-for="worker in workerOptions" :key="worker.name" :value="worker.name">{{ worker.name }}{{ worker.enabled === false ? ' (nonaktif)' : '' }}</option></select>
        </label>
        <button ref="settingsButton" class="button button-secondary" type="button" :disabled="!health?.ready || !selectedWorker" aria-haspopup="dialog" @click="openSettings"><span aria-hidden="true">⚙</span> Pengaturan transfer</button>
        <button ref="folderButton" class="button button-secondary aria2-folder-button" type="button" :disabled="!selectedWorker" :aria-label="`Pilih folder unduhan, saat ini ${selectedFolder}`" :title="selectedFolder" aria-haspopup="dialog" @click="openFolderPicker">▣ <span>{{ selectedFolder }}</span></button>
        <button class="button button-secondary" type="button" :disabled="inspecting || !selectedWorker" @click="inspect()"><span class="refresh-icon" :class="{ spinning: inspecting }">↻</span>{{ inspecting ? 'Memeriksa…' : 'Periksa layanan' }}</button>
        <div v-if="health" class="aria2-health" role="status">
          <span class="status-pill" :class="health.ready ? 'status-ready' : 'status-warn'">{{ health.ready ? 'Siap' : health.reason_code || 'Belum siap' }}</span>
          <span class="muted">Engine: {{ health.engine.ready ? `aria2 ${health.engine.version || ''}` : 'tidak tersedia' }}</span>
          <span class="muted">Hook low-speed: {{ health.hook.ready ? 'siap' : 'tidak siap' }}</span>
          <span v-if="health.hook.last_result && health.hook.last_result !== 'never'" class="muted">Hook terakhir: {{ health.hook.last_result }}</span>
        </div>
      </section>

      <section v-if="health?.ready" class="panel aria2-frame-panel">
        <header class="aria2-frame-heading"><div><strong>Tugas {{ selectedWorker }}</strong><small class="muted">Tujuan aktif: {{ selectedFolder }}</small></div><button class="button button-secondary button-small" type="button" :disabled="reconnecting" @click="reconnectAriaNg">{{ reconnecting ? 'Memulihkan…' : 'Sambungkan ulang' }}</button></header>
        <iframe v-if="iframeSrc" :key="`${selectedWorker}:${iframeGeneration}`" :data-connection-generation="iframeGeneration" class="aria2-frame" :src="iframeSrc" :title="`aria2 ${selectedWorker}`" referrerpolicy="no-referrer" data-testid="ariang-frame"></iframe>
        <div v-else class="aria2-frame-empty"><h2>Aria2 belum siap</h2><p class="muted">Perbaiki status engine dan hook worker, lalu periksa layanan kembali.</p></div>
      </section>
      <section v-else-if="!health && !inspecting" class="panel aria2-frame-empty"><p class="muted">Periksa layanan worker untuk membuka AriaNg.</p></section>
    </template>

    <Teleport to="body">
      <Transition name="modal">
        <div v-if="settingsOpen" class="dialog-backdrop" role="presentation" @click.self="closeSettings">
          <section class="panel aria2-dialog settings-dialog" role="dialog" aria-modal="true" aria-labelledby="aria2-settings-title" @keydown.esc.prevent="closeSettings">
            <header class="aria2-dialog-heading"><div><p class="eyebrow">WORKER {{ selectedWorker }}</p><h2 id="aria2-settings-title">Pengaturan transfer</h2><p class="muted">Limit dan retry tersimpan pada worker. RPC dan hook tetap dikelola backend.</p></div><button ref="settingsCloseButton" class="icon-button" type="button" aria-label="Tutup pengaturan" @click="closeSettings">×</button></header>
            <div v-if="settingsError" class="notice notice-error" role="alert">{{ settingsError }}</div>
            <div v-if="settingsMessage" class="notice" role="status">{{ settingsMessage }}</div>
            <div class="settings-grid"><label v-for="field in settingFields" :key="field.key">{{ field.label }}<input class="field" :type="field.text ? 'text' : 'number'" :min="field.text ? undefined : 0" :value="settings[field.key]" :disabled="loadingSettings || savingSettings" @input="updateSetting(field.key, $event)"><small class="muted">{{ field.hint }}</small></label></div>
            <footer class="dialog-actions"><button class="button button-secondary" type="button" :disabled="loadingSettings || savingSettings" @click="loadSettings()">{{ loadingSettings ? 'Memuat…' : 'Muat pengaturan' }}</button><button class="button button-secondary" type="button" @click="closeSettings">Tutup</button><button class="button" type="button" :disabled="loadingSettings || savingSettings" @click="saveSettings">{{ savingSettings ? 'Menyimpan…' : 'Simpan pengaturan' }}</button></footer>
          </section>
        </div>
      </Transition>
      <Transition name="modal">
        <div v-if="folderPickerOpen" class="dialog-backdrop" role="presentation" @click.self="closeFolderPicker(false)">
          <section class="panel aria2-dialog folder-dialog" role="dialog" aria-modal="true" aria-labelledby="aria2-folder-title" @keydown.esc.prevent="closeFolderPicker(false)">
            <header class="aria2-dialog-heading"><div><p class="eyebrow">WORKER {{ selectedWorker }}</p><h2 id="aria2-folder-title">Folder unduhan</h2><p class="muted path-text">{{ folderDraft[0] || selectedFolder }}</p></div><button ref="folderCloseButton" class="icon-button" type="button" aria-label="Tutup pemilih folder" @click="closeFolderPicker(false)">×</button></header>
            <WorkspaceExplorer v-model:selected="folderDraft" single :worker="selectedWorker" />
            <p class="muted folder-hint">Folder ini menjadi tujuan URL dari AriaNg dan dibatasi ke Workspace worker.</p>
            <footer class="dialog-actions"><button class="button button-secondary" type="button" @click="closeFolderPicker(false)">Batal</button><button class="button" type="button" @click="closeFolderPicker(true)">Gunakan folder</button></footer>
          </section>
        </div>
      </Transition>
    </Teleport>
  </main>
</template>

<style scoped>
.aria2-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: .55rem; padding: .7rem; }
.aria2-worker { display: grid; min-width: 12rem; flex: .7; gap: .32rem; color: var(--muted); font-size: .62rem; font-weight: 700; }
.aria2-toolbar .field { width: 100%; min-height: 36px; padding: .45rem .58rem; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-soft); color: var(--ink); font-size: .69rem; }
.aria2-folder-button { max-width: min(30vw, 20rem); min-width: 10rem; }
.aria2-folder-button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aria2-health { display: flex; min-width: min(100%, 100%); flex-wrap: wrap; align-items: center; gap: .45rem .85rem; padding: .4rem .15rem .1rem; font-size: .64rem; }
.aria2-frame-panel { overflow: hidden; }
.aria2-frame-heading { display: flex; min-height: 48px; align-items: center; justify-content: space-between; gap: .6rem; padding: .55rem .75rem; border-bottom: 1px solid var(--line); }
.aria2-frame-heading div { display: grid; gap: .18rem; min-width: 0; font-size: .71rem; }
.aria2-frame-heading small { overflow: hidden; font-size: .6rem; text-overflow: ellipsis; white-space: nowrap; }
.aria2-frame { display: block; width: 100%; height: calc(100vh - 15rem); min-height: 480px; border: 0; background: white; }
.aria2-frame-empty { display: grid; min-height: 480px; place-content: center; gap: .3rem; padding: 2rem; text-align: center; }
.aria2-frame-empty h2 { margin: 0; font-size: .9rem; }
.aria2-dialog { width: min(calc(100vw - 2rem), 940px); max-height: 92vh; overflow: auto; padding: 1rem; box-shadow: var(--shadow); }
.folder-dialog { width: min(calc(100vw - 2rem), 580px); }
.aria2-dialog-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: .8rem; margin-bottom: .8rem; }
.aria2-dialog-heading h2 { margin: .25rem 0 0; font-size: 1rem; }
.aria2-dialog-heading p:not(.eyebrow) { margin: .3rem 0 0; font-size: .67rem; line-height: 1.5; }
.settings-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .7rem; }
.settings-grid label { display: grid; align-content: start; gap: .32rem; font-size: .66rem; font-weight: 700; }
.settings-grid .field { min-height: 36px; padding: .45rem .55rem; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-soft); font-size: .7rem; }
.settings-grid small { font-size: .57rem; font-weight: 400; }
.folder-hint { margin: .6rem 0 0; font-size: .61rem; }
.dialog-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: .45rem; margin-top: .9rem; padding-top: .75rem; border-top: 1px solid var(--line); }
.dialog-backdrop { position: fixed; z-index: 80; inset: 0; display: grid; place-items: center; padding: 1rem; background: rgba(0,0,0,.66); backdrop-filter: blur(4px); }
.modal-enter-active,.modal-leave-active { transition: opacity .16s ease, transform .16s ease; }
.modal-enter-from,.modal-leave-to { transform: translateY(8px); opacity: 0; }
.path-text { overflow-wrap: anywhere; font-family: "DM Mono", monospace; }
.button-small { min-height: 31px; padding: .38rem .58rem; font-size: .62rem; }
@media (max-width: 760px) { .settings-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .aria2-toolbar { align-items: stretch; } .aria2-worker { flex: 1 1 100%; } .aria2-toolbar > button { flex: 1; } .aria2-folder-button { max-width: none; } }
@media (max-width: 480px) { .settings-grid { grid-template-columns: 1fr; } .aria2-frame { min-height: 430px; height: calc(100vh - 14rem); } }
@media (prefers-reduced-motion: reduce) { .modal-enter-active,.modal-leave-active { transition: none; } .modal-enter-from,.modal-leave-to { transform: none; } }
</style>
