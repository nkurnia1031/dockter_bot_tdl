<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, remove } from '../lib/api';
import { session, type ProfileOption } from '../session';
import { normalizeTdlChatRef } from '../../../src/lib/chatRef';
import { formatBytes, formatDate } from '../../../src/lib/presentation';
import { normalizeRuntimeReadiness, profileOptionLabel, runtimeReadinessFor } from '../../../src/lib/profile-catalog';

type Artifact = {
  id: string;
  filename: string;
  profile?: string;
  worker?: string;
  status: string;
  chat_ref?: string;
  label?: string;
  message_count?: number;
  media_count?: number;
  photo_count?: number;
  video_count?: number;
  json_bytes?: number;
  expected_media_bytes?: number;
  actual_downloaded_bytes?: number;
  error?: string;
  created_at?: string;
  completed_at?: string;
  archived_at?: string;
  available?: boolean | number;
  missing_at?: string;
};
type Tab = 'pending' | 'processing' | 'history' | 'archived';
type ArtifactQuery = { archived: boolean; status?: string; available?: boolean };
type JobRef = { id: string };

const tabs: { key: Tab; label: string }[] = [
  { key: 'pending', label: 'Pending' },
  { key: 'processing', label: 'Sedang diproses' },
  { key: 'history', label: 'History' },
  { key: 'archived', label: 'Archived' }
];
const terminal = ['downloaded', 'failed', 'deleted'];
const activeTab = ref<Tab>('pending');
const artifacts = ref<Artifact[]>([]);
const selected = ref<string[]>([]);
const pending = ref(false);
const catalogLoading = ref(true);
const syncing = ref(false);
const catalogRefreshing = ref(false);
const message = ref('');
const error = ref('');
const profileFilter = ref('');
const workerFilter = ref('');
const labelFilter = ref('');
const chatRefFilter = ref('');
const confirmAction = ref<'delete' | 'purge' | null>(null);
const readiness = ref(normalizeRuntimeReadiness(null));
const lastUpdated = ref<Date | null>(null);
let generation = 0;
let disposed = false;
const onJobFinished = () => { void refreshProfileContext(); };

const profileOptions = computed(() => session.profileCatalog);
const workerOptions = computed(() => [...new Set([
  ...session.workers.map((item) => item.name),
  ...artifacts.value.map((item) => item.worker || 'local')
])].sort());
const filtered = computed(() => artifacts.value.filter((item) => {
  const label = (item.label || '').toLocaleLowerCase();
  const normalizedChat = normalizeTdlChatRef(item.chat_ref || '');
  const chat = (normalizedChat || (item.chat_ref || '').replace(/^@+/, '')).toLocaleLowerCase();
  const normalizedFilter = normalizeTdlChatRef(chatRefFilter.value)
    || chatRefFilter.value.trim().replace(/^@+/, '').toLocaleLowerCase();
  return (!profileFilter.value || item.profile === profileFilter.value)
    && (!workerFilter.value || (item.worker || 'local') === workerFilter.value)
    && (!labelFilter.value.trim() || label.includes(labelFilter.value.trim().toLocaleLowerCase()))
    && (!chatRefFilter.value.trim() || chat.includes(normalizedFilter));
}));
const visible = computed(() => filtered.value.filter((item) => {
  const available = item.available ?? true;
  if (activeTab.value === 'pending') return Boolean(available) && ['pending', 'failed'].includes(item.status);
  if (activeTab.value === 'processing') return Boolean(available) && item.status === 'processing';
  if (activeTab.value === 'history') return !item.archived_at && (terminal.includes(item.status) || available === false || available === 0);
  return Boolean(item.archived_at) || item.status === 'archived';
}));
const selectable = computed(() => visible.value.filter((item) =>
  Boolean(item.available ?? true) && ['pending', 'failed'].includes(item.status)
));
const selectedItems = computed(() => artifacts.value.filter((item) => selected.value.includes(item.id)));
const allVisibleSelected = computed(() => selectable.value.length > 0 && selectable.value.every((item) => selected.value.includes(item.id)));

function queriesForTab(tab: Tab): ArtifactQuery[] {
  if (tab === 'pending') return [{ archived: false, status: 'pending' }, { archived: false, status: 'failed' }];
  if (tab === 'processing') return [{ archived: false, status: 'processing' }];
  if (tab === 'history') return [
    { archived: false, status: 'downloaded' },
    { archived: false, status: 'failed' },
    { archived: false, status: 'deleted' },
    { archived: false, available: false }
  ];
  return [{ archived: true }];
}

