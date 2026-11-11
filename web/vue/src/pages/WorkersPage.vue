<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { api, patch, post, put, remove } from "../lib/api";
import { session } from "../session";

type Worker = {
  name: string;
  url: string;
  public_url?: string;
  enabled?: boolean;
  selected?: boolean;
  healthy?: boolean;
  latency_ms?: number;
};
type WorkerSettings = {
  worker: string;
  worker_api_token_configured: boolean;
  job_stall_timeout_seconds: number;
  tdl_export_stall_timeout_seconds: number;
  tdl_download_stall_timeout_seconds: number;
  storage_profile: string;
  storage_profile_available: boolean;
  available_storage_profiles: string[];
  tts_helper_urls: string[];
  tts_part_retries: number;
  tts_retry_base_seconds: number;
  tts_newnym_after_retries: number;
};
type TtsDraft = {
  helper_urls: string;
  part_retries: string;
  retry_base_seconds: string;
  newnym_after_retries: string;
};
type WorkerOpsDraft = {
  job_stall: string;
  export_stall: string;
  download_stall: string;
};
type TtsHelperStatus =
  | "ready"
  | "bootstrapping"
  | "tor_unreachable"
  | "helper_unreachable";
type TtsHelper = {
  slot: number;
  status: TtsHelperStatus;
  bootstrap_percent: number | null;
  checked_at: string | null;
};
type TtsHealth = {
  worker: string;
  ready: boolean;
  helpers_ready: boolean;
  capability_ready: boolean;
  profile_session_ready: boolean;
  verified_profiles?: string[];
  reason_code: string;
  helpers: TtsHelper[];
};

const workers = ref<Worker[]>([]);
const workerDraft = reactive({ name: "", url: "", public_url: "", token: "" });
const message = ref("");
const failure = ref("");
const loading = ref(false);
const adding = ref(false);
const editing = ref<Worker | null>(null);
const deleting = ref<Worker | null>(null);
const editDraft = reactive({ url: "", public_url: "", token: "" });
const settingsOpen = ref("");
const workerSettings = ref<Record<string, WorkerSettings>>({});
const storageProfileDrafts = ref<Record<string, string>>({});
const ttsDrafts = ref<Record<string, TtsDraft>>({});
const opsDrafts = ref<Record<string, WorkerOpsDraft>>({});
const settingsLoading = reactive<Record<string, boolean>>({});
const settingsSaving = reactive<Record<string, boolean>>({});
const ttsHealth = ref<Record<string, TtsHealth>>({});
const ttsHealthLoading = reactive<Record<string, boolean>>({});
const ttsRecoveryLoading = reactive<Record<string, number | null>>({});

const selectedProfile = computed(
  () => session.current.actor?.profile || "-",
);

async function loadWorkers() {
  loading.value = true;
  failure.value = "";
  try {
    const result = await api<{ items?: Worker[] }>("/workers");
    workers.value = Array.isArray(result.items) ? result.items : [];
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Worker gagal dimuat.";
  } finally {
    loading.value = false;
  }
}

async function addWorker() {
  if (!workerDraft.name.trim() || !workerDraft.url.trim() || !workerDraft.token)
    return;
  adding.value = true;
  failure.value = "";
  try {
    await post("/workers", {
      name: workerDraft.name.trim(),
      url: workerDraft.url.trim(),
      public_url: workerDraft.public_url.trim(),
      token: workerDraft.token,
    });
    workerDraft.name = "";
    workerDraft.url = "";
    workerDraft.public_url = "";
    workerDraft.token = "";
    message.value = "Worker ditambahkan.";
    await loadWorkers();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Worker gagal ditambahkan.";
  } finally {
    adding.value = false;
  }
}

async function selectWorker(worker: Worker) {
  if (worker.enabled === false) return;
  failure.value = "";
  try {
    await session.chooseWorker(worker.name);
    message.value = `Job baru akan memakai ${worker.name}.`;
    await loadWorkers();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Route worker gagal diubah.";
  }
}

