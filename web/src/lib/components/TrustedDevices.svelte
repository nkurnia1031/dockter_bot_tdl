<script lang="ts">
  import { onMount } from 'svelte';
  import { KeyRound, RefreshCw, Shield, Trash2 } from '@lucide/svelte';
  import { api, patch, post, remove } from '$lib/api';

  type Device = {
    id: string;
    name: string;
    algorithm: string;
    fingerprint: string;
    origin: string;
    created_at: string;
    last_used_at: string | null;
    revoked_at: string | null;
    status: 'active' | 'revoked';
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

  let devices = $state<Device[]>([]);
  let enrollment = $state<Enrollment | null>(null);
  let enrollmentFile = $state('');
  let busy = $state(false);
  let error = $state('');
  let message = $state('');

  async function load() {
    busy = true;
    error = '';
    try {
      const result = await api<{ items: Device[] }>('/auth/devices');
      devices = result.items || [];
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Daftar perangkat gagal dimuat.';
    } finally {
      busy = false;
    }
  }

  async function readEnrollment(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    enrollment = null;
    enrollmentFile = file?.name || '';
    error = '';
    if (!file) return;
    try {
      if (file.size > 16_384) throw new Error('Berkas pendaftaran terlalu besar.');
      const parsed = JSON.parse(await file.text()) as Enrollment;
      if (parsed.private_key || parsed.private_key_dpapi) throw new Error('Berkas tidak boleh memuat private key.');
      if (parsed.version !== 1 || parsed.algorithm !== 'Ed25519' || parsed.origin !== window.location.origin) {
        throw new Error('Versi, algoritme, atau origin berkas tidak cocok dengan situs ini.');
      }
      if (!/^[0-9a-f-]{36}$/i.test(parsed.device_id) || !parsed.name || !parsed.public_key) {
        throw new Error('Data pendaftaran tidak lengkap.');
      }
      const standardBase64 = parsed.public_key.replace(/-/g, '+').replace(/_/g, '/');
      const raw = Uint8Array.from(atob(standardBase64.padEnd(Math.ceil(standardBase64.length / 4) * 4, '=')), (char) => char.charCodeAt(0));
      if (raw.length !== 32) throw new Error('Public key Ed25519 tidak valid.');
      const digest = await crypto.subtle.digest('SHA-256', raw);
      const fingerprint = `SHA256:${btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/=+$/, '')}`;
      if (fingerprint !== parsed.fingerprint) throw new Error('Fingerprint public key tidak cocok.');
      enrollment = parsed;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Berkas pendaftaran tidak valid.';
    }
  }

  async function approveEnrollment() {
    if (!enrollment) return;
    busy = true;
    error = '';
    try {
      const result = await post<{ device: Device; created: boolean }>('/auth/devices', enrollment);
      message = result.created ? 'Perangkat berhasil ditambahkan.' : 'Perangkat ini sudah terdaftar.';
      enrollment = null;
      enrollmentFile = '';
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Perangkat gagal ditambahkan.';
    } finally {
      busy = false;
    }
  }

  async function renameDevice(device: Device) {
    const nextName = window.prompt('Nama perangkat', device.name)?.trim();
    if (!nextName || nextName === device.name) return;
    busy = true;
    error = '';
    try {
      await patch(`/auth/devices/${encodeURIComponent(device.id)}`, { name: nextName });
      message = 'Nama perangkat diperbarui.';
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Nama perangkat gagal diperbarui.';
    } finally {
      busy = false;
    }
  }

  async function revokeDevice(device: Device) {
    if (!window.confirm(`Cabut akses perangkat “${device.name}” beserta sesi browser turunannya?`)) return;
    busy = true;
    error = '';
    try {
      await remove(`/auth/devices/${encodeURIComponent(device.id)}`);
      message = 'Akses perangkat dicabut.';
      await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Perangkat gagal dicabut.';
    } finally {
      busy = false;
    }
  }

  const date = (value: string | null) => value ? new Date(value).toLocaleString() : 'Belum pernah';
  onMount(load);
</script>

<section class="card p-5 sm:p-6" aria-labelledby="trusted-devices-heading">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-3"><KeyRound class="text-violet-600" size={21}/><h2 id="trusted-devices-heading" class="font-extrabold">Perangkat tepercaya</h2></div>
    <button class="button" onclick={load} disabled={busy}><RefreshCw size={15}/>{busy ? 'Memuat...' : 'Refresh'}</button>
  </div>
  <p class="muted mt-2 text-sm">Daftarkan public key dari helper laptop yang Anda setujui. Key mengizinkan laptop membuat sesi Web dengan hak actor yang sama sampai perangkat dicabut.</p>
  {#if error}<p role="alert" class="mt-3 text-sm text-rose-600">{error}</p>{/if}
  {#if message}<p role="status" class="mt-3 text-sm text-emerald-600">{message}</p>{/if}

  <div class="mt-4 rounded-xl border border-[var(--line)] p-4">
    <label class="block text-sm font-bold">Berkas public key enrollment<input class="field mt-2" type="file" accept="application/json,.json" onchange={readEnrollment}/></label>
    {#if enrollment}
      <dl class="mt-4 grid gap-2 text-sm sm:grid-cols-2">
        <div><dt class="muted">Nama dan file</dt><dd class="font-semibold">{enrollment.name} · {enrollmentFile}</dd></div>
        <div><dt class="muted">Origin</dt><dd class="font-mono">{enrollment.origin}</dd></div>
        <div class="sm:col-span-2"><dt class="muted">Fingerprint SHA-256 — periksa sebelum menyetujui</dt><dd class="break-all font-mono">{enrollment.fingerprint}</dd></div>
      </dl>
      <button class="button mt-4" onclick={approveEnrollment} disabled={busy}><Shield size={16}/>{busy ? 'Menyimpan...' : 'Setujui dan tambahkan'}</button>
    {/if}
  </div>

  <div class="mt-4 space-y-3">
    {#each devices as device (device.id)}
      <article class="rounded-xl border border-[var(--line)] p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div><div class="flex items-center gap-2"><h3 class="font-bold">{device.name}</h3><span class="badge">{device.status === 'active' ? 'Aktif' : 'Dicabut'}</span></div>
            <p class="muted mt-1 text-xs">{device.algorithm} · ditambahkan {date(device.created_at)} · terakhir dipakai {date(device.last_used_at)}</p>
            <p class="mt-2 break-all font-mono text-xs">{device.fingerprint}</p>
          </div>
          <div class="flex gap-2">
            <button class="button" onclick={() => renameDevice(device)} disabled={busy || device.status !== 'active'}>Ganti nama</button>
            <button class="button" onclick={() => revokeDevice(device)} disabled={busy || device.status === 'revoked'}><Trash2 size={15}/>Cabut</button>
          </div>
        </div>
      </article>
    {:else}
      <p class="muted text-sm">Belum ada perangkat terdaftar.</p>
    {/each}
  </div>
</section>
