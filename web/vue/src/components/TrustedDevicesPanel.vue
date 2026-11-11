<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, patch, post, remove } from "../lib/api";

type Device = {
  id: string;
  name: string;
  algorithm: string;
  fingerprint: string;
  origin: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  status: "active" | "revoked";
};
type Enrollment = {
  version: number;
  device_id: string;
  name: string;
  algorithm: string;
  public_key: string;
  fingerprint: string;
  origin: string;
  private_key?: string;
  private_key_dpapi?: string;
};

const devices = ref<Device[]>([]);
const enrollment = ref<Enrollment | null>(null);
const enrollmentFile = ref("");
const busy = ref(false);
const error = ref("");
const message = ref("");

async function load() {
  busy.value = true;
  error.value = "";
  try {
    const result = await api<{ items?: Device[] }>("/auth/devices");
    devices.value = Array.isArray(result.items) ? result.items : [];
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Daftar perangkat gagal dimuat.";
  } finally {
    busy.value = false;
  }
}

async function readEnrollment(event: Event) {
  const input = event.currentTarget as HTMLInputElement;
  const file = input.files?.[0];
  enrollment.value = null;
  enrollmentFile.value = file?.name || "";
  error.value = "";
  message.value = "";
  if (!file) return;
  try {
    if (file.size > 16_384)
      throw new Error("Berkas pendaftaran terlalu besar.");
    const parsed = JSON.parse(await file.text()) as Enrollment;
    if (parsed.private_key || parsed.private_key_dpapi)
      throw new Error("Berkas tidak boleh memuat private key.");
    if (
      parsed.version !== 1 ||
      parsed.algorithm !== "Ed25519" ||
      parsed.origin !== window.location.origin
    )
      throw new Error("Versi, algoritme, atau origin berkas tidak cocok dengan situs ini.");
    if (
      !/^[0-9a-f-]{36}$/i.test(parsed.device_id) ||
      !parsed.name ||
      !parsed.public_key
    )
      throw new Error("Data pendaftaran tidak lengkap.");

    const standardBase64 = parsed.public_key.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(
      standardBase64.padEnd(Math.ceil(standardBase64.length / 4) * 4, "="),
    );
    const raw = Uint8Array.from(decoded, (character) => character.charCodeAt(0));
    if (raw.length !== 32) throw new Error("Public key Ed25519 tidak valid.");
    const digest = await crypto.subtle.digest("SHA-256", raw);
    const fingerprint = `SHA256:${btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/=+$/, "")}`;
    if (fingerprint !== parsed.fingerprint)
      throw new Error("Fingerprint public key tidak cocok.");
    enrollment.value = parsed;
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Berkas pendaftaran tidak valid.";
  }
}

async function approveEnrollment() {
  if (!enrollment.value) return;
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    const result = await post<{ device: Device; created: boolean }>(
      "/auth/devices",
      enrollment.value,
    );
    message.value = result.created
      ? "Perangkat berhasil ditambahkan."
      : "Perangkat ini sudah terdaftar.";
    enrollment.value = null;
    enrollmentFile.value = "";
    await load();
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Perangkat gagal ditambahkan.";
  } finally {
    busy.value = false;
  }
}

async function renameDevice(device: Device) {
  const nextName = window.prompt("Nama perangkat", device.name)?.trim();
  if (!nextName || nextName === device.name) return;
  busy.value = true;
  error.value = "";
  try {
    await patch(`/auth/devices/${encodeURIComponent(device.id)}`, {
      name: nextName,
    });
    message.value = "Nama perangkat diperbarui.";
    await load();
  } catch (cause) {
    error.value =
      cause instanceof Error
        ? cause.message
        : "Nama perangkat gagal diperbarui.";
  } finally {
    busy.value = false;
  }
}

async function revokeDevice(device: Device) {
  if (
    !window.confirm(
      `Cabut akses perangkat “${device.name}” beserta sesi browser turunannya?`,
    )
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    await remove(`/auth/devices/${encodeURIComponent(device.id)}`);
    message.value = "Akses perangkat dicabut.";
    await load();
  } catch (cause) {
    error.value =
      cause instanceof Error ? cause.message : "Perangkat gagal dicabut.";
  } finally {
    busy.value = false;
  }
}