async function toggleWorker(worker: Worker) {
  failure.value = "";
  const enabled = worker.enabled === false;
  try {
    await patch(`/workers/${encodeURIComponent(worker.name)}`, { enabled });
    message.value = enabled
      ? `${worker.name} diaktifkan dan dapat menerima job baru.`
      : `${worker.name} dinonaktifkan. Job lama tetap berjalan.`;
    await loadWorkers();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Status worker gagal diubah.";
  }
}

function openEdit(worker: Worker) {
  editing.value = worker;
  editDraft.url = worker.url;
  editDraft.public_url = worker.public_url || "";
  editDraft.token = "";
}

async function saveWorkerEdit() {
  if (!editing.value || !editDraft.url.trim()) return;
  const target = editing.value;
  failure.value = "";
  try {
    await put(`/workers/${encodeURIComponent(target.name)}`, {
      url: editDraft.url.trim(),
      public_url: editDraft.public_url.trim(),
      token: editDraft.token,
    });
    editing.value = null;
    message.value = `Worker ${target.name} diperbarui.`;
    await loadWorkers();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Worker gagal diperbarui.";
  }
}

async function deleteWorker() {
  if (!deleting.value) return;
  const target = deleting.value;
  failure.value = "";
  try {
    await remove(`/workers/${encodeURIComponent(target.name)}`);
    deleting.value = null;
    message.value = `Worker ${target.name} dihapus dari registry.`;
    await loadWorkers();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Worker gagal dihapus.";
  }
}

