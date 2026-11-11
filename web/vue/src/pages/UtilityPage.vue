<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import WorkspaceExplorer from '../components/WorkspaceExplorer.vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, remove } from '../lib/api';
import { session } from '../session';

type Job = Record<string, any> & { id?: string; status?: string };
type FlattenAction = { type: 'delete_empty' | 'move' | 'skip_multiple'; folder: string; source?: string; destination?: string; collision?: boolean; item_count?: number };
type FlattenDetail = { folder: string; flatten_preview: { fingerprint: string; passes: { index: number; actions: FlattenAction[] }[]; action_count: number; moves: number; deleted: number; skipped: number } };
type Preview = { selectionKey: string; details: FlattenDetail[]; fingerprints: Record<string, string>; summary: Record<string, number> };

const selected = ref<string[]>([]);
const saved = ref<string[]>([]);
const utility = ref('pindah');
const password = ref('');
const pending = ref(false);
const message = ref('');
const error = ref('');
const worker = ref('');
const preview = ref<Preview | null>(null);
const workers = computed(() => session.workers);
const selectionKey = () => JSON.stringify({ worker: worker.value, folders: [...selected.value].sort() });
const currentPreview = computed(() => utility.value === 'flatten' && preview.value?.selectionKey === selectionKey() ? preview.value : null);
const disposed = ref(false);
const terminal = new Set(['succeeded', 'failed', 'cancelled']);

watch(() => session.current.actor?.worker_route, (route) => { if (!worker.value && route) worker.value = route; }, { immediate: true });
watch(() => [worker.value, selected.value.join('|'), utility.value], () => { preview.value = null; });

