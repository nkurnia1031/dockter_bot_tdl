<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../lib/api";

type Worker = {
  name: string;
  enabled: boolean;
  online: boolean;
  secure: boolean;
};
type WorkerState = {
  worker: string;
  status: string;
  error?: string;
  desired_revision?: number | null;
  installed_revision?: number | null;
  updated_at?: string;
};
type Profile = {
  name: string;
  status: string;
  vault: boolean;
  source?: string;
  operation_id?: string;
  desired_revision?: number;
  error?: string;
  workers: WorkerState[];
};
type DistributionWorker = {
  worker: string;
  status: string;
  phase: string;
  reason_code: string;
  archive_message_id?: number | null;
  updated_at: string;
};
type DistributionOperation = {
  id: string;
  profile: string;
  revision: number;
  target_workers: string[];
  status: string;
  created_at: string;
  updated_at: string;
  workers: DistributionWorker[];
};
type DistributionEvents = {
  items: Array<{
    id: number;
    worker: string;
    sequence: number | null;
    phase: string;
    status: string;
    code: string;
    created_at: string;
  }>;
  active: boolean;
  next_after_id: number;
};

const profiles = ref<Profile[]>([]);
const workers = ref<Worker[]>([]);
const loading = ref(false);
const failure = ref("");
const notice = ref("");
const checkedAt = ref("");
const deletingProfile = ref("");
const distributionBusy = ref("");
const distributionOperations = ref<Record<string, DistributionOperation[]>>({});
const distributionEvents = ref<Record<string, DistributionEvents>>({});
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let loadGeneration = 0;
const vaultedProfiles = computed(() =>
  profiles.value.filter((profile) => profile.vault),
);
const hasActiveDistribution = computed(() =>
  Object.values(distributionOperations.value)
    .flat()
    .some((operation) =>
      ["queued", "running", "waiting"].includes(operation.status),
    ),
);

const statusLabel = (status: string) =>
  (
    ({
      ready: "Tersimpan pada worker",
      stored: "Tersimpan di Vault",
      queued: "Dalam antrean",
      running: "Berjalan",
      waiting: "Menunggu worker",
      waiting_worker: "Menunggu worker",
      active: "Aktif di Vault",
      succeeded: "Selesai",
      cancelled: "Dibatalkan",
      not_assigned: "Belum ditugaskan",
      worker_unavailable: "Worker tidak terjangkau",
      worker_update_required: "Perlu diperbarui",
      failed: "Gagal",
      unavailable: "Tidak tersedia",
    }) as Record<string, string>
  )[status] ||
  status ||
  "Belum diperiksa";
const phaseLabel = (phase: string) =>
  (
    ({
      queued: "Antrean",
      archive_upload: "Unggah arsip terenkripsi",
      archive_download: "Unduh arsip dari channel",
      bundle_validation: "Validasi bundle",
      session_validation: "Validasi sesi",
      session_install: "Pasang sesi",
      session_commit: "Simpan sesi",
      download_staging: "Siapkan lane Download",
      download_validation: "Validasi lane Download",
      download_install: "Pasang lane Download",
      export_staging: "Siapkan lane Export",
      export_validation: "Validasi lane Export",
      export_install: "Pasang lane Export",
      upload_staging: "Salin lane Upload",
      upload_validation: "Validasi lane Upload",
      upload_install: "Pasang lane Upload",
      identity_install: "Pasang metadata identitas",
      transaction_rollback: "Pulihkan seluruh lane",
      installation_reused: "Pemasangan sudah tercatat",
      worker_unreachable: "Worker tidak terjangkau",
      worker_dispatch: "Kirim perintah ke worker",
      completed: "Selesai",
      cancelled: "Dibatalkan",
      failed: "Gagal",
    }) as Record<string, string>
  )[phase] || phase;

