<script setup lang="ts">
import CryptoJS from 'crypto-js';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { api } from '../lib/api';

const PASSPHRASE = 'root';
const EXAMPLE = 'a77894319ebfd94509a5db3c280d9aee30d8f20e48773993e3a07eda5632fcf4050a8da670fb4831a28b1f68f6cef20af063b32024485302';
const HISTORY_PAGE_SIZE = 5;
const ACTIVE_RESOLVER = new Set(['queued', 'dispatched', 'running', 'paused', 'cancelling']);
type HistoryItem = { id: string; result: string; created_at: string };
type ResolverJob = Record<string, any>;
type PageToken = number | `ellipsis-${number}-${number}`;
const formatter: { stringify(params: CryptoJS.lib.CipherParams): string; parse(value: string): CryptoJS.lib.CipherParams } = {
  stringify(params) { return `${params.salt?.toString() ?? ''}${params.ciphertext.toString()}`; },
  parse(value) {
    return CryptoJS.lib.CipherParams.create({
      salt: CryptoJS.enc.Hex.parse(value.slice(0, 16)),
      ciphertext: CryptoJS.enc.Hex.parse(value.slice(16))
    });
  }
};

const encrypted = ref('');
const plaintext = ref('');
const history = ref<HistoryItem[]>([]);
const historyError = ref('');
const historyLoading = ref(false);
const historyTotal = ref(0);
const historyPage = ref(1);
const selectedHistoryId = ref('');
const decryptSaving = ref(false);
const error = ref('');
const notice = ref('');
const copied = ref(false);
const shortlink = ref('');
const resolverError = ref('');
const resolverNotice = ref('');
const resolverBusy = ref(false);
const resolverCopied = ref(false);
const resolverEnabled = ref(false);
const resolverStatusError = ref('');
const resolverJobs = ref<ResolverJob[]>([]);
const resolverWorkers = ref<Record<string, any>[]>([]);
const selectedResolverWorker = ref('');
const resolverWorkerError = ref('');
const selectedResolverJobId = ref('');
const resolverRequestActive = ref(false);
let resolverTimer: ReturnType<typeof setTimeout> | undefined;
let mounted = false;
let requestGeneration = 0;

const historyPageCount = computed(() => Math.max(1, Math.ceil(historyTotal.value / HISTORY_PAGE_SIZE)));
const historyPageTokens = computed(() => getHistoryPageTokens(historyPage.value, historyPageCount.value));
const plaintextLink = computed(() => httpLink(plaintext.value));
const selectedResolverJob = computed(() => resolverJobs.value.find((job) => String(job.id) === selectedResolverJobId.value) || resolverJobs.value[0] || null);
const resolverResult = computed(() => {
  const result = selectedResolverJob.value?.result?.value ?? selectedResolverJob.value?.result;
  return typeof result?.destination_url === 'string' ? result.destination_url : '';
});
const resolverLink = computed(() => httpLink(resolverResult.value));

function httpLink(value: string): string {
  const candidate = value.trim();
  if (!candidate) return '';
  try {
    const url = new URL(candidate);
    return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : '';
  } catch { return ''; }
}

