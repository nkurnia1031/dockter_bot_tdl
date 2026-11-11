<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import { api, post, put } from '../lib/api';
import { normalizeTdlChatRef } from '../../../src/lib/chatRef';

type TtsProfile = { profile: string; status: string; reason_code: string };
type TtsWorker = {
  name: string;
  enabled: boolean;
  ready: boolean;
  queued_jobs: number;
  reason_code: string;
  profiles?: TtsProfile[];
  profile_session_ready?: boolean;
};

const maxChars = 100_000;
const title = ref('');
const text = ref('');
const workers = ref<TtsWorker[]>([]);
const worker = ref('');
const workersLoading = ref(true);
const workersRefreshing = ref(false);
const chatConfigured = ref(false);
const chatDraft = ref('');
const chatSaving = ref(false);
const chatMessage = ref('');
const chatError = ref('');
const submitting = ref(false);
const error = ref('');
const notice = ref('');
const activeWorkers = computed(() => workers.value.filter((item) => item.enabled));
const workerReason = (code: string) => ({
  ready: 'Siap menerima job', runtime_not_scanned: 'Belum ada hasil scan',
  tts_destination_changed: 'Tujuan berubah; command aktual akan mengujinya',
  tts_chat_unavailable: 'Chat tujuan belum dikonfigurasi', tts_helper_unavailable: 'Helper TTS tidak siap',
  tts_runtime_unavailable: 'Runtime TTS tidak siap', tdl_access_not_verified: 'Belum ada hasil command terbaru; job tetap dapat dicoba',
  tdl_session_unauthorized: 'Sesi TDL perlu diperiksa', profile_session_changed: 'Snapshot lama; command aktual menentukan hasil',
  profile_session_unavailable: 'Sesi profil tidak siap', worker_disabled: 'Dinonaktifkan untuk job baru',
  worker_unavailable: 'Worker tidak dapat dihubungi', worker_update_required: 'Perlu update worker',
  helpers_not_ready: 'Helper gTTS atau Tor belum siap', tdl_access_unverified: 'Belum ada hasil command terbaru; job tetap dapat dicoba',
  tts_capability_missing: 'Capability TTS belum dilaporkan', capability_unavailable: 'Capability worker belum dapat diperiksa'
} as Record<string, string>)[code] || code || 'Status belum diketahui');

async function loadWorkers() {
  workersLoading.value = true;
  try {
    const result = await api<{ items?: TtsWorker[] }>('/tts/workers');
    workers.value = result.items || [];
    if (worker.value && !workers.value.some((item) => item.name === worker.value && item.enabled)) worker.value = '';
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Daftar worker TTS gagal dimuat.';
  } finally {
    workersLoading.value = false;
    workersRefreshing.value = false;
  }
}

async function loadChatStatus() {
  try {
    const result = await api<{ telegram_tts_chat_configured: boolean }>('/runtime/secrets');
    chatConfigured.value = result.telegram_tts_chat_configured;
  } catch (cause) {
    chatError.value = cause instanceof Error ? cause.message : 'Status chat tujuan gagal dimuat.';
  }
}

async function refreshWorkers() {
  if (workersRefreshing.value) return;
  workersRefreshing.value = true;
  await Promise.all([loadWorkers(), loadChatStatus()]);
}

async function saveChatId(clear = false) {
  chatMessage.value = '';
  chatError.value = '';
  const chatId = normalizeTdlChatRef(chatDraft.value);
  if (!clear && !chatId) {
    chatError.value = 'Masukkan ID numeric, @username, username, link publik t.me, atau nomor telepon internasional.';
    return;
  }
  chatSaving.value = true;
  try {
    const result = await put<{ telegram_tts_chat_configured: boolean }>('/runtime/secrets', {
      telegram_tts_chat_id: clear ? '' : (chatId || '')
    });
    chatConfigured.value = result.telegram_tts_chat_configured;
    chatDraft.value = '';
    chatMessage.value = clear
      ? 'ID chat dihapus. Job TTS berikutnya tidak akan dikirim sampai tujuan baru diatur.'
      : 'ID chat tersimpan. Status scan dapat diperbarui dari halaman Profil.';
    void loadWorkers();
  } catch (cause) {
    chatError.value = cause instanceof Error ? cause.message : 'ID chat gagal disimpan.';
  } finally { chatSaving.value = false; }
}

