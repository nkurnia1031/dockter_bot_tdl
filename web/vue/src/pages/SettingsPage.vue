<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api, put } from "../lib/api";
import TrustedDevicesPanel from "../components/TrustedDevicesPanel.vue";

type Settings = {
  move_size: string;
  compress_size: string;
  rclone_destination: string;
  compress_password_configured: boolean;
};
type SettingMeta = {
  key: string;
  label: string;
  description: string;
  format: string;
  examples: string[];
  secret: boolean;
};
type StorageSettings = {
  title?: string;
  channel_id?: number | string;
  channel?: number | string;
};
type RuntimeSecrets = {
  telegram_bot_token_configured: boolean;
  telegram_tts_chat_configured: boolean;
};

const settings = ref<Settings>({
  move_size: "",
  compress_size: "",
  rclone_destination: "",
  compress_password_configured: false,
});
const meta = ref<SettingMeta[]>([]);
const drafts = reactive<Record<string, string>>({});
const storage = ref<StorageSettings | null>(null);
const runtimeSecrets = ref<RuntimeSecrets>({
  telegram_bot_token_configured: false,
  telegram_tts_chat_configured: false,
});
const secretDraft = reactive({ bot_token: "" });
const message = ref("");
const failure = ref("");
const loading = ref(false);
const saving = ref("");

async function load() {
  loading.value = true;
  failure.value = "";
  try {
    const [valueResult, metaResult, storageResult, secretResult] =
      await Promise.all([
        api<Settings>("/utility/settings"),
        api<{ items?: SettingMeta[] }>("/utility/settings/meta"),
        api<StorageSettings>("/storage/settings").catch(() => null),
        api<RuntimeSecrets>("/runtime/secrets"),
      ]);
    settings.value = valueResult;
    meta.value = Array.isArray(metaResult.items) ? metaResult.items : [];
    storage.value = storageResult;
    runtimeSecrets.value = secretResult;
    for (const key of ["move_size", "compress_size", "rclone_destination"])
      drafts[key] = valueResult[key as keyof Settings] as string;
    drafts.compress_password = "";
    secretDraft.bot_token = "";
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Pengaturan gagal dimuat.";
  } finally {
    loading.value = false;
  }
}

async function save(item: SettingMeta) {
  if (!drafts[item.key]) return;
  saving.value = item.key;
  failure.value = "";
  message.value = "";
  try {
    await put(`/utility/settings/${encodeURIComponent(item.key)}`, {
      value: drafts[item.key],
    });
    message.value = `${item.label} berhasil disimpan.`;
    await load();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Pengaturan gagal disimpan.";
  } finally {
    saving.value = "";
  }
}

async function saveRuntimeSecrets() {
  const payload: Record<string, string> = {};
  if (secretDraft.bot_token) payload.bot_token = secretDraft.bot_token;
  if (!Object.keys(payload).length) return;
  saving.value = "runtime-secrets";
  failure.value = "";
  message.value = "";
  try {
    const result = await put<RuntimeSecrets & { restart_required_services?: string[] }>(
      "/runtime/secrets",
      payload,
    );
    const services = (result.restart_required_services || []).join(" dan ");
    message.value = services
      ? `Credential tersimpan. Restart container ${services} agar perubahan aktif.`
      : "Credential tersimpan.";
    await load();
  } catch (cause) {
    failure.value =
      cause instanceof Error ? cause.message : "Credential gagal disimpan.";
  } finally {
    saving.value = "";
  }
}

function activeValue(item: SettingMeta) {
  if (item.secret)
    return settings.value.compress_password_configured
      ? "Sudah diatur"
      : "Belum diatur";
  const value = settings.value[item.key as keyof Settings];
  return typeof value === "string" && value ? value : "-";
}

onMounted(() => void load());
</script>