function readEncryptedValue(input: string): { value: string; fromParameter: boolean } {
  const raw = input.trim();
  const links = raw.match(/https?:\/\/[^\s)\]]+/gi) || [];
  for (const link of links) {
    try {
      const url = new URL(link);
      const fragment = url.hash.replace(/^#/, '');
      const query = fragment.includes('?') ? fragment.slice(fragment.indexOf('?') + 1) : fragment;
      const value = url.searchParams.get('o') || new URLSearchParams(query).get('o');
      if (value !== null && value !== undefined) return { value, fromParameter: true };
    } catch { /* continue through pasted links */ }
  }
  const parameter = raw.match(/(?:[?&#]|^)o=([^&#\s\])]+)/i);
  if (parameter) {
    let value = parameter[1];
    try { value = decodeURIComponent(value.replace(/\+/g, ' ')); } catch { /* preserve copied input */ }
    return { value, fromParameter: true };
  }
  if (links.length) throw new Error('URL tidak memiliki parameter o.');
  return { value: raw.replace(/\s+/g, ''), fromParameter: false };
}

async function decrypt() {
  if (decryptSaving.value) return;
  error.value = ''; notice.value = ''; plaintext.value = ''; copied.value = false; selectedHistoryId.value = '';
  let input: { value: string; fromParameter: boolean };
  try { input = readEncryptedValue(encrypted.value); }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Tidak dapat membaca input.'; return; }
  const value = input.value.replace(/\s+/g, '');
  if (!value) {
    error.value = input.fromParameter ? 'Parameter o pada URL kosong.' : 'Masukkan teks terenkripsi atau URL Safelink terlebih dahulu.';
    return;
  }
  if (!/^[\da-f]+$/i.test(value) || value.length < 48 || (value.length - 16) % 32 !== 0) {
    error.value = input.fromParameter ? 'Nilai parameter o bukan hex Safelink yang valid.' : 'Format tidak valid. Masukkan hex: 16 karakter salt, diikuti ciphertext AES dalam blok 32 karakter.';
    return;
  }
  let decoded = '';
  try { decoded = CryptoJS.AES.decrypt(value, PASSPHRASE, { format: formatter }).toString(CryptoJS.enc.Utf8); }
  catch { error.value = 'Dekripsi gagal. Periksa teks terenkripsi dan kecocokan kunci.'; return; }
  if (!decoded) { error.value = 'Hasil dekripsi kosong. Periksa kembali teks dan kunci yang digunakan.'; return; }
  plaintext.value = decoded;
  decryptSaving.value = true;
  try {
    const saved = await api<{ item?: HistoryItem }>('/decrypt/history', { method: 'POST', body: JSON.stringify({ result: decoded }) });
    if (saved.item) { selectedHistoryId.value = saved.item.id; await loadHistory(1); }
    notice.value = input.fromParameter ? 'Parameter o berhasil didekripsi dan hasilnya disimpan di riwayat.' : 'Dekripsi selesai dan hasilnya disimpan di riwayat.';
  } catch (cause) {
    error.value = cause instanceof Error ? `Dekripsi berhasil, tetapi hasil gagal disimpan di riwayat: ${cause.message}` : 'Dekripsi berhasil, tetapi hasil gagal disimpan di riwayat.';
  } finally { decryptSaving.value = false; }
}

async function loadHistory(page = historyPage.value) {
  if (historyLoading.value) return;
  const targetPage = Math.max(1, Math.floor(page));
  const offset = (targetPage - 1) * HISTORY_PAGE_SIZE;
  const knownIds = new Set(history.value.map((item) => item.id));
  const generation = ++requestGeneration;
  historyLoading.value = true;
  try {
    const result = await api<{ items?: HistoryItem[]; total?: number }>(`/decrypt/history?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`);
    if (!mounted || generation !== requestGeneration) return;
    const received = result.items || [];
    const receivedIds = new Set(received.map((item) => item.id));
    const addedWhileLoading = targetPage === 1 ? history.value.filter((item) => !knownIds.has(item.id) && !receivedIds.has(item.id)) : [];
    history.value = [...addedWhileLoading, ...received].slice(0, HISTORY_PAGE_SIZE);
    historyTotal.value = Number(result.total || 0) + addedWhileLoading.length;
    historyPage.value = Math.min(targetPage, Math.max(1, Math.ceil(historyTotal.value / HISTORY_PAGE_SIZE)));
    historyError.value = '';
  } catch (cause) {
    if (mounted && generation === requestGeneration) historyError.value = cause instanceof Error ? cause.message : 'Riwayat hasil dekripsi tidak dapat dimuat.';
  } finally {
    if (mounted && generation === requestGeneration) historyLoading.value = false;
  }
}

function getHistoryPageTokens(currentPage: number, pageCount: number): PageToken[] {
  const pages = new Set<number>([1, pageCount]);
  for (let page = currentPage - 1; page <= currentPage + 1; page += 1) if (page >= 1 && page <= pageCount) pages.add(page);
  const sorted = [...pages].sort((a, b) => a - b);
  const tokens: PageToken[] = [];
  sorted.forEach((page, index) => {
    if (index > 0 && page - sorted[index - 1] > 1) tokens.push(`ellipsis-${sorted[index - 1]}-${page}`);
    tokens.push(page);
  });
  return tokens;
}

function formatDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); }
async function copy(value: string, kind: 'decrypt' | 'resolver') {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    if (kind === 'decrypt') { copied.value = true; notice.value = 'Hasil disalin ke clipboard.'; setTimeout(() => copied.value = false, 1800); }
    else { resolverCopied.value = true; resolverNotice.value = 'URL tujuan disalin ke clipboard.'; setTimeout(() => resolverCopied.value = false, 1800); }
  } catch {
    if (kind === 'decrypt') error.value = 'Clipboard tidak dapat diakses. Pilih dan salin hasil secara manual.';
    else resolverError.value = 'Clipboard tidak dapat diakses. Pilih dan salin hasil secara manual.';
  }
}
function fillExample() { encrypted.value = EXAMPLE; plaintext.value = ''; selectedHistoryId.value = ''; error.value = ''; notice.value = ''; }
function clearAll() { encrypted.value = ''; plaintext.value = ''; selectedHistoryId.value = ''; error.value = ''; notice.value = ''; copied.value = false; }
function requestKey() { return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`; }

function scheduleResolverRefresh() {
  if (resolverTimer) clearTimeout(resolverTimer);
  if (!mounted || !resolverJobs.value.some((job) => ACTIVE_RESOLVER.has(String(job.status)))) return;
  resolverTimer = setTimeout(() => { resolverTimer = undefined; void loadResolverJobs(); }, 2500);
}
async function loadResolverJobs() {
  if (resolverRequestActive.value) return;
  resolverRequestActive.value = true;
  if (resolverTimer) { clearTimeout(resolverTimer); resolverTimer = undefined; }
  try {
    const result = await api<{ items?: ResolverJob[] }>('/jobs?kind=safelink_resolve&scope=current&archived=false&limit=50');
    resolverJobs.value = result.items || [];
    if (!resolverJobs.value.some((job) => String(job.id) === selectedResolverJobId.value)) selectedResolverJobId.value = String(resolverJobs.value[0]?.id || '');
    resolverError.value = '';
  } catch (cause) { resolverError.value = cause instanceof Error ? cause.message : 'Riwayat resolver tidak dapat dimuat.'; }
  finally { resolverRequestActive.value = false; scheduleResolverRefresh(); }
}
async function loadResolverWorkers() {
  if (!resolverEnabled.value) return;
  try { const result = await api<{ items?: Record<string, any>[] }>('/safelink/workers'); resolverWorkers.value = result.items || []; resolverWorkerError.value = ''; }
  catch (cause) { resolverWorkers.value = []; resolverWorkerError.value = cause instanceof Error ? cause.message : 'Status worker Resolver tidak dapat dimuat.'; }
}
async function loadResolverStatus() {
  try {
    const status = await api<{ enabled?: boolean }>('/safelink/status');
    resolverEnabled.value = status.enabled === true;
    resolverStatusError.value = '';
    if (resolverEnabled.value) void loadResolverWorkers();
    else { resolverWorkers.value = []; resolverWorkerError.value = ''; }
  } catch { resolverEnabled.value = false; resolverWorkers.value = []; resolverWorkerError.value = ''; resolverStatusError.value = 'Status Resolver tidak dapat dimuat; pengiriman dinonaktifkan sementara.'; }
}
async function resolveShortlink() {
  resolverError.value = ''; resolverNotice.value = ''; resolverCopied.value = false;
  if (!resolverEnabled.value) { resolverError.value = 'Resolver dinonaktifkan sementara.'; return; }
  if (!shortlink.value.trim()) { resolverError.value = 'Tempel URL shortlink terlebih dahulu.'; return; }
  resolverBusy.value = true;
  try {
    const job = await api<ResolverJob>('/safelink/jobs', { method: 'POST', headers: { 'Idempotency-Key': requestKey() }, body: JSON.stringify({ url: shortlink.value.trim(), ...(selectedResolverWorker.value ? { worker: selectedResolverWorker.value } : {}) }) });
    selectedResolverJobId.value = String(job.id || '');
    resolverNotice.value = 'Job resolver masuk antrean. Kamu dapat menutup halaman; hasilnya tersimpan di riwayat.';
    await loadResolverJobs(); await loadResolverWorkers(); selectedResolverJobId.value = String(job.id || ''); scheduleResolverRefresh();
    window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
  } catch (cause) { resolverError.value = cause instanceof Error ? cause.message : 'Job resolver gagal dikirim.'; }
  finally { resolverBusy.value = false; }
}
async function resolverAction(job: ResolverJob, action: 'cancel' | 'retry') {
  resolverError.value = '';
  if (action === 'retry' && !resolverEnabled.value) { resolverError.value = 'Resolver dinonaktifkan sementara.'; return; }
  try {
    await api(`/safelink/jobs/${encodeURIComponent(String(job.id))}/${action}`, { method: 'POST', headers: { 'Idempotency-Key': requestKey() } });
    resolverNotice.value = action === 'cancel' ? 'Permintaan pembatalan dikirim.' : 'Job masuk antrean ulang.';
    await loadResolverJobs(); selectedResolverJobId.value = String(job.id);
    window.dispatchEvent(new CustomEvent('tme3:data-mutated'));
  } catch (cause) { resolverError.value = cause instanceof Error ? cause.message : 'Aksi job gagal.'; }
}

function onDataMutated() { void loadHistory(); void loadResolverJobs(); void loadResolverStatus(); }
function onVisibilityChange() { if (document.visibilityState === 'hidden' && resolverTimer) { clearTimeout(resolverTimer); resolverTimer = undefined; } else scheduleResolverRefresh(); }
function refreshResolver() { void loadResolverJobs(); void loadResolverStatus(); }
onMounted(() => {
  mounted = true;
  window.addEventListener('tme3:data-mutated', onDataMutated);
  document.addEventListener('visibilitychange', onVisibilityChange);
  void loadHistory(); void loadResolverJobs(); void loadResolverStatus();
});
onUnmounted(() => { mounted = false; requestGeneration++; if (resolverTimer) clearTimeout(resolverTimer); window.removeEventListener('tme3:data-mutated', onDataMutated); document.removeEventListener('visibilitychange', onVisibilityChange); });
</script>

<template>
  <main class="page-stack decrypt-page">
    <header class="page-heading"><div><p class="eyebrow">PEMROSESAN</p><h1>Dekripsi teks</h1><p class="muted">Dekripsi teks Safelink dengan format yang kompatibel dengan script CryptoJS.</p></div></header>
    <section class="panel" aria-labelledby="decrypt-title">
      <div class="panel-heading"><div><h2 id="decrypt-title">Teks terenkripsi</h2><p class="muted">Tempel nilai hex atau URL Safelink; jika berupa URL, hanya parameter <code>o</code> yang diproses.</p></div><button class="button button-secondary" type="button" @click="fillExample">Isi contoh</button></div>
      <label class="sr-only" for="encrypted-text">Teks terenkripsi</label><textarea id="encrypted-text" v-model="encrypted" class="field mono" rows="5" placeholder="Tempel teks terenkripsi di sini…" spellcheck="false" autocomplete="off" autocapitalize="off" />
      <div class="toolbar-actions"><button class="button button-primary" type="button" :disabled="decryptSaving" @click="decrypt">{{ decryptSaving ? 'Menyimpan…' : 'Dekripsi' }}</button><button class="button button-secondary" type="button" @click="clearAll">Bersihkan</button></div>
      <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p><p v-if="notice" class="notice notice-success" role="status">{{ notice }}</p>
    </section>
    <section class="panel" aria-labelledby="plaintext-title"><div class="panel-heading"><div><h2 id="plaintext-title">Hasil dekripsi</h2><p class="muted">Hasil tersimpan terenkripsi di riwayat.</p></div><button class="button button-secondary" :disabled="!plaintext" @click="copy(plaintext, 'decrypt')">{{ copied ? 'Tersalin' : 'Salin hasil' }}</button></div>
      <a v-if="plaintextLink" class="result-text" :href="plaintextLink" target="_blank" rel="noopener noreferrer">{{ plaintext.trim() }}</a><label v-else class="sr-only" for="decrypted-text">Hasil dekripsi</label><textarea v-if="!plaintextLink" id="decrypted-text" v-model="plaintext" class="field mono result-area" placeholder="Hasil dekripsi akan muncul di sini…" readonly spellcheck="false" />
    </section>
    <section class="panel" aria-labelledby="decrypt-history-title"><div class="panel-heading"><div><h2 id="decrypt-history-title">Riwayat hasil dekripsi</h2><p class="muted">{{ history.length }} dari {{ historyTotal }} hasil tersimpan</p></div><button class="button button-secondary" :disabled="historyLoading" @click="loadHistory()">{{ historyLoading ? 'Memuat…' : 'Muat ulang' }}</button></div>
      <p v-if="historyError" class="notice notice-error" role="alert">{{ historyError }}</p><p v-if="historyLoading && !history.length" class="empty-state" role="status">Memuat riwayat dekripsi…</p>
      <div v-else-if="history.length" class="history-list"><button v-for="item in history" :key="item.id" class="history-row" :class="{ selected: selectedHistoryId === item.id }" :aria-label="`Tampilkan hasil dekripsi ${formatDate(item.created_at)}`" @click="plaintext = item.result; selectedHistoryId = item.id; error = ''; notice = 'Hasil dekripsi dimuat dari riwayat.'; copied = false"><small class="muted">{{ formatDate(item.created_at) }}</small><span>{{ item.result }}</span></button></div>
      <p v-else-if="!historyLoading" class="empty-state">Belum ada hasil dekripsi tersimpan.</p>
      <nav v-if="historyPageCount > 1" class="page-nav" aria-label="Navigasi halaman riwayat dekripsi"><button class="button button-secondary" aria-label="Sebelumnya" :disabled="historyLoading || historyPage <= 1" @click="loadHistory(historyPage - 1)">Sebelumnya</button><template v-for="token in historyPageTokens" :key="token"><button v-if="typeof token === 'number'" class="button" :class="token === historyPage ? 'button-primary' : 'button-secondary'" :aria-label="`Halaman ${token}`" :aria-current="token === historyPage ? 'page' : undefined" :disabled="historyLoading || token === historyPage" @click="loadHistory(token)">{{ token }}</button><span v-else aria-hidden="true">…</span></template><button class="button button-secondary" aria-label="Berikutnya" :disabled="historyLoading || historyPage >= historyPageCount" @click="loadHistory(historyPage + 1)">Berikutnya</button></nav>
    </section>
    <p class="muted security-note">Dekripsi dilakukan di browser. Saat berhasil, hasil teks dikirim melalui sesi login dan disimpan terenkripsi di database; input terenkripsi tidak dikirim. Kunci mengikuti script contoh.</p>
      <section class="panel" aria-labelledby="resolver-title"><div class="panel-heading"><div><p class="eyebrow">JOB WORKER</p><h2 id="resolver-title">Resolver shortlink</h2><p class="muted">{{ resolverEnabled ? 'Ikuti langkah shortlink pndk.to atau go.fakta.id di browser worker. Resolver hanya mencari URL tujuan.' : 'Lihat job Resolver yang sudah ada; hasil dan riwayatnya tetap tersimpan.' }}</p></div><button class="button button-secondary" :disabled="resolverRequestActive" @click="refreshResolver">{{ resolverRequestActive ? 'Memuat…' : 'Refresh job' }}</button></div>
      <template v-if="resolverEnabled"><label for="shortlink-input">URL shortlink</label><textarea id="shortlink-input" v-model="shortlink" class="field mono" rows="3" maxlength="2048" placeholder="https://pndk.to/... atau https://go.fakta.id/..." spellcheck="false"/><label for="resolver-worker">Worker</label><select id="resolver-worker" v-model="selectedResolverWorker" class="field"><option value="">Auto · antrean terpendek</option><option v-for="item in resolverWorkers" :key="item.name" :value="item.name">{{ item.name }} · {{ item.status }} · antrean {{ item.queued_jobs ?? 0 }}</option></select><p v-if="resolverWorkerError" class="muted" role="status">{{ resolverWorkerError }}</p><button class="button button-primary" :disabled="resolverBusy" @click="resolveShortlink">{{ resolverBusy ? 'Mengirim…' : 'Resolve' }}</button></template>
      <p v-else class="notice notice-warning" role="status">{{ resolverStatusError || 'Resolver dinonaktifkan sementara. Job dan hasil sebelumnya tetap tersedia di bawah.' }}</p>
      <p v-if="resolverError" class="notice notice-error" role="alert">{{ resolverError }}</p><p v-if="resolverNotice" class="notice notice-success" role="status">{{ resolverNotice }}</p>
      <div class="subsection"><div class="panel-heading"><div><h3>Hasil URL tujuan</h3><p class="muted">Klik tautan untuk membukanya di tab baru.</p></div><button class="button button-secondary" :disabled="!resolverResult" @click="copy(resolverResult, 'resolver')">{{ resolverCopied ? 'Tersalin' : 'Salin URL' }}</button></div><a v-if="resolverLink" class="result-text" :href="resolverLink" target="_blank" rel="noopener noreferrer">{{ resolverResult }}</a><p v-else class="empty-state">URL tujuan muncul setelah job selesai.</p></div>
      <div class="subsection"><div class="panel-heading"><h3>Job resolver</h3><span class="muted">{{ resolverJobs.length }} job tersimpan</span></div><div v-if="resolverJobs.length" class="history-list"><article v-for="job in resolverJobs" :key="job.id" class="history-row resolver-job" :class="{ selected: selectedResolverJobId === String(job.id) }"><button class="job-select" @click="selectedResolverJobId = String(job.id)"><span>#{{ String(job.id).slice(0, 8) }} · {{ job.status }} · {{ job.worker }}</span><span>{{ job.progress?.message || job.error?.message || 'Resolver shortlink' }}</span><small v-if="job.result?.value?.destination_url || job.result?.destination_url">{{ job.result?.value?.destination_url || job.result?.destination_url }}</small></button><div class="toolbar-actions"><button v-if="ACTIVE_RESOLVER.has(String(job.status))" class="button button-danger" @click="resolverAction(job, 'cancel')">Batalkan</button><button v-if="resolverEnabled && ['failed','cancelled'].includes(String(job.status))" class="button button-secondary" @click="resolverAction(job, 'retry')">Coba lagi</button></div></article></div><p v-else class="empty-state">Belum ada job resolver. Setelah dikirim, status dan hasil tersimpan di sini.</p></div>
    </section>
  </main>
</template>

<style scoped>
.decrypt-page{max-width:75rem;margin:0 auto}.panel{display:grid;gap:.85rem;padding:1rem;border:1px solid var(--line);border-radius:1rem;background:var(--panel)}.panel h2,.panel h3{font-weight:800}.panel-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:.8rem}.panel-heading p{margin-top:.2rem;font-size:.78rem}.field{width:100%;margin-top:.25rem;padding:.65rem .75rem;border:1px solid var(--line);border-radius:.65rem;background:var(--panel-soft);color:var(--text)}.mono,.history-row span,.result-text{font-family:ui-monospace,SFMono-Regular,monospace}.toolbar-actions,.page-nav{display:flex;align-items:center;flex-wrap:wrap;gap:.45rem}.button{padding:.5rem .7rem;border:1px solid var(--line);border-radius:.6rem;font-size:.75rem;font-weight:700}.button-primary{border-color:var(--accent);background:var(--accent);color:#071218}.button-secondary{background:var(--panel-soft)}.button-danger{color:#fecaca}.button:disabled{opacity:.5}.notice,.empty-state{padding:.7rem;border-radius:.65rem;font-size:.78rem}.notice-error{background:color-mix(in srgb,#ef4444 15%,transparent);color:#fecaca}.notice-success{color:#86efac}.notice-warning{color:#fcd34d}.history-list{display:grid;gap:.4rem}.history-row{display:grid;gap:.25rem;width:100%;padding:.65rem;border:1px solid var(--line);border-radius:.65rem;text-align:left;overflow:hidden}.history-row span,.history-row small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.history-row.selected{border-color:var(--accent)}.result-text{display:block;overflow-wrap:anywhere;padding:.8rem;border:1px solid var(--line);border-radius:.65rem}.result-area{min-height:8rem}.security-note{font-size:.7rem}.subsection{display:grid;gap:.6rem;padding-top:.8rem;border-top:1px solid var(--line)}.resolver-job{grid-template-columns:1fr auto}.job-select{display:grid;gap:.25rem;text-align:left;min-width:0;overflow:hidden}.job-select>*{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.page-nav{justify-content:center}
</style>