async function submit() {
  error.value = '';
  notice.value = '';
  if (!title.value.trim() || !text.value.trim()) {
    error.value = 'Judul dan teks wajib diisi.';
    return;
  }
  if (text.value.length > maxChars) {
    error.value = `Teks tidak boleh lebih dari ${maxChars.toLocaleString('id-ID')} karakter.`;
    return;
  }
  submitting.value = true;
  try {
    const payload: { title: string; text: string; worker?: string } = { title: title.value.trim(), text: text.value.trim() };
    if (worker.value) payload.worker = worker.value;
    await post('/tts/jobs', payload);
    notice.value = 'Job TTS masuk antrean.';
    text.value = '';
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Job TTS gagal dibuat.';
  } finally { submitting.value = false; }
}

function onJobFinished() { void loadWorkers(); }

onMounted(() => {
  void Promise.all([loadWorkers(), loadChatStatus()]);
  window.addEventListener('tme3:job-finished', onJobFinished);
});
onUnmounted(() => window.removeEventListener('tme3:job-finished', onJobFinished));
</script>

<template>
  <main class="page-stack tts-page">
    <header class="page-heading"><div><p class="eyebrow">PEMROSESAN · TEXT TO SPEECH</p><h1>TTS Novel</h1><p class="muted">Ubah teks menjadi audio. Pilih worker tertentu atau biarkan sistem memakai antrean terpendek.</p></div></header>

    <section class="tts-overview">
      <article class="panel tts-chat-config">
        <header class="panel-heading"><div><p class="eyebrow">DESTINASI</p><h2>Chat tujuan MP3</h2></div><span class="status-pill" :class="chatConfigured ? 'status-ready' : 'status-warning'">{{ chatConfigured ? 'ID tersimpan' : 'Belum diatur' }}</span></header>
        <div class="tts-config-body"><p class="muted">ID chat tersimpan tidak ditampilkan kembali.</p><div class="chat-config-row"><label>ID chat Telegram<input v-model="chatDraft" class="field" autocomplete="off" placeholder="-100123456789 · @iyear · https://t.me/iyear"></label><button class="button" type="button" :disabled="chatSaving || !chatDraft.trim()" @click="saveChatId()">{{ chatSaving ? 'Menyimpan…' : 'Simpan ID chat' }}</button><button v-if="chatConfigured" class="button button-secondary" type="button" :disabled="chatSaving" @click="saveChatId(true)">Hapus</button></div><p v-if="chatError" class="notice notice-error" role="alert">{{ chatError }}</p><p v-if="chatMessage" class="notice notice-success" role="status">{{ chatMessage }}</p><small class="muted">Terima ID numeric, username, link publik t.me, dan nomor telepon internasional.</small></div>
      </article>

      <article class="panel tts-workers">
        <header class="panel-heading"><div><p class="eyebrow">RUNTIME</p><h2>Worker TTS</h2></div><button class="button button-secondary button-small" type="button" :disabled="workersLoading || workersRefreshing" @click="refreshWorkers">{{ workersRefreshing ? 'Memuat…' : 'Muat ulang status' }}</button></header>
        <p class="muted worker-help">Hasil scan hanya informasi. Job aktual menguji TDL/TTS saat berjalan.</p>
        <p v-if="workersLoading" class="empty-state" role="status">Memeriksa worker…</p>
        <p v-else-if="!workers.length" class="empty-state">Belum ada worker terdaftar.</p>
        <p v-else-if="!activeWorkers.length" class="notice notice-warning">Belum ada worker aktif untuk menerima job TTS.</p>
        <div v-else class="tts-worker-list"><article v-for="option in workers" :key="option.name" class="tts-worker-row"><div><strong>{{ option.name }}</strong><span class="status-pill" :class="option.ready ? 'status-ready' : 'status-warning'">{{ workerReason(option.reason_code) }}</span></div><small class="muted">Hasil scan terakhir (informasi): {{ option.profiles?.length ? option.profiles.map((profile) => `${profile.profile}: ${profile.status === 'ready' ? 'siap' : workerReason(profile.reason_code)}`).join(' · ') : 'belum dipindai' }}</small></article></div>
        <a class="diagnostic-link" href="/api/v1/diagnostics/tts/logs?limit=100" target="_blank" rel="noreferrer">Buka log diagnosis JSON</a>
      </article>
    </section>

    <article class="panel tts-compose">
      <header class="panel-heading"><div><p class="eyebrow">JOB BARU</p><h2>Buat audio</h2><p class="muted">Teks maksimal {{ maxChars.toLocaleString('id-ID') }} karakter. Progress ditampilkan tanpa isi teks.</p></div></header>
      <form class="tts-form" @submit.prevent="submit">
        <label v-if="activeWorkers.length && !workersLoading">Worker untuk job ini<select v-model="worker" class="field" aria-label="Worker untuk job ini"><option value="">Otomatis — antrean terpendek</option><option v-for="option in activeWorkers" :key="option.name" :value="option.name">{{ option.name }} · {{ option.queued_jobs }} job dalam antrean</option></select></label>
        <label>Judul audio<input v-model="title" class="field" maxlength="200" autocomplete="off" placeholder="Contoh: Bab 1 — Awal Perjalanan" required></label>
        <label>Teks<textarea v-model="text" class="field tts-textarea" :maxlength="maxChars" placeholder="Tempel teks novel di sini…" required></textarea><span class="muted char-count">{{ text.length.toLocaleString('id-ID') }} / {{ maxChars.toLocaleString('id-ID') }} karakter</span></label>
        <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p><p v-if="notice" class="notice notice-success" role="status">{{ notice }}</p>
        <footer class="tts-submit-row"><small class="muted">Pause berlaku setelah batch aktif selesai. Resume melanjutkan dari checkpoint.</small><button class="button" type="submit" :disabled="submitting || workersLoading || !activeWorkers.length || !title.trim() || !text.trim() || text.length > maxChars">{{ submitting ? 'Mengirim…' : 'Buat job TTS' }}</button></footer>
      </form>
    </article>
    <JobMonitor kind="tts" title="Antrean dan riwayat TTS" :retryable="true" />
  </main>