function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Belum pernah";
}

onMounted(() => void load());
</script>

<template>
  <section class="panel trusted-panel" aria-labelledby="trusted-devices-heading">
    <header class="panel-heading">
      <div><p class="eyebrow">AUTENTIKASI WEB</p><h2 id="trusted-devices-heading">Perangkat tepercaya</h2></div>
      <button class="button button-secondary button-small" type="button" :disabled="busy" @click="load">{{ busy ? "Memuat…" : "Refresh" }}</button>
    </header>
    <div class="panel-body">
      <p class="muted">Daftarkan public key dari helper laptop yang Anda setujui. Key mengizinkan laptop membuat sesi Web dengan hak actor yang sama sampai perangkat dicabut.</p>
      <p v-if="error" class="notice notice-error" role="alert">{{ error }}</p>
      <p v-if="message" class="notice notice-success" role="status">{{ message }}</p>

      <div class="enrollment-box">
        <label>Berkas public key enrollment<input class="field" type="file" accept="application/json,.json" aria-label="Berkas public key enrollment" @change="readEnrollment" /></label>
        <dl v-if="enrollment" class="enrollment-details">
          <div><dt>Nama dan file</dt><dd>{{ enrollment.name }} · {{ enrollmentFile }}</dd></div>
          <div><dt>Origin</dt><dd class="mono">{{ enrollment.origin }}</dd></div>
          <div><dt>Fingerprint SHA-256 — periksa sebelum menyetujui</dt><dd class="mono break-all">{{ enrollment.fingerprint }}</dd></div>
        </dl>
        <button v-if="enrollment" class="button button-primary" type="button" :disabled="busy" @click="approveEnrollment">{{ busy ? "Menyimpan…" : "Setujui dan tambahkan" }}</button>
      </div>

      <div v-if="busy && !devices.length" class="empty-state" role="status">Memuat perangkat…</div>
      <p v-else-if="!devices.length" class="empty-state">Belum ada perangkat terdaftar.</p>
      <div v-else class="device-list">
        <article v-for="device in devices" :key="device.id" class="device-row">
          <div>
            <div class="operation-heading"><h3>{{ device.name }}</h3><span class="status-pill" :class="device.status === 'active' ? 'status-ready' : 'status-neutral'">{{ device.status === "active" ? "Aktif" : "Dicabut" }}</span></div>
            <p class="muted">{{ device.algorithm }} · ditambahkan {{ date(device.created_at) }} · terakhir dipakai {{ date(device.last_used_at) }}</p>
            <p class="mono break-all">{{ device.fingerprint }}</p>
          </div>
          <div class="device-actions">
            <button class="button button-secondary button-small" type="button" :disabled="busy || device.status !== 'active'" @click="renameDevice(device)">Ganti nama</button>
            <button class="button button-danger button-small" type="button" :disabled="busy || device.status === 'revoked'" @click="revokeDevice(device)">Cabut</button>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trusted-panel { overflow:hidden; }
.panel-body { display:grid; gap:.8rem; padding:1rem; }
.enrollment-box { display:grid; gap:.75rem; padding:.85rem; border:1px solid var(--line); border-radius:.75rem; }
.enrollment-details { display:grid; gap:.5rem; margin:0; }
.enrollment-details dt { color:var(--muted); font-size:.72rem; }
.enrollment-details dd { margin:.15rem 0 0; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.75rem; }
.device-list { display:grid; gap:.55rem; }
.device-row { display:flex; align-items:flex-start; justify-content:space-between; gap:.8rem; padding:.8rem; border:1px solid var(--line); border-radius:.7rem; }
.device-row h3 { margin:0; font-size:.9rem; }
.device-row p { margin:.25rem 0; font-size:.72rem; }
.device-actions { display:flex; flex-wrap:wrap; gap:.4rem; }
@media(max-width:600px) { .device-row { flex-direction:column; } }
</style>