function queryFor(query: ArtifactQuery): string {
  const params = new URLSearchParams({ scope: 'global', limit: '200', offset: '0', archived: String(query.archived) });
  if (query.status) params.set('status', query.status);
  if (query.available !== undefined) params.set('available', String(query.available));
  if (profileFilter.value) params.set('profile', profileFilter.value);
  if (workerFilter.value) params.set('worker', workerFilter.value);
  if (labelFilter.value.trim()) params.set('label', labelFilter.value.trim());
  if (chatRefFilter.value.trim()) params.set('chat_ref', chatRefFilter.value.trim());
  return `/downloads/artifacts?${params.toString()}`;
}

async function load(request = generation) {
  catalogLoading.value = true;
  try {
    const pages = await Promise.all(queriesForTab(activeTab.value).map(async (query) =>
      api<{ items?: Artifact[]; total?: number }>(queryFor(query))
    ));
    if (disposed || request !== generation) return;
    const byId = new Map<string, Artifact>();
    for (const page of pages) for (const item of page.items || []) byId.set(item.id, item);
    artifacts.value = [...byId.values()].sort((left, right) => {
      const leftCreated = Date.parse(left.created_at || '') || 0;
      const rightCreated = Date.parse(right.created_at || '') || 0;
      return rightCreated - leftCreated || right.id.localeCompare(left.id);
    });
    selected.value = selected.value.filter((id) => artifacts.value.some((item) => item.id === id));
    lastUpdated.value = new Date();
  } finally {
    if (!disposed && request === generation) catalogLoading.value = false;
  }
}

async function refreshProfileContext() {
  try {
    const result = await api<{ profiles?: ProfileOption[]; runtime_readiness?: unknown }>('/profiles/local');
    if (!disposed) {
      if (Array.isArray(result.profiles)) session.profileCatalog = result.profiles;
      readiness.value = normalizeRuntimeReadiness(result.runtime_readiness);
    }
  } catch {
    // The stored readiness is informational; it never gates download actions.
  }
}

async function refreshCatalog() {
  if (catalogRefreshing.value || pending.value) return;
  catalogRefreshing.value = true;
  message.value = '';
  error.value = '';
  const request = ++generation;
  try {
    await Promise.all([load(request), refreshProfileContext()]);
    if (request === generation) message.value = 'Katalog unduhan dan status profil diperbarui.';
  } catch (cause) {
    if (request === generation) error.value = cause instanceof Error ? cause.message : 'Katalog unduhan gagal diperbarui.';
  } finally {
    catalogRefreshing.value = false;
  }
}

async function changeFilter() {
  const request = ++generation;
  selected.value = [];
  syncing.value = false;
  error.value = '';
  pending.value = true;
  try { await load(request); }
  catch (cause) { if (request === generation) error.value = cause instanceof Error ? cause.message : 'Artifact gagal dimuat.'; }
  finally { if (request === generation) pending.value = false; }
}

function changeTab(tab: Tab) {
  if (activeTab.value === tab) return;
  activeTab.value = tab;
  void changeFilter();
}

function toggleAll() {
  selected.value = allVisibleSelected.value
    ? selected.value.filter((id) => !selectable.value.some((item) => item.id === id))
    : [...new Set([...selected.value, ...selectable.value.map((item) => item.id)])];
}

function toggle(item: Artifact) {
  if (!(item.available ?? true) || !['pending', 'failed'].includes(item.status)) return;
  selected.value = selected.value.includes(item.id)
    ? selected.value.filter((id) => id !== item.id)
    : [...selected.value, item.id];
}