</template>

<style scoped>
.tts-overview{display:grid;grid-template-columns:minmax(20rem,.9fr) minmax(23rem,1.1fr);gap:.85rem;align-items:start}.tts-config-body{display:grid;gap:.6rem;padding:.8rem}.tts-config-body>p{margin:0;font-size:.67rem}.chat-config-row{display:flex;align-items:end;gap:.45rem}.chat-config-row label,.tts-form>label{display:grid;flex:1;gap:.35rem;font-size:.68rem;font-weight:750}.tts-config-body small{font-size:.61rem}.worker-help{margin:.7rem .8rem 0;font-size:.65rem}.tts-worker-list{display:grid;gap:.45rem;padding:.7rem .8rem}.tts-worker-row{display:grid;gap:.35rem;padding:.55rem .65rem;border:1px solid var(--line);border-radius:8px;background:var(--panel-soft)}.tts-worker-row>div{display:flex;align-items:center;justify-content:space-between;gap:.5rem;font-size:.68rem}.tts-worker-row>small{font-size:.6rem;line-height:1.45}.diagnostic-link{display:inline-block;margin:0 .8rem .75rem;color:var(--muted);font-size:.62rem;text-decoration:underline}.tts-compose .panel-heading{padding:.8rem}.tts-form{display:grid;gap:.75rem;padding:.85rem}.tts-form>label .field{width:100%}.tts-textarea{min-height:13rem;resize:vertical;line-height:1.55}.char-count{text-align:right;font-size:.61rem}.tts-submit-row{display:flex;align-items:center;justify-content:space-between;gap:.75rem}.tts-submit-row small{font-size:.62rem}.empty-state{padding:1rem;text-align:center;color:var(--muted);font-size:.68rem}.notice-success{border-color:color-mix(in srgb,var(--success) 35%,var(--line));color:var(--success)}
@media(max-width:850px){.tts-overview{grid-template-columns:1fr}}
@media(max-width:560px){.chat-config-row,.tts-submit-row{align-items:stretch;flex-direction:column}.chat-config-row>.button{width:100%}}
</style>