function stopPolling() {
  if (pollTimer !== undefined) clearTimeout(pollTimer);
  pollTimer = undefined;
}
function schedulePolling() {
  stopPolling();
  if (hasActiveDistribution.value)
    pollTimer = setTimeout(() => void loadDistributionOperations(), 3000);
}
function idempotencyKey() {
  return typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `profile-distribution-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function loadDistributionOperations(generation = loadGeneration) {
  const vaulted = profiles.value.filter((profile) => profile.vault);
  await Promise.all(
    vaulted.map(async (profile) => {
      try {
        const result = await api<{ items: DistributionOperation[] }>(
          `/profiles/${encodeURIComponent(profile.name)}/distributions`,
        );
        if (generation !== loadGeneration) return;
        const items = Array.isArray(result.items) ? result.items : [];
        distributionOperations.value = {
          ...distributionOperations.value,
          [profile.name]: items,
        };
        await Promise.all(
          items.map(async (operation) => {
            try {
              const events = await api<DistributionEvents>(
                `/profile-distributions/${encodeURIComponent(operation.id)}/events?limit=100`,
              );
              if (generation === loadGeneration)
                distributionEvents.value = {
                  ...distributionEvents.value,
                  [operation.id]: events,
                };
            } catch {
              if (generation === loadGeneration)
                distributionEvents.value = {
                  ...distributionEvents.value,
                  [operation.id]: {
                    items: [],
                    active: false,
                    next_after_id: 0,
                  },
                };
            }
          }),
        );
      } catch {
        if (generation === loadGeneration)
          distributionOperations.value = {
            ...distributionOperations.value,
            [profile.name]: [],
          };
      }
    }),
  );
  if (generation === loadGeneration) schedulePolling();
}

async function load() {
  const generation = ++loadGeneration;
  loading.value = true;
  failure.value = "";
  try {
    const result = await api<{ items: Profile[]; workers: Worker[] }>(
      "/profiles/management",
    );
    if (generation !== loadGeneration) return;
    profiles.value = Array.isArray(result.items) ? result.items : [];
    workers.value = Array.isArray(result.workers) ? result.workers : [];
    checkedAt.value = new Date().toLocaleString();
    await loadDistributionOperations(generation);
  } catch (cause) {
    if (generation === loadGeneration)
      failure.value =
        cause instanceof Error ? cause.message : "Status Vault gagal dimuat.";
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}

async function distribute(profile: Profile) {
  if (distributionBusy.value) return;
  distributionBusy.value = profile.name;
  failure.value = "";
  notice.value = "";
  try {
    const operation = await api<DistributionOperation>(
      `/profiles/${encodeURIComponent(profile.name)}/distributions`,
      { method: "POST", headers: { "Idempotency-Key": idempotencyKey() } },
    );
    notice.value = `Distribusi ${profile.name} revision ${operation.revision} masuk antrean (${operation.id}).`;
    await loadDistributionOperations();
  } catch (cause) {
    failure.value =
      cause instanceof Error
        ? cause.message
        : `Distribusi ${profile.name} gagal dimulai.`;
  } finally {
    distributionBusy.value = "";
  }
}

async function retryDistribution(
  operation: DistributionOperation,
  worker: string,
) {
  const key = `${operation.id}:${worker}`;
  if (distributionBusy.value) return;
  distributionBusy.value = key;
  failure.value = "";
  notice.value = "";
  try {
    await api(
      `/profile-distributions/${encodeURIComponent(operation.id)}/workers/${encodeURIComponent(worker)}/retry`,
      { method: "POST", headers: { "Idempotency-Key": idempotencyKey() } },
    );
    notice.value = `Retry ${worker} masuk antrean pada revision ${operation.revision}.`;
    await loadDistributionOperations();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : `Retry ${worker} gagal dimulai.`;
  } finally {
    distributionBusy.value = "";
  }
}

async function deleteBundle(profile: Profile) {
  if (deletingProfile.value) return;
  if (
    !window.confirm(
      `Hapus bundle terenkripsi "${profile.name}" dari Vault? Sesi pada worker lokal tidak akan dihapus atau diubah.`,
    )
  )
    return;
  deletingProfile.value = profile.name;
  failure.value = "";
  notice.value = "";
  try {
    await api(`/profiles/${encodeURIComponent(profile.name)}/vault`, {
      method: "DELETE",
    });
    profiles.value = profiles.value.map((item) =>
      item.name === profile.name
        ? {
            ...item,
            vault: false,
            status: "legacy",
            workers: [],
            error: undefined,
          }
        : item,
    );
    notice.value = `Bundle ${profile.name} dihapus dari Vault. Sesi worker lokal tetap utuh.`;
  } catch (cause) {
    failure.value =
      cause instanceof Error
        ? cause.message
        : `Bundle ${profile.name} gagal dihapus dari Vault.`;
  } finally {
    deletingProfile.value = "";
  }
}

onMounted(() => {
  void load();
});
onUnmounted(() => {
  loadGeneration += 1;
  stopPolling();
});
</script>

<template>
  <main class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">PROFIL BERSAMA</p>
        <h1>Vault profil</h1>
        <p class="muted">
          Simpan profil aktif di satu tempat dan distribusikan salinannya ke
          worker.
        </p>
      </div>
      <div class="heading-actions">
        <RouterLink class="button button-secondary" to="/profiles/"
          >Profil lokal</RouterLink
        ><button
          class="button button-secondary"
          type="button"
          aria-label="Muat ulang status Vault"
          :disabled="loading"
          @click="load"
        >
          {{ loading ? "Memuat…" : "Muat ulang" }}
        </button>
      </div>
    </header>
    <div v-if="failure" class="notice notice-error" role="alert">
      {{ failure }}
    </div>
    <p v-if="notice" class="notice notice-success" role="status">
      {{ notice }}
    </p>
    <section class="panel vault-panel" aria-label="Status Vault">
      <header class="panel-heading">
        <div>
          <h2>Profil dan distribusi worker</h2>
          <p class="muted">
            Profil aktif setelah disimpan. Status pemasangan hanya informasi dan
            tidak menahan job.
          </p>
        </div>
        <span v-if="checkedAt" class="muted">Diperiksa {{ checkedAt }}</span>
      </header>
      <div v-if="loading && !profiles.length" class="empty-state">
        Memuat status Vault…
      </div>
      <div v-else-if="!vaultedProfiles.length" class="empty-state">
        Belum ada profil yang tersimpan di Vault.
      </div>
      <div v-else class="vault-list">
        <article
          v-for="profile in vaultedProfiles"
          :key="profile.name"
          class="vault-profile"
        >
          <div class="vault-profile-heading">
            <h3>{{ profile.name }}</h3>
            <div class="heading-actions">
              <span class="status-pill status-neutral">{{
                statusLabel(profile.status)
              }}</span
              ><button
                v-if="profile.desired_revision && workers.length"
                class="button button-primary"
                type="button"
                :disabled="Boolean(distributionBusy)"
                :aria-label="`Distribusikan ${profile.name} revision ${profile.desired_revision} ke semua worker`"
                @click="distribute(profile)"
              >
                {{
                  distributionBusy === profile.name
                    ? "Mengantrikan…"
                    : `Distribusikan r${profile.desired_revision}`
                }}</button
              ><button
                class="button button-secondary"
                type="button"
                :disabled="Boolean(deletingProfile)"
                :aria-label="`Hapus bundle ${profile.name} dari Vault`"
                @click="deleteBundle(profile)"
              >
                {{
                  deletingProfile === profile.name
                    ? "Menghapus…"
                    : "Hapus dari Vault"
                }}
              </button>
            </div>
          </div>
          <p v-if="profile.error" class="notice notice-error">
            {{ profile.error }}
          </p>
          <section
            v-for="operation in (
              distributionOperations[profile.name] || []
            ).slice(0, 3)"
            :key="operation.id"
            class="distribution-operation"
            :aria-label="`Operasi distribusi ${profile.name} revision ${operation.revision}`"
          >
            <div class="operation-heading">
              <div>
                <strong>Distribusi revision {{ operation.revision }}</strong>
                <p class="muted">
                  ID {{ operation.id }} · snapshot:
                  {{ operation.target_workers.join(", ") }}
                </p>
              </div>
              <span
                class="status-pill"
                :class="
                  ['failed'].includes(operation.status)
                    ? 'status-failed'
                    : ['succeeded', 'stored'].includes(operation.status)
                      ? 'status-ready'
                      : 'status-running'
                "
                >{{ statusLabel(operation.status) }}</span
              >
            </div>
            <div class="distribution-workers">
              <article
                v-for="target in operation.workers"
                :key="target.worker"
                class="distribution-worker"
              >
                <div class="operation-heading">
                  <strong>{{ target.worker }}</strong
                  ><span
                    >{{ statusLabel(target.status) }} ·
                    {{ phaseLabel(target.phase) }}</span
                  >
                </div>
                <p v-if="target.reason_code" class="failure-code">
                  {{ target.reason_code }}
                </p>
                <button
                  v-if="target.status === 'failed'"
                  class="button button-secondary button-small"
                  type="button"
                  :disabled="Boolean(distributionBusy)"
                  :aria-label="`Retry distribusi ${operation.id} pada ${target.worker}`"
                  @click="retryDistribution(operation, target.worker)"
                >
                  {{
                    distributionBusy === `${operation.id}:${target.worker}`
                      ? "Mengantrikan…"
                      : "Retry worker"
                  }}
                </button>
                <ol
                  v-if="
                    distributionEvents[operation.id]?.items.some(
                      (event) => event.worker === target.worker,
                    )
                  "
                  class="event-list"
                >
                  <li
                    v-for="event in (
                      distributionEvents[operation.id]?.items || []
                    )
                      .filter((item) => item.worker === target.worker)
                      .slice(-5)
                      .reverse()"
                    :key="event.id"
                  >
                    {{ phaseLabel(event.phase) }} ·
                    {{ statusLabel(event.status)
                    }}<span v-if="event.code" class="muted">
                      ({{ event.code }})</span
                    ><time>{{
                      new Date(event.created_at).toLocaleTimeString()
                    }}</time>
                  </li>
                </ol>
              </article>
            </div>
          </section>
          <p
            v-if="
              profile.workers.length === 0 &&
              !distributionOperations[profile.name]?.length
            "
            class="muted"
          >
            Belum ada status distribusi worker untuk profil ini.
          </p>
          <div v-else class="distribution-workers">
            <article
              v-for="item in profile.workers"
              :key="`${profile.name}:${item.worker}`"
              class="distribution-worker"
            >
              <div class="operation-heading">
                <strong>{{ item.worker }}</strong
                ><span>{{ statusLabel(item.status) }}</span>
              </div>
              <p class="muted">
                Revision terpasang {{ item.installed_revision ?? "-" }} dari
                {{ item.desired_revision ?? profile.desired_revision ?? "-"
                }}<template v-if="item.updated_at">
                  · {{ new Date(item.updated_at).toLocaleString() }}</template
                >
              </p>
              <p v-if="item.error" class="failure-code">{{ item.error }}</p>
            </article>
          </div>
        </article>
      </div>
      <p class="muted vault-foot">
        Menghapus bundle hanya mengosongkan Vault; sesi pada worker lokal tetap
        ada. Status distribusi bukan gate job.
      </p>
    </section>
  </main>
</template>

<style scoped>
.vault-panel {
  padding: 1rem;
}
.vault-panel > .panel-heading {
  padding: 0 0 1rem;
  border-bottom: 1px solid var(--line);
}
.panel-heading h2 {
  margin: 0;
  font-size: 1rem;
}
.panel-heading p {
  margin: 0.35rem 0 0;
}
.vault-list {
  display: grid;
  gap: 0.8rem;
  margin-top: 0.8rem;
}
.vault-profile {
  display: grid;
  gap: 0.75rem;
  padding: 0.9rem;
  border: 1px solid var(--line);
  border-radius: 0.85rem;
  background: var(--panel-soft);
}
.vault-profile-heading,
.operation-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.vault-profile-heading h3 {
  margin: 0;
  font-size: 0.95rem;
}
.vault-profile-heading .heading-actions {
  gap: 0.4rem;
}
.distribution-operation {
  display: grid;
  gap: 0.65rem;
  padding: 0.75rem;
  border: 1px solid color-mix(in srgb, var(--brand) 30%, var(--line));
  border-radius: 0.7rem;
  background: var(--panel);
}
.operation-heading strong {
  font-size: 0.82rem;
}
.operation-heading p,
.distribution-worker p {
  margin: 0.25rem 0 0;
  font-size: 0.72rem;
}
.operation-heading > span {
  font-size: 0.72rem;
}
.distribution-workers {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
  gap: 0.55rem;
}
.distribution-worker {
  display: grid;
  gap: 0.35rem;
  padding: 0.65rem;
  border: 1px solid var(--line);
  border-radius: 0.6rem;
  background: var(--panel);
}
.distribution-worker .button {
  justify-self: start;
}
.event-list {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding: 0.5rem 0 0;
  border-top: 1px solid var(--line);
  list-style: none;
}
.event-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  font-size: 0.67rem;
}
.event-list time {
  color: var(--muted);
  white-space: nowrap;
}
.failure-code {
  color: var(--danger);
  font-size: 0.73rem;
}
.vault-foot {
  margin: 0.85rem 0 0;
  font-size: 0.7rem;
}
</style>