async function start(ids: string[], priority: 'normal' | 'next' = 'normal') {
  if (!ids.length) return;
  pending.value = true;
  error.value = '';
  try {
    const result = await post<{ groups?: Array<{ profile: string; worker: string; job_id: string }> }>('/downloads/batch', { artifact_ids: ids, priority });
    selected.value = [];
    message.value = `${ids.length} artifact dikelompokkan otomatis berdasarkan profile-worker dan masuk antrean.${result.groups?.length ? ` ${result.groups.length} job dibuat.` : ''}`;
    await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Download gagal dibuat.'; }
  finally { pending.value = false; }
}

async function clearFailed() {
  pending.value = true;
  error.value = '';
  try {
    const result = await post<{ jobs?: unknown[] }>('/downloads/clear-failed?scope=global');
    message.value = `Artifact failed dibersihkan pada ${result.jobs?.length || 0} origin.`;
    await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Clear failed gagal.'; }
  finally { pending.value = false; }
}

function wait(milliseconds: number) { return new Promise((resolve) => setTimeout(resolve, milliseconds)); }
async function reconcile() {
  const request = ++generation;
  syncing.value = true;
  pending.value = true;
  selected.value = [];
  message.value = 'Menyinkronkan inventory seluruh profile-worker…';
  error.value = '';
  try {
    const params = new URLSearchParams({ scope: 'global' });
    if (profileFilter.value) params.set('profile', profileFilter.value);
    if (workerFilter.value) params.set('worker', workerFilter.value);
    const result = await post<{ jobs?: JobRef[]; id?: string }>(`/downloads/artifacts/reconcile?${params}`);
    const jobs = result.jobs || (result.id ? [{ id: result.id }] : []);
    while (jobs.length && request === generation && !disposed) {
      const states = await Promise.all(jobs.map((job) => api<{ status: string; error?: { message?: string } }>(`/jobs/${encodeURIComponent(job.id)}`)));
      if (states.every((job) => ['succeeded', 'failed', 'cancelled'].includes(job.status))) {
        const failed = states.find((job) => job.status !== 'succeeded');
        if (failed) throw new Error(failed.error?.message || 'Inventory worker gagal.');
        break;
      }
      await wait(800);
    }
    await load(request);
    if (request === generation) message.value = 'Inventory berhasil disinkronkan.';
  } catch (cause) { if (request === generation) error.value = cause instanceof Error ? cause.message : 'Inventory gagal disinkronkan.'; }
  finally {
    if (request === generation) { syncing.value = false; pending.value = false; }
  }
}

async function archive(item: Artifact) {
  try { await post(`/downloads/artifacts/${encodeURIComponent(item.id)}/archive`); message.value = `${item.filename} diarsipkan.`; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Artifact gagal diarsipkan.'; }
}
async function restore(item: Artifact) {
  try { await post(`/downloads/artifacts/${encodeURIComponent(item.id)}/restore`); message.value = `${item.filename} dipulihkan.`; await load(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Artifact gagal dipulihkan.'; }
}

async function confirmDestructive() {
  const action = confirmAction.value;
  if (!action) return;
  pending.value = true;
  error.value = '';
  try {
    if (action === 'delete') {
      await post('/downloads/artifacts/actions/delete', { artifact_ids: [...selected.value] });
      message.value = `Permintaan hapus dikirim untuk ${selected.value.length} artifact.`;
    } else {
      for (const item of selectedItems.value) await remove(`/downloads/artifacts/${encodeURIComponent(item.id)}`);
      message.value = `Metadata ${selectedItems.value.length} artifact dihapus permanen.`;
    }
    selected.value = [];
    confirmAction.value = null;
    await load();
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Aksi artifact gagal.'; }
  finally { pending.value = false; }
}

function readinessFor(item: Artifact) {
  return runtimeReadinessFor(readiness.value, item.profile || null, item.worker || 'local', 'download');
}
function statusClass(status: string) {
  if (['downloaded', 'succeeded'].includes(status)) return 'status-ready';
  if (['failed', 'deleted'].includes(status)) return 'status-failed';
  if (['processing', 'running'].includes(status)) return 'status-warn';
  return 'status-neutral';
}

onMounted(() => {
  disposed = false;
  void refreshProfileContext();
  window.addEventListener('tme3:job-finished', onJobFinished);
  void load().catch((cause) => { error.value = cause instanceof Error ? cause.message : 'Artifact gagal dimuat.'; });
});
onUnmounted(() => {
  disposed = true;
  generation += 1;
  window.removeEventListener('tme3:job-finished', onJobFinished);
});
</script>

<template>
  <main class="page-stack downloads-page">
    <header class="page-heading">
      <div><p class="eyebrow">TRANSFER · CATALOG</p><h1>Download manager</h1><p class="muted">Artifact lintas profil dan worker. Origin tersimpan menentukan worker untuk setiap unduhan.</p></div>
      <div class="heading-actions">
        <span v-if="lastUpdated" class="last-updated muted">Diperbarui {{ lastUpdated.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }) }}</span>
        <button class="button button-secondary" type="button" aria-label="Refresh katalog unduhan" :disabled="catalogRefreshing || pending || syncing" @click="refreshCatalog"><span class="refresh-icon" :class="{ spinning: catalogRefreshing }">↻</span>Refresh katalog</button>
        <button class="button button-secondary" type="button" :disabled="pending || syncing" @click="reconcile"><span class="refresh-icon" :class="{ spinning: syncing }">↻</span>Reconcile global</button>
      </div>
    </header>

    <div v-if="error" class="notice notice-error" role="alert">{{ error }}</div>
    <div v-else-if="message" class="notice" role="status">{{ message }}</div>

    <section class="panel downloads-catalog" aria-label="Katalog unduhan">
      <div class="downloads-toolbar">
        <div class="tab-list" role="tablist" aria-label="Status artifact">
          <button v-for="tab in tabs" :key="tab.key" class="tab-button" :class="{ selected: activeTab === tab.key }" role="tab" :aria-selected="activeTab === tab.key" @click="changeTab(tab.key)">{{ tab.label }}</button>
        </div>
        <div class="download-actions">
          <button v-if="activeTab === 'pending'" class="button button-secondary" type="button" :disabled="pending || syncing" @click="clearFailed">Clear failed</button>
          <button v-if="activeTab === 'pending'" class="button button-secondary" type="button" :disabled="pending || syncing || !selectable.length" @click="start(selectable.map((item) => item.id))">Mulai semua</button>
        </div>
      </div>

      <div class="download-filters">
        <label>Profil<select v-model="profileFilter" class="field" aria-label="Profile" @change="changeFilter"><option value="">Semua profile</option><option v-for="profile in profileOptions" :key="profile.name" :value="profile.name">{{ profileOptionLabel(profile) }}</option></select></label>
        <label>Worker / VPS<select v-model="workerFilter" class="field" aria-label="Worker / VPS" @change="changeFilter"><option value="">Semua worker</option><option v-for="worker in workerOptions" :key="worker" :value="worker">{{ worker }}</option></select></label>
        <label>Label<input v-model="labelFilter" class="field" placeholder="Cari label" @change="changeFilter"></label>
        <label>Referensi chat<input v-model="chatRefFilter" class="field" placeholder="@username, link, ID, atau telepon" @change="changeFilter"></label>
        <button class="button button-secondary select-visible" type="button" :disabled="pending || syncing || !selectable.length" @click="toggleAll">{{ allVisibleSelected ? 'Hapus pilihan' : 'Pilih semua' }}</button>
      </div>

      <div v-if="selected.length" class="selection-bar">
        <strong>{{ selected.length }} artifact dipilih</strong>
        <button class="button" type="button" :disabled="pending || syncing" @click="start([...selected])">Mulai terpilih</button>
        <button class="button button-secondary" type="button" :disabled="pending || syncing" @click="start([...selected], 'next')">Berikutnya</button>
        <button class="button button-danger" type="button" :disabled="pending || syncing" @click="confirmAction = 'delete'">Hapus terpilih</button>
      </div>

      <div v-if="pending && !artifacts.length" class="empty-state" role="status">Memuat artifact…</div>
      <div class="artifact-table-wrap">
        <table class="artifact-table">
          <thead><tr><th>Pilih</th><th>Artifact</th><th>Origin</th><th>Statistik</th><th>Ukuran</th><th>Status</th><th>Waktu</th><th>Aksi</th></tr></thead>
          <tbody>
            <tr v-for="item in visible" :key="item.id">
              <td><input type="checkbox" :aria-label="`Pilih ${item.filename}`" :checked="selected.includes(item.id)" :disabled="pending || syncing || !(item.available ?? true) || !['pending', 'failed'].includes(item.status)" @change="toggle(item)"></td>
              <td><strong>{{ item.filename }}</strong><small class="muted">{{ item.label || item.chat_ref || '—' }}</small><small v-if="item.error" class="artifact-error">{{ item.error }}</small></td>
              <td><span class="origin-profile">{{ item.profile || '—' }}</span><small class="muted">{{ item.worker || 'local' }}</small></td>
              <td>{{ item.message_count ?? '?' }} pesan<small class="muted">{{ item.photo_count ?? '?' }} foto · {{ item.video_count ?? '?' }} video · {{ item.media_count ?? '?' }} media</small></td>
              <td>{{ formatBytes(item.actual_downloaded_bytes ?? item.expected_media_bytes ?? item.json_bytes) }}</td>
              <td><span class="status-pill" :class="statusClass(item.status)">{{ item.status }}</span><small v-if="!(item.available ?? true)" class="artifact-error">File tidak tersedia</small><small v-if="['pending', 'failed'].includes(item.status) && readinessFor(item).status !== 'ready'" class="muted" :title="readinessFor(item).reason_code">Scan terakhir: belum siap</small></td>
              <td>{{ formatDate(item.completed_at || item.created_at) }}</td>
              <td><div class="artifact-actions">
                <template v-if="activeTab === 'archived'"><button class="button button-secondary" type="button" @click="restore(item)">Restore</button><button class="button button-danger" type="button" @click="selected = [item.id]; confirmAction = 'purge'">Purge</button></template>
                <button v-else-if="activeTab === 'history' && item.status === 'downloaded'" class="button button-secondary" type="button" @click="archive(item)">Archive</button>
                <button v-else-if="['pending', 'failed'].includes(item.status) && Boolean(item.available ?? true)" class="button button-secondary" type="button" :disabled="pending || syncing" @click="start([item.id])">Mulai</button>
                <span v-else class="muted">—</span>
              </div></td>
            </tr>
            <tr v-if="!visible.length"><td colspan="8" class="artifact-empty">{{ catalogLoading ? 'Memuat artifact…' : 'Tidak ada artifact pada tab ini.' }}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="artifact-cards">
        <article v-for="item in visible" :key="item.id" class="artifact-card">
          <div class="artifact-card-heading"><label><input type="checkbox" :aria-label="`Pilih ${item.filename}`" :checked="selected.includes(item.id)" :disabled="pending || syncing || !(item.available ?? true) || !['pending', 'failed'].includes(item.status)" @change="toggle(item)"><strong>{{ item.filename }}</strong></label><span class="status-pill" :class="statusClass(item.status)">{{ item.status }}</span></div>
          <p class="muted">{{ item.profile || '—' }} · {{ item.worker || 'local' }} · {{ formatBytes(item.actual_downloaded_bytes ?? item.expected_media_bytes ?? item.json_bytes) }}</p>
          <small class="muted">{{ item.label || item.chat_ref || '—' }} · {{ formatDate(item.completed_at || item.created_at) }}</small>
          <div class="artifact-actions">
            <template v-if="activeTab === 'archived'"><button class="button button-secondary" type="button" @click="restore(item)">Restore</button><button class="button button-danger" type="button" @click="selected = [item.id]; confirmAction = 'purge'">Purge</button></template>
            <button v-else-if="activeTab === 'history' && item.status === 'downloaded'" class="button button-secondary" type="button" @click="archive(item)">Archive</button>
            <button v-else-if="['pending', 'failed'].includes(item.status) && Boolean(item.available ?? true)" class="button button-secondary" type="button" :disabled="pending || syncing" @click="start([item.id])">Mulai</button>
          </div>
        </article>
        <p v-if="!visible.length" class="empty-state">{{ catalogLoading ? 'Memuat artifact…' : 'Tidak ada artifact pada tab ini.' }}</p>
      </div>
    </section>

    <JobMonitor kind="download" title="Progress & riwayat download" scope="global" />

    <div v-if="confirmAction" class="dialog-backdrop" role="presentation" @click.self="confirmAction = null">
      <section class="confirm-dialog panel" role="dialog" aria-modal="true" :aria-labelledby="'download-confirm-title'">
        <p class="eyebrow">KONFIRMASI</p>
        <h2 id="download-confirm-title">{{ confirmAction === 'purge' ? 'Hapus metadata permanen?' : 'Hapus file artifact terpilih?' }}</h2>
        <p class="muted">{{ confirmAction === 'purge' ? 'Metadata artifact yang diarsipkan akan dihapus permanen.' : 'File JSON pending/failed pada worker asal akan dihapus; metadata history tetap dipertahankan.' }}</p>
        <div class="dialog-actions"><button class="button button-secondary" type="button" @click="confirmAction = null">Batal</button><button class="button button-danger" type="button" :disabled="pending" @click="confirmDestructive">Lanjutkan</button></div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.downloads-page { min-width: 0; }
.downloads-toolbar, .tab-list, .download-actions, .selection-bar, .artifact-actions, .dialog-actions { display: flex; align-items: center; gap: .5rem; }
.downloads-toolbar { justify-content: space-between; flex-wrap: wrap; padding: .8rem; border-bottom: 1px solid var(--line); }
.tab-list { overflow-x: auto; padding: .2rem; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); }
.tab-button { flex: 0 0 auto; padding: .48rem .7rem; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--muted); font-size: .68rem; font-weight: 700; }
.tab-button.selected { border-color: var(--line); background: var(--panel); color: var(--ink); }
.download-filters { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)) auto; align-items: end; gap: .65rem; padding: .8rem; border-bottom: 1px solid var(--line); }
.download-filters label { display: grid; gap: .35rem; color: var(--muted); font-size: .62rem; font-weight: 700; }
.field { width: 100%; min-height: 36px; padding: .45rem .58rem; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-soft); color: var(--ink); font-size: .69rem; }
.select-visible { white-space: nowrap; }
.selection-bar { justify-content: flex-end; flex-wrap: wrap; padding: .65rem .8rem; border-bottom: 1px solid var(--line); background: var(--brand-soft); }
.selection-bar strong { margin-right: auto; font-size: .68rem; }
.button-danger { border-color: color-mix(in srgb, var(--danger) 32%, var(--line)); background: color-mix(in srgb, var(--danger) 10%, var(--panel)); color: var(--danger); }
.artifact-table-wrap { overflow-x: auto; }
.artifact-table { width: 100%; min-width: 950px; border-collapse: collapse; text-align: left; font-size: .67rem; }
.artifact-table th { padding: .7rem .55rem; border-bottom: 1px solid var(--line); color: var(--muted); font-family: "DM Mono", monospace; font-size: .55rem; font-weight: 500; letter-spacing: .07em; text-transform: uppercase; white-space: nowrap; }
.artifact-table td { max-width: 220px; padding: .65rem .55rem; border-bottom: 1px solid color-mix(in srgb, var(--line) 75%, transparent); vertical-align: middle; }
.artifact-table td:first-child, .artifact-table th:first-child { padding-left: .85rem; }
.artifact-table td:last-child, .artifact-table th:last-child { padding-right: .85rem; }
.artifact-table td small { display: block; margin-top: .23rem; font-size: .59rem; }
.origin-profile { display: inline-flex; padding: .21rem .4rem; border: 1px solid var(--line); border-radius: 6px; background: var(--panel-soft); font-family: "DM Mono", monospace; font-size: .59rem; }
.artifact-error { color: var(--danger); }
.artifact-actions { justify-content: flex-end; flex-wrap: wrap; }
.artifact-actions .button { min-height: 31px; padding: .4rem .55rem; font-size: .61rem; }
.artifact-empty { padding: 2.6rem 1rem !important; color: var(--muted); text-align: center; }
.artifact-cards { display: none; }
.artifact-card { display: grid; gap: .42rem; padding: .8rem; border-bottom: 1px solid var(--line); font-size: .68rem; }
.artifact-card-heading, .artifact-card-heading label { display: flex; align-items: center; gap: .5rem; }
.artifact-card-heading { justify-content: space-between; }
.artifact-card p { margin: 0; }
.dialog-backdrop { position: fixed; z-index: 80; inset: 0; display: grid; place-items: center; padding: 1rem; background: rgba(0, 0, 0, .66); backdrop-filter: blur(4px); }
.confirm-dialog { width: min(100%, 430px); padding: 1rem; box-shadow: var(--shadow); }
.confirm-dialog h2 { margin: .35rem 0; font-size: 1rem; }
.confirm-dialog > p:not(.eyebrow) { font-size: .7rem; line-height: 1.5; }
.dialog-actions { justify-content: flex-end; margin-top: 1rem; }
@media (max-width: 900px) { .download-filters { grid-template-columns: repeat(2, minmax(120px, 1fr)); } .select-visible { justify-self: start; } }
@media (max-width: 620px) { .downloads-page .page-heading { align-items: flex-start; flex-direction: column; } .downloads-page .heading-actions { justify-content: flex-start; flex-wrap: wrap; } .downloads-toolbar { align-items: flex-start; } .download-filters { grid-template-columns: 1fr 1fr; } .artifact-table-wrap { display: none; } .artifact-cards { display: block; } .artifact-card .artifact-actions { justify-content: flex-start; } }
</style>
