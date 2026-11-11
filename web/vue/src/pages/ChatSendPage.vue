<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import JobMonitor from '../components/JobMonitor.vue';
import WorkspaceExplorer from '../components/WorkspaceExplorer.vue';
import { api } from '../lib/api';
import { session } from '../session';

type LocalProfile = { name: string; ready?: boolean; reason_codes?: string[] };
type Job = { id?: string };

const worker = ref('');
const chatRef = ref('');
const profiles = ref<LocalProfile[]>([]);
const selectedProfiles = ref<string[]>([]);
const folders = ref<string[]>([]);
const transferMode = ref<'copy' | 'move'>('copy');
const profilesLoading = ref(false);
const submitting = ref(false);
const loadingError = ref('');
const error = ref('');
const notice = ref('');
const availableWorkers = computed(() => session.workers.filter((item) => item.enabled !== false));
const activeProfiles = computed(() => profiles.value.filter((item) => selectedProfiles.value.includes(item.name)));
let profileLoadGeneration = 0;

function idempotencyKey() {
  return globalThis.crypto?.randomUUID?.()
    || `chat-send-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function loadProfiles(target: string) {
  const generation = ++profileLoadGeneration;
  profilesLoading.value = true;
  loadingError.value = '';
  profiles.value = [];
  selectedProfiles.value = [];
  try {
    const response = await api<{ items?: LocalProfile[] }>(`/workers/${encodeURIComponent(target)}/profiles/local`);
    if (generation !== profileLoadGeneration) return;
    profiles.value = (response.items || []).filter((item) => typeof item.name === 'string' && item.name.trim());
    const preferred = session.current.actor?.profile;
    selectedProfiles.value = profiles.value.some((item) => item.name === preferred)
      ? [preferred as string]
      : profiles.value.slice(0, 1).map((item) => item.name);
  } catch (cause) {
    if (generation !== profileLoadGeneration) return;
    loadingError.value = cause instanceof Error ? cause.message : 'Daftar profil worker tidak dapat dimuat.';
  } finally {
    if (generation === profileLoadGeneration) profilesLoading.value = false;
  }
}

function changeWorker(target: string) {
  if (target === worker.value) return;
  worker.value = target;
  folders.value = [];
  if (target) void loadProfiles(target);
}

function toggleProfile(name: string) {
  selectedProfiles.value = selectedProfiles.value.includes(name)
    ? selectedProfiles.value.filter((item) => item !== name)
    : [...selectedProfiles.value, name];
}

function selectionOrder(name: string): number | undefined {
  const index = selectedProfiles.value.indexOf(name);
  return index < 0 ? undefined : index + 1;
}

async function submit() {
  error.value = '';
  notice.value = '';
  if (!worker.value || !selectedProfiles.value.length || !folders.value.length || !chatRef.value.trim()) {
    error.value = 'Pilih worker, satu atau beberapa profil, folder Workspace, dan chat tujuan.';
    return;
  }
  if (transferMode.value === 'move' && !window.confirm('Move akan menghapus setiap file sumber setelah TDL mengonfirmasi file terkirim. Lanjutkan?')) return;

  submitting.value = true;
  try {
    const result = await api<Job>('/chat-send/jobs', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: JSON.stringify({
        worker: worker.value,
        chat_ref: chatRef.value.trim(),
        folders: folders.value,
        profiles: selectedProfiles.value,
        transfer_mode: transferMode.value,
        move_confirmed: transferMode.value === 'move'
      })
    });
    window.dispatchEvent(new CustomEvent('tme3:data-mutated', { detail: { path: '/chat-send/jobs' } }));
    notice.value = `Job Kirim ke Chat diterima${result.id ? ` (#${String(result.id).slice(0, 8)})` : ''}.`;
    folders.value = [];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Job Kirim ke Chat gagal dibuat.';
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  const preferredWorker = session.current.actor?.worker_route;
  const target = availableWorkers.value.find((item) => item.name === preferredWorker)?.name
    || availableWorkers.value[0]?.name
    || '';
  if (target) changeWorker(target);
});
</script>

<template>
  <main class="page-stack chat-send-page">
    <header class="page-heading">
      <div><p class="eyebrow">TRANSFER · TELEGRAM</p><h1>Kirim ke Chat</h1><p class="muted">Kirim file Workspace sebagai dokumen, satu per satu dengan profil TDL bergiliran.</p></div>
    </header>

    <section class="chat-send-grid">
      <article class="panel chat-send-form">
        <header class="panel-heading"><div><p class="eyebrow">PENGIRIMAN</p><h2>Tujuan dan profil</h2></div></header>
        <div class="chat-send-fields">
          <label>Worker
            <select class="field" aria-label="Worker" :value="worker" :disabled="submitting" @change="changeWorker(($event.target as HTMLSelectElement).value)">
              <option value="" disabled>Pilih worker</option>
              <option v-for="item in availableWorkers" :key="item.name" :value="item.name">{{ item.name }}</option>
            </select>
          </label>

          <fieldset class="profile-choice">
            <legend>Profil TDL bergiliran</legend>
            <p v-if="profilesLoading" class="empty-state" role="status">Memuat profil worker…</p>
            <p v-else-if="loadingError" class="notice notice-error" role="alert">{{ loadingError }}</p>
            <p v-else-if="!profiles.length" class="empty-state">Worker belum melaporkan profil lokal.</p>
            <template v-else>
              <div class="profile-grid">
                <label v-for="profile in profiles" :key="profile.name" class="profile-option">
                  <input type="checkbox" :checked="selectedProfiles.includes(profile.name)" :disabled="submitting" @change="toggleProfile(profile.name)">
                  <span>{{ profile.name }}</span>
                  <span v-if="selectionOrder(profile.name)" class="order-badge">Urutan {{ selectionOrder(profile.name) }}</span>
                  <small v-if="profile.ready === false" class="muted profile-note">status informatif</small>
                </label>
              </div>
              <p class="muted helper-text">Scan hanya memberi informasi. TDL menentukan akses ketika file dikirim.</p>
            </template>
          </fieldset>

          <label>Chat tujuan
            <input v-model="chatRef" class="field" maxlength="2048" placeholder="ID, @username, tautan t.me, atau nomor telepon" :disabled="submitting">
          </label>

          <fieldset class="transfer-choice">
            <legend>Perilaku file</legend>
            <label class="mode-option"><input v-model="transferMode" type="radio" name="chat-send-mode" value="copy" :disabled="submitting"><span><strong>Copy</strong><small class="muted">File tetap di Workspace.</small></span></label>
            <label class="mode-option"><input v-model="transferMode" type="radio" name="chat-send-mode" value="move" :disabled="submitting"><span><strong>Move</strong><small class="muted">Sumber dihapus setelah TDL mengonfirmasi message ID.</small></span></label>
          </fieldset>

          <p v-if="activeProfiles.length" class="muted selected-profiles" aria-label="Urutan profil">Urutan: {{ activeProfiles.map((item) => item.name).join(' → ') }}</p>
          <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
          <p v-if="notice" class="notice notice-success" role="status">{{ notice }}</p>
          <button class="button" type="button" :disabled="submitting || profilesLoading || !availableWorkers.length" @click="submit">
            {{ submitting ? 'Mengirim job…' : 'Kirim ke Chat' }}
          </button>
        </div>
      </article>

      <article class="panel chat-send-folders">
        <header class="panel-heading"><div><p class="eyebrow">SUMBER FILE</p><h2>Folder Workspace</h2><p class="muted">Pilih satu atau beberapa folder. Isinya dikirim rekursif sebagai dokumen terpisah.</p></div></header>
        <div class="folder-content"><WorkspaceExplorer v-model:selected="folders" :worker="worker" /></div>
      </article>
    </section>

    <JobMonitor kind="chat_send" title="Riwayat Kirim ke Chat" :retryable="true" />
  </main>
</template>

<style scoped>
.chat-send-grid{display:grid;grid-template-columns:minmax(19rem,.82fr) minmax(25rem,1.18fr);gap:.85rem;align-items:start}
.chat-send-form,.chat-send-folders{min-width:0}
.chat-send-fields{display:grid;gap:.8rem;padding:.85rem}
.chat-send-fields>label,.profile-choice,.transfer-choice{display:grid;gap:.4rem;font-size:.72rem;font-weight:700}
.profile-choice,.transfer-choice{min-width:0;margin:0;padding:0;border:0}
.profile-choice legend,.transfer-choice legend{margin-bottom:.42rem;font-size:.72rem;font-weight:800}
.profile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.4rem}
.profile-option,.mode-option{display:flex;min-width:0;align-items:center;gap:.5rem;padding:.58rem .65rem;border:1px solid var(--line);border-radius:9px;background:var(--panel-soft);font-size:.7rem}
.profile-option>span:first-of-type{overflow:hidden;text-overflow:ellipsis}
.order-badge{margin-left:auto;white-space:nowrap;border-radius:999px;padding:.15rem .4rem;background:color-mix(in srgb,var(--brand) 17%,var(--panel));color:var(--ink);font-size:.58rem;font-weight:800}
.profile-note{margin-left:auto;white-space:nowrap;font-size:.58rem}
.helper-text,.selected-profiles{margin:0;font-size:.65rem}
.transfer-choice{grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem}
.transfer-choice legend{grid-column:1/-1}
.mode-option{align-items:flex-start}
.mode-option span{display:grid;gap:.2rem}
.mode-option small{font-size:.62rem;font-weight:400;line-height:1.4}
.folder-content{padding:.8rem}
.notice-success{border-color:color-mix(in srgb,var(--success) 35%,var(--line));color:var(--success)}
@media(max-width:850px){.chat-send-grid{grid-template-columns:1fr}}
@media(max-width:520px){.profile-grid,.transfer-choice{grid-template-columns:1fr}.transfer-choice legend{grid-column:auto}}
</style>