function parseList(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function loadWorkerSettings(worker: Worker) {
  settingsLoading[worker.name] = true;
  failure.value = "";
  try {
    const result = await api<WorkerSettings>(
      `/workers/${encodeURIComponent(worker.name)}/settings`,
    );
    workerSettings.value = { ...workerSettings.value, [worker.name]: result };
    storageProfileDrafts.value = {
      ...storageProfileDrafts.value,
      [worker.name]: result.storage_profile,
    };
    opsDrafts.value = {
      ...opsDrafts.value,
      [worker.name]: {
        job_stall: String(result.job_stall_timeout_seconds ?? 600),
        export_stall: String(result.tdl_export_stall_timeout_seconds ?? 300),
        download_stall: String(
          result.tdl_download_stall_timeout_seconds ?? 300,
        ),
      },
    };
    ttsDrafts.value = {
      ...ttsDrafts.value,
      [worker.name]: {
        helper_urls: (result.tts_helper_urls || []).join(", "),
        part_retries: String(result.tts_part_retries ?? 4),
        retry_base_seconds: String(result.tts_retry_base_seconds ?? 2),
        newnym_after_retries: String(result.tts_newnym_after_retries ?? 3),
      },
    };
  } catch (cause) {
    failure.value =
      cause instanceof Error
        ? cause.message
        : "Pengaturan runtime worker gagal dimuat.";
  } finally {
    settingsLoading[worker.name] = false;
  }
}

async function toggleSettings(worker: Worker) {
  if (settingsOpen.value === worker.name) {
    settingsOpen.value = "";
    return;
  }
  settingsOpen.value = worker.name;
  if (!workerSettings.value[worker.name]) await loadWorkerSettings(worker);
}

async function refreshWorkerSettings(worker: Worker) {
  const next = { ...workerSettings.value };
  delete next[worker.name];
  workerSettings.value = next;
  await loadWorkerSettings(worker);
}

async function saveStorageProfile(worker: Worker) {
  const storage_profile = storageProfileDrafts.value[worker.name];
  if (!storage_profile) return;
  settingsSaving[worker.name] = true;
  failure.value = "";
  try {
    const result = await put<WorkerSettings>(
      `/workers/${encodeURIComponent(worker.name)}/settings`,
      { storage_profile },
    );
    workerSettings.value = { ...workerSettings.value, [worker.name]: result };
    storageProfileDrafts.value = {
      ...storageProfileDrafts.value,
      [worker.name]: result.storage_profile,
    };
    message.value = `Profil Storage worker ${worker.name} disimpan.`;
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Profil Storage gagal disimpan.";
  } finally {
    settingsSaving[worker.name] = false;
  }
}

async function saveOperationalSettings(worker: Worker) {
  const draft = opsDrafts.value[worker.name];
  if (!draft) return;
  settingsSaving[worker.name] = true;
  failure.value = "";
  try {
    const result = await put<WorkerSettings>(
      `/workers/${encodeURIComponent(worker.name)}/settings`,
      {
        job_stall_timeout_seconds: Number(draft.job_stall),
        tdl_export_stall_timeout_seconds: Number(draft.export_stall),
        tdl_download_stall_timeout_seconds: Number(draft.download_stall),
      },
    );
    workerSettings.value = { ...workerSettings.value, [worker.name]: result };
    message.value = `Timeout worker ${worker.name} disimpan untuk job berikutnya.`;
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Timeout worker gagal disimpan.";
  } finally {
    settingsSaving[worker.name] = false;
  }
}

function updateTtsDraft(worker: Worker, values: Partial<TtsDraft>) {
  const current = ttsDrafts.value[worker.name];
  if (!current) return;
  ttsDrafts.value = {
    ...ttsDrafts.value,
    [worker.name]: { ...current, ...values },
  };
}

async function saveTtsSettings(worker: Worker) {
  const draft = ttsDrafts.value[worker.name];
  if (!draft) return;
  settingsSaving[worker.name] = true;
  failure.value = "";
  try {
    const result = await put<WorkerSettings>(
      `/workers/${encodeURIComponent(worker.name)}/settings`,
      {
        tts_helper_urls: parseList(draft.helper_urls),
        tts_part_retries: Number(draft.part_retries),
        tts_retry_base_seconds: Number(draft.retry_base_seconds),
        tts_newnym_after_retries: Number(draft.newnym_after_retries),
      },
    );
    workerSettings.value = { ...workerSettings.value, [worker.name]: result };
    message.value = `Pengaturan TTS worker ${worker.name} disimpan untuk job berikutnya.`;
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Pengaturan TTS gagal disimpan.";
  } finally {
    settingsSaving[worker.name] = false;
  }
}

async function refreshTtsHealth(worker: Worker) {
  ttsHealthLoading[worker.name] = true;
  failure.value = "";
  try {
    ttsHealth.value = {
      ...ttsHealth.value,
      [worker.name]: await api<TtsHealth>(
        `/workers/${encodeURIComponent(worker.name)}/tts/health`,
      ),
    };
  } catch (cause) {
    failure.value =
      cause instanceof Error
        ? cause.message
        : `Diagnosis TTS ${worker.name} gagal dimuat.`;
  } finally {
    ttsHealthLoading[worker.name] = false;
  }
}

async function recoverTtsHelper(worker: Worker, slot: number) {
  ttsRecoveryLoading[worker.name] = slot;
  failure.value = "";
  try {
    await post(
      `/workers/${encodeURIComponent(worker.name)}/tts/helpers/${slot}/recover`,
      {},
    );
    message.value = `Pemulihan Tor helper ${slot} pada ${worker.name} dimulai. Periksa ulang status secara manual.`;
    const current = ttsHealth.value[worker.name];
    if (current) {
      ttsHealth.value = {
        ...ttsHealth.value,
        [worker.name]: {
          ...current,
          ready: false,
          helpers_ready: false,
          helpers: current.helpers.map((helper) =>
            helper.slot === slot
              ? { ...helper, status: "bootstrapping", bootstrap_percent: 0 }
              : helper,
          ),
        },
      };
    }
  } catch (cause) {
    failure.value =
      cause instanceof Error
        ? cause.message
        : `Pemulihan helper ${slot} gagal dimulai.`;
  } finally {
    ttsRecoveryLoading[worker.name] = null;
  }
}

function ttsStatusLabel(status: TtsHelperStatus) {
  return {
    ready: "Siap",
    bootstrapping: "Tor sedang memulai",
    tor_unreachable: "Tor tidak terjangkau",
    helper_unreachable: "Helper tidak terjangkau",
  }[status];
}

function contextChanged() {
  void loadWorkers();
}

onMounted(() => {
  void loadWorkers();
  window.addEventListener("tme3:context-changed", contextChanged);
});
onUnmounted(() => window.removeEventListener("tme3:context-changed", contextChanged));
</script>

<template>
  <main class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">WORKERS</p>
        <h1>Worker &amp; routing</h1>
        <p class="muted">
          Route baru hanya berlaku untuk job berikutnya; job lama tetap pada
          worker asal.
        </p>
      </div>
      <span class="status-pill status-neutral">Profil aktif · {{ selectedProfile }}</span>
    </header>

    <p v-if="message" class="notice notice-success" role="status">{{ message }}</p>
    <p v-if="failure" class="notice notice-error" role="alert">{{ failure }}</p>

    <div class="worker-layout">
      <section class="panel">
        <div class="panel-heading"><h2>Tambah worker</h2></div>
        <form class="form-grid worker-add-form" @submit.prevent="addWorker">
          <label>Nama<input v-model="workerDraft.name" class="field" placeholder="remote-1" autocomplete="off" /></label>
          <label>URL API<input v-model="workerDraft.url" class="field" placeholder="https://worker.example.com" /></label>
          <label>Domain link publik<input v-model="workerDraft.public_url" class="field" placeholder="https://worker.example.com" /><small class="muted">Origin HTTPS yang melayani route unduhan publik worker.</small></label>
          <label>Token<input v-model="workerDraft.token" class="field" type="password" autocomplete="new-password" /></label>
          <button class="button button-primary" type="submit" :disabled="adding || !workerDraft.name || !workerDraft.url || !workerDraft.token">{{ adding ? "Menambahkan…" : "Tambahkan worker" }}</button>
        </form>
      </section>

      <section class="panel workers-panel">
        <header class="panel-heading">
          <div><h2>Registry worker</h2><p class="muted">Admission hanya mengatur job baru. Job lama tetap pada worker asal.</p></div>
          <button class="button button-secondary button-small" type="button" :disabled="loading" @click="loadWorkers">{{ loading ? "Memuat…" : "Refresh" }}</button>
        </header>
        <p v-if="loading && !workers.length" class="empty-state" role="status">Memuat worker…</p>
        <p v-else-if="!workers.length" class="empty-state">Belum ada worker.</p>
        <article v-for="worker in workers" :key="worker.name" class="worker-row">
          <div class="worker-summary">
            <div class="worker-title">
              <strong>{{ worker.name }}</strong>
              <span v-if="worker.selected" class="status-pill status-ready">Route aktif</span>
              <span class="status-pill" :class="worker.enabled === false ? 'status-failed' : 'status-ready'">{{ worker.enabled === false ? "Nonaktif" : "Aktif" }}</span>
            </div>
            <p class="muted worker-url">{{ worker.url }}</p>
            <p class="muted worker-url">Domain link publik: {{ worker.public_url || "belum diatur" }}</p>
            <small class="muted">{{ worker.enabled === false ? "Tidak menerima job baru; job lama tidak dihentikan." : "Admission job aktif; kesiapan TTS diperiksa terpisah." }}</small>
          </div>
          <div class="worker-actions">
            <button class="button button-secondary button-small" type="button" :disabled="worker.selected || worker.enabled === false" @click="selectWorker(worker)">Pilih</button>
            <button class="button button-secondary button-small" type="button" @click="toggleWorker(worker)">{{ worker.enabled === false ? "Aktifkan" : "Nonaktifkan" }}</button>
            <button class="button button-secondary button-small" type="button" :aria-expanded="settingsOpen === worker.name" @click="toggleSettings(worker)">{{ settingsOpen === worker.name ? "Tutup runtime" : "Runtime" }}</button>
            <button class="button button-secondary button-small" type="button" :aria-label="`Edit worker ${worker.name}`" @click="openEdit(worker)">Edit</button>
            <button class="button button-danger button-small" type="button" :aria-label="`Hapus worker ${worker.name}`" @click="deleting = worker">Hapus</button>
          </div>
          <section v-if="settingsOpen === worker.name" class="runtime-settings">
            <header class="operation-heading"><h3>Pengaturan runtime worker</h3><button class="button button-secondary button-small" type="button" aria-label="Muat ulang pengaturan worker" :disabled="settingsLoading[worker.name]" @click="refreshWorkerSettings(worker)">Muat ulang</button></header>
            <p class="muted">Profil Storage dan TTS berlaku untuk job baru. Token API: {{ workerSettings[worker.name]?.worker_api_token_configured ? "sudah diatur" : "belum diatur" }}; token baru bisa dirotasi dari Edit tanpa menampilkan nilai aktif.</p>
            <p v-if="settingsLoading[worker.name]" class="empty-state" role="status">Memuat pengaturan…</p>
            <template v-else-if="workerSettings[worker.name]">
              <div v-if="!workerSettings[worker.name].storage_profile_available" class="notice notice-warning">Profil aktif “{{ workerSettings[worker.name].storage_profile }}” belum memiliki sesi TDL Storage. Siapkan sesi Storage satu kali di mesin worker, lalu muat ulang pengaturan.</div>
              <div class="form-grid runtime-form">
                <label>Profil sesi Storage<select v-model="storageProfileDrafts[worker.name]" class="field"><option value="" disabled>Pilih profil dengan sesi aktif</option><option v-for="profile in workerSettings[worker.name].available_storage_profiles" :key="profile" :value="profile">{{ profile }}</option></select></label>
                <button class="button button-primary" type="button" :disabled="!storageProfileDrafts[worker.name] || settingsSaving[worker.name] || storageProfileDrafts[worker.name] === workerSettings[worker.name].storage_profile" @click="saveStorageProfile(worker)">{{ settingsSaving[worker.name] ? "Menyimpan…" : "Simpan profil Storage" }}</button>
              </div>
              <p v-if="!workerSettings[worker.name].available_storage_profiles.length" class="muted">Belum ada sesi Storage yang siap dipilih pada worker ini.</p>

              <section class="runtime-subsection">
                <div class="operation-heading"><div><h4>Mesin TTS</h4><p class="muted">Setiap helper menjalankan Tor lokal. Diagnosis hanya berjalan saat diminta.</p></div><button class="button button-secondary button-small" type="button" :aria-label="`Periksa ulang TTS ${worker.name}`" :disabled="ttsHealthLoading[worker.name]" @click="refreshTtsHealth(worker)">{{ ttsHealthLoading[worker.name] ? "Memeriksa…" : "Periksa ulang" }}</button></div>
                <template v-if="ttsHealth[worker.name]">
                  <p class="muted">Status job TTS: {{ ttsHealth[worker.name].ready ? "siap" : ttsHealth[worker.name].reason_code }} · Helper/Tor: {{ ttsHealth[worker.name].helpers_ready ? "siap" : "belum siap" }} · Profil yang terverifikasi mengirim: {{ ttsHealth[worker.name].verified_profiles?.length ? ttsHealth[worker.name].verified_profiles.join(", ") : "belum ada" }}</p>
                  <a class="muted" href="/api/v1/diagnostics/tts/logs?limit=100" target="_blank" rel="noreferrer">Log diagnosis TTS JSON</a>
                  <div class="helper-grid">
                    <article v-for="helper in ttsHealth[worker.name].helpers" :key="helper.slot" class="helper-card" :data-testid="`tts-helper-${worker.name}-${helper.slot}`">
                      <div class="operation-heading"><strong>Helper {{ helper.slot }}</strong><span>{{ ttsStatusLabel(helper.status) }}</span></div>
                      <p v-if="helper.status === 'bootstrapping'" class="muted">{{ helper.bootstrap_percent === null ? "Menunggu Tor aktif" : `Bootstrap ${helper.bootstrap_percent}%` }}</p>
                      <p v-if="helper.status === 'helper_unreachable'" class="muted">Helper tidak merespons. Restart container perlu dilakukan operator pada host.</p>
                      <button v-if="helper.status === 'tor_unreachable' || helper.status === 'bootstrapping'" class="button button-secondary button-small" type="button" :aria-label="`Pulihkan helper ${helper.slot} ${worker.name}`" :disabled="ttsRecoveryLoading[worker.name] !== undefined && ttsRecoveryLoading[worker.name] !== null" @click="recoverTtsHelper(worker, helper.slot)">{{ ttsRecoveryLoading[worker.name] === helper.slot ? "Meminta pemulihan…" : "Pulihkan Tor" }}</button>
                    </article>
                  </div>
                </template>
                <p v-else class="empty-state">Belum diperiksa.</p>
                <div class="form-grid runtime-form">
                  <label>URL tiga helper gTTS<textarea class="field" rows="3" :value="ttsDrafts[worker.name]?.helper_urls" placeholder="http://tts-1:5000, http://tts-2:5000, http://tts-3:5000" @input="updateTtsDraft(worker, { helper_urls: ($event.target as HTMLTextAreaElement).value })" /></label>
                  <label>Retry per bagian<input class="field" type="number" min="0" max="10" :value="ttsDrafts[worker.name]?.part_retries" @input="updateTtsDraft(worker, { part_retries: ($event.target as HTMLInputElement).value })" /></label>
                  <label>Backoff awal (detik)<input class="field" type="number" min="0.1" max="60" step="0.1" :value="ttsDrafts[worker.name]?.retry_base_seconds" @input="updateTtsDraft(worker, { retry_base_seconds: ($event.target as HTMLInputElement).value })" /></label>
                  <label>Rotasi circuit setelah retry<input class="field" type="number" min="1" max="20" :value="ttsDrafts[worker.name]?.newnym_after_retries" @input="updateTtsDraft(worker, { newnym_after_retries: ($event.target as HTMLInputElement).value })" /></label>
                </div>
                <button class="button button-primary" type="button" :disabled="settingsSaving[worker.name]" @click="saveTtsSettings(worker)">{{ settingsSaving[worker.name] ? "Menyimpan…" : "Simpan pengaturan TTS" }}</button>
              </section>

              <section class="runtime-subsection">
                <h4>Timeout job worker</h4>
                <p class="muted">Angka 0 menonaktifkan batas stall. Perubahan hanya berlaku untuk job berikutnya dan ditolak saat worker sedang menjalankan job.</p>
                <div class="form-grid runtime-form three-columns">
                  <label>Semua job<input class="field" type="number" min="0" max="86400" :value="opsDrafts[worker.name]?.job_stall" @input="opsDrafts[worker.name] = { ...opsDrafts[worker.name], job_stall: ($event.target as HTMLInputElement).value }" /></label>
                  <label>Export TDL<input class="field" type="number" min="0" max="86400" :value="opsDrafts[worker.name]?.export_stall" @input="opsDrafts[worker.name] = { ...opsDrafts[worker.name], export_stall: ($event.target as HTMLInputElement).value }" /></label>
                  <label>Download TDL<input class="field" type="number" min="0" max="86400" :value="opsDrafts[worker.name]?.download_stall" @input="opsDrafts[worker.name] = { ...opsDrafts[worker.name], download_stall: ($event.target as HTMLInputElement).value }" /></label>
                </div>
                <button class="button button-primary" type="button" :disabled="settingsSaving[worker.name]" @click="saveOperationalSettings(worker)">{{ settingsSaving[worker.name] ? "Menyimpan…" : "Simpan timeout" }}</button>
              </section>
            </template>
          </section>
        </article>
      </section>
    </div>

    <div v-if="editing" class="modal-backdrop" @click.self="editing = null">
      <section class="modal-card" role="dialog" aria-modal="true" :aria-label="`Edit ${editing.name}`">
        <header class="modal-heading"><h2>Edit {{ editing.name }}</h2><button class="icon-button" aria-label="Tutup edit worker" @click="editing = null">×</button></header>
        <div class="form-grid">
          <label>URL API<input v-model="editDraft.url" class="field" /></label>
          <label>Domain link publik<input v-model="editDraft.public_url" class="field" placeholder="https://worker.example.com" /><small class="muted">Kosongkan untuk menonaktifkan penerbitan link baru.</small></label>
          <label>Token API baru<input v-model="editDraft.token" class="field" type="password" autocomplete="new-password" placeholder="Kosongkan agar tetap sama" /></label>
        </div>
        <p class="muted">Token worker dirotasi melalui koneksi internal. Jika koneksi sama, perubahan langsung berlaku di worker dan gateway.</p>
        <footer class="modal-actions"><button class="button button-secondary" @click="editing = null">Batal</button><button class="button button-primary" :disabled="!editDraft.url" @click="saveWorkerEdit">Simpan</button></footer>
      </section>
    </div>
    <div v-if="deleting" class="modal-backdrop" @click.self="deleting = null">
      <section class="modal-card" role="dialog" aria-modal="true" aria-label="Hapus worker">
        <header class="modal-heading"><h2>Hapus worker?</h2><button class="icon-button" aria-label="Tutup hapus worker" @click="deleting = null">×</button></header>
        <p>Worker <strong>{{ deleting.name }}</strong> akan dihapus dari registry. Job yang sudah dibuat tidak dipindahkan.</p>
        <footer class="modal-actions"><button class="button button-secondary" @click="deleting = null">Batal</button><button class="button button-danger" @click="deleteWorker">Hapus</button></footer>
      </section>
    </div>
  </main>
</template>

<style scoped>
.worker-layout { display:grid; gap:1rem; grid-template-columns:minmax(17rem,.72fr) minmax(0,1.28fr); align-items:start; }
.worker-add-form { padding:1rem; }
.workers-panel { overflow:hidden; }
.worker-row { display:grid; gap:.7rem; padding:1rem; border-bottom:1px solid var(--line); }
.worker-row:last-child { border-bottom:0; }
.worker-title,.worker-actions,.operation-heading { display:flex; align-items:center; justify-content:space-between; gap:.5rem; flex-wrap:wrap; }
.worker-url { margin:.2rem 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.worker-actions { justify-content:flex-start; }
.runtime-settings { display:grid; gap:.8rem; padding:1rem; border-top:1px solid var(--line); background:var(--panel-soft); }
.runtime-settings h3,.runtime-settings h4 { margin:0; }
.runtime-form { align-items:end; }
.three-columns { grid-template-columns:repeat(3,minmax(0,1fr)); }
.runtime-subsection { display:grid; gap:.7rem; padding-top:.8rem; border-top:1px solid var(--line); }
.helper-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(10rem,1fr)); gap:.5rem; }
.helper-card { display:grid; gap:.35rem; padding:.65rem; border:1px solid var(--line); border-radius:.65rem; background:var(--panel); }
.form-grid label { display:grid; gap:.3rem; }
@media (max-width: 900px) { .worker-layout { grid-template-columns:1fr; } }
@media (max-width: 600px) { .three-columns { grid-template-columns:1fr; } }
</style>