async function loadSaved() {
  try { saved.value = (await api<{ items?: string[] }>('/utility/folders')).items || []; }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Daftar folder gagal dimuat.'; }
}
async function saveFolders() {
  if (!worker.value) return;
  pending.value = true; error.value = ''; message.value = '';
  try {
    for (const path of selected.value.filter((item) => !saved.value.includes(item))) await post('/utility/folders', { path });
    await loadSaved(); message.value = 'Pilihan folder disimpan.';
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Folder gagal disimpan.'; }
  finally { pending.value = false; }
}
async function removeSaved(path: string) {
  try { await remove(`/utility/folders?path=${encodeURIComponent(path)}`); await loadSaved(); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Folder gagal dihapus.'; }
}
async function waitForJob(id: string): Promise<Job | null> {
  while (!disposed.value) {
    const job = await api<Job>(`/jobs/${encodeURIComponent(id)}`);
    if (terminal.has(String(job.status))) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
  }
  return null;
}
function resultValue(job: Job): Record<string, any> {
  const result = job.result?.value || job.result || {};
  return result && typeof result === 'object' ? result : {};
}
async function previewFlatten() {
  if (!selected.value.length || !worker.value || pending.value) return;
  const key = selectionKey(); pending.value = true; error.value = ''; message.value = ''; preview.value = null;
  try {
    const submitted = await post<Job>('/utility/jobs', { utility: 'flatten', folders: selected.value, worker: worker.value, flatten_action: 'preview' });
    if (!submitted.id) throw new Error('Job preview tidak mengembalikan ID.');
    message.value = 'Menyusun preview Flatten…';
    const job = await waitForJob(String(submitted.id));
    if (!job) return;
    if (job.status !== 'succeeded') { error.value = String(job.error?.message || 'Preview Flatten gagal.'); return; }
    const result = resultValue(job);
    const details: FlattenDetail[] = Array.isArray(result.details) ? result.details.filter((item: any) => item?.flatten_preview?.fingerprint) : [];
    if (details.length !== selected.value.length) throw new Error('Hasil preview tidak mencakup semua folder pilihan.');
    if (selectionKey() !== key) { message.value = 'Pilihan worker atau folder berubah. Buat preview baru.'; return; }
    const fingerprints = Object.fromEntries(details.map((item) => [item.folder, item.flatten_preview.fingerprint]));
    preview.value = { selectionKey: key, details, fingerprints, summary: result.summary || {} };
    const actions = Number(result.summary?.action_count || 0);
    message.value = actions ? `Preview siap: ${actions} tindakan pada ${details.length} folder.` : 'Preview selesai. Tidak ada perubahan yang perlu diterapkan.';
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Preview Flatten gagal dibuat.'; }
  finally { pending.value = false; }
}
async function applyFlatten() {
  const current = currentPreview.value;
  if (!current || !current.summary.action_count || pending.value) return;
  if (!window.confirm(`Terapkan ${current.summary.action_count} tindakan Flatten pada ${current.details.length} folder?`)) return;
  pending.value = true; error.value = '';
  try {
    const submitted = await post<Job>('/utility/jobs', { utility: 'flatten', folders: current.details.map((item) => item.folder), worker: worker.value, flatten_action: 'apply', flatten_fingerprints: current.fingerprints });
    if (!submitted.id) throw new Error('Job apply tidak mengembalikan ID.');
    preview.value = null; message.value = 'Apply Flatten berjalan pada worker terpilih…';
    window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
    const job = await waitForJob(String(submitted.id));
    if (!job) return;
    message.value = job.status === 'succeeded' ? 'Flatten selesai.' : String(job.error?.message || 'Apply Flatten gagal. Buat preview baru sebelum mencoba lagi.');
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Apply Flatten gagal dibuat.'; }
  finally { pending.value = false; }
}
async function run() {
  if (!selected.value.length || !worker.value || pending.value) return;
  if (utility.value === 'flatten') { await previewFlatten(); return; }
  pending.value = true; error.value = ''; message.value = '';
  try {
    await post('/utility/jobs', { utility: utility.value, folders: selected.value, worker: worker.value, ...(utility.value === 'extract' && password.value ? { password: password.value } : {}) });
    message.value = `${selected.value.length} folder masuk antrean utility.`;
    window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Utility gagal dibuat.'; }
  finally { pending.value = false; }
}
function changeUtility(value: string) { utility.value = value; preview.value = null; error.value = ''; message.value = ''; if (value !== 'extract') password.value = ''; }
function flattenActionText(action: FlattenAction) {
  if (action.type === 'delete_empty') return `Hapus folder kosong: ${action.folder}`;
  if (action.type === 'move') return `Pindah ${action.source} → ${action.destination} (hapus ${action.folder})${action.collision ? ' · nama bentrok, diberi prefix' : ''}`;
  return `Lewati ${action.folder} (${action.item_count} item)`;
}
onMounted(() => { disposed.value = false; void loadSaved(); });
onUnmounted(() => { disposed.value = true; });
</script>

<template>
  <main class="page-stack utility-page">
    <header class="page-heading"><div><p class="eyebrow">PEMROSESAN</p><h1>Utility Workspace</h1><p class="muted">Jelajahi folder pada worker terpilih dan proses beberapa folder sekaligus.</p></div><label class="worker-select">Worker<select v-model="worker" class="field" aria-label="Worker target"><option value="">Pilih worker</option><option v-for="item in workers" :key="item.name" :value="item.name">{{ item.name }}{{ item.enabled === false ? ' · nonaktif' : '' }}</option></select></label></header>
    <div class="utility-grid"><section class="panel"><h2>Folder Workspace</h2><p class="muted">Semua pilihan dibatasi ke /workspace pada worker terpilih.</p><WorkspaceExplorer v-model:selected="selected" :worker="worker" /></section>
      <section class="panel"><label for="utility-kind">Jenis operasi</label><select id="utility-kind" :value="utility" class="field" @change="changeUtility(($event.target as HTMLSelectElement).value)"><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option><option value="flatten">Flatten folder</option></select>
        <label v-if="utility === 'extract'" for="utility-password">Password arsip<input id="utility-password" v-model="password" class="field" type="password" autocomplete="new-password" placeholder="Kosongkan untuk default" /></label>
        <div class="toolbar-actions"><button class="button button-primary" :disabled="!selected.length || !worker || pending" @click="run">{{ pending ? 'Memproses…' : utility === 'flatten' ? 'Preview Flatten' : 'Jalankan utility' }}</button><button class="button button-secondary" :disabled="!selected.length || !worker || pending" @click="saveFolders">Simpan pilihan</button></div>
        <p v-if="message" class="notice notice-info" role="status">{{ message }}</p><p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
        <section v-if="currentPreview" class="flatten-preview" aria-label="Preview Flatten"><div class="panel-heading"><div><h3>Preview Flatten</h3><p class="muted">{{ currentPreview.summary.moves || 0 }} pindah · {{ currentPreview.summary.deleted || 0 }} hapus · {{ currentPreview.summary.skipped || 0 }} dilewati</p></div><button v-if="currentPreview.summary.action_count" class="button button-danger" :disabled="pending" @click="applyFlatten">Terapkan Flatten</button></div>
          <article v-for="detail in currentPreview.details" :key="detail.folder" class="flatten-folder"><h4>{{ detail.folder }}</h4><div v-for="pass in detail.flatten_preview.passes" :key="pass.index"><small class="muted">Putaran {{ pass.index }}</small><ul><li v-for="(action, index) in pass.actions" :key="`${pass.index}:${index}`">{{ flattenActionText(action) }}</li></ul></div></article>
        </section>
        <section class="saved-folders"><div class="panel-heading"><h3>Folder tersimpan</h3><button class="button button-secondary" @click="loadSaved">Refresh</button></div><article v-for="path in saved" :key="path" class="saved-folder"><button @click="selected = selected.includes(path) ? selected : [...selected, path]">{{ path }}</button><button class="button button-danger" :aria-label="`Hapus ${path}`" @click="removeSaved(path)">Hapus</button></article><p v-if="!saved.length" class="empty-state">Belum ada folder tersimpan.</p></section>
      </section>
    </div>
    <JobMonitor kind="utility" title="Riwayat utility" view="all" />
  </main>
</template>

<style scoped>
.utility-page{max-width:92rem;margin:0 auto}.utility-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(19rem,.9fr);gap:1rem}.panel{display:grid;align-content:start;gap:.7rem;padding:1rem;border:1px solid var(--line);border-radius:1rem;background:var(--panel)}.panel h2,.panel h3{font-weight:800}.panel-heading{display:flex;align-items:center;justify-content:space-between;gap:.6rem}.worker-select{display:grid;gap:.25rem;min-width:12rem;font-size:.72rem;font-weight:700}.field{width:100%;padding:.6rem .7rem;border:1px solid var(--line);border-radius:.65rem;background:var(--panel-soft);color:var(--text)}.toolbar-actions{display:flex;flex-wrap:wrap;gap:.5rem}.button{padding:.5rem .7rem;border:1px solid var(--line);border-radius:.6rem;font-size:.76rem;font-weight:700}.button-primary{background:var(--accent);color:#071218}.button-secondary{background:var(--panel-soft)}.button-danger{color:#fecaca}.button:disabled{opacity:.5}.notice{padding:.65rem;border-radius:.65rem;font-size:.77rem}.notice-info{background:var(--panel-soft)}.notice-error{background:#3b121d;color:#fecaca}.flatten-preview,.saved-folders{display:grid;gap:.65rem;padding-top:.8rem;border-top:1px solid var(--line)}.flatten-folder,.saved-folder{padding:.65rem;border:1px solid var(--line);border-radius:.65rem}.flatten-folder h4,.saved-folder>button:first-child{font-family:ui-monospace,monospace;font-size:.75rem;overflow-wrap:anywhere}.flatten-folder ul{padding-left:1.2rem;font-size:.73rem}.saved-folder{display:flex;align-items:center;justify-content:space-between;gap:.5rem}.empty-state{padding:.75rem;text-align:center;color:var(--muted);font-size:.76rem}@media(max-width:800px){.utility-grid{grid-template-columns:1fr}}
</style>