<template>
  <main class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">SETTINGS</p>
        <h1>Pengaturan</h1>
        <p class="muted">Default utility dan pengaturan keamanan aplikasi.</p>
      </div>
      <button class="button button-secondary button-small" :disabled="loading" @click="load">{{ loading ? "Memuat…" : "Muat ulang" }}</button>
    </header>
    <p v-if="message" class="notice notice-success" role="status">{{ message }}</p>
    <p v-if="failure" class="notice notice-error" role="alert">{{ failure }}</p>

    <div class="settings-layout">
      <section class="panel">
        <div class="panel-heading"><h2>Default utility</h2></div>
        <div v-if="loading && !meta.length" class="empty-state" role="status">Memuat pengaturan…</div>
        <div v-else-if="!meta.length" class="empty-state">Metadata pengaturan belum tersedia.</div>
        <div v-else class="setting-list">
          <article v-for="item in meta" :key="item.key" class="setting-item">
            <div class="setting-heading"><div><h3>{{ item.label }}</h3><p class="muted">{{ item.description }}</p></div><span class="status-pill status-neutral">Aktif · {{ activeValue(item) }}</span></div>
            <div class="setting-form">
              <label>Nilai baru<input v-model="drafts[item.key]" class="field" :type="item.secret ? 'password' : 'text'" :autocomplete="item.secret ? 'new-password' : 'off'" :placeholder="item.examples?.[0] || item.format" /></label>
              <button class="button button-primary" type="button" :disabled="!drafts[item.key] || saving === item.key" @click="save(item)">{{ saving === item.key ? "Menyimpan…" : "Simpan" }}</button>
            </div>
            <p class="muted setting-format"><strong>Format:</strong> {{ item.format }}. <template v-if="item.examples?.length">Contoh: {{ item.examples.join(", ") }}.</template></p>
          </article>
        </div>
      </section>

      <div class="settings-side">
        <section class="panel panel-body">
          <h2>Channel storage</h2>
          <dl><div><dt class="muted">Nama</dt><dd>{{ storage?.title || "Belum dikonfigurasi" }}</dd></div><div><dt class="muted">Channel ID</dt><dd class="mono">{{ storage?.channel_id || storage?.channel || "-" }}</dd></div></dl>
        </section>
        <section class="panel panel-body">
          <h2>Kredensial Telegram</h2>
          <p class="muted">Token bot: {{ runtimeSecrets.telegram_bot_token_configured ? "Sudah diatur" : "Belum diatur" }}. ID chat tujuan audio dikelola dari halaman TTS Novel.</p>
          <label>Token bot baru<input v-model="secretDraft.bot_token" class="field" type="password" autocomplete="new-password" placeholder="Kosongkan agar tidak berubah" /></label>
          <button class="button button-primary" :disabled="saving === 'runtime-secrets' || !secretDraft.bot_token" @click="saveRuntimeSecrets">{{ saving === "runtime-secrets" ? "Menyimpan…" : "Simpan token bot" }}</button>
          <p class="muted">Nilai rahasia hanya dikirim saat disimpan dan tidak dibaca kembali ke halaman. Perubahan token bot memerlukan restart backend dan Telegram.</p>
        </section>
        <section class="panel panel-body">
          <h2>Keamanan</h2>
          <p class="muted">Login Web melindungi pengaturan. Password dan token tersimpan di volume data dengan akses file terbatas; API tidak mengembalikan nilainya.</p>
        </section>
      </div>
    </div>
    <TrustedDevicesPanel />
  </main>
</template>

<style scoped>
.settings-layout { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(18rem,.8fr); gap:1rem; align-items:start; }
.setting-list { display:grid; gap:.55rem; padding:1rem; }
.setting-item { display:grid; gap:.55rem; padding:.8rem; border:1px solid var(--line); border-radius:.7rem; }
.setting-heading,.setting-form { display:flex; justify-content:space-between; align-items:end; gap:.65rem; flex-wrap:wrap; }
.setting-heading h3,.panel-body h2 { margin:0; font-size:.9rem; }
.setting-heading p,.setting-format { margin:0; font-size:.72rem; }
.setting-form label,.panel-body label { display:grid; gap:.3rem; flex:1; min-width:min(100%,14rem); }
.setting-format { line-height:1.5; }
.settings-side { display:grid; gap:.8rem; }
.panel-body { display:grid; gap:.7rem; padding:1rem; }
.panel-body dl { display:grid; gap:.55rem; margin:0; }
.panel-body dd { margin:.15rem 0 0; font-weight:650; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
@media(max-width:850px) { .settings-layout { grid-template-columns:1fr; } }
</style>
