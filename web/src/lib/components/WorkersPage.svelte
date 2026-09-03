<script lang="ts">
  import { onMount } from 'svelte';
  import { Modal } from 'flowbite-svelte';
  import { api, patch, post, put, remove } from '$lib/api';
  import { session } from '$lib/session.svelte';
  import { CheckCircle2, Pencil, Plus, Server, Trash2 } from '@lucide/svelte';

  type Worker = { name: string; url: string; enabled?: boolean; selected?: boolean; healthy?: boolean; latency_ms?: number };
  let workers = $state<Worker[]>([]);
  let name = $state(''); let url = $state(''); let token = $state(''); let message = $state('');
  let editing = $state<Worker|null>(null); let deleting = $state<Worker|null>(null); let editOpen = $state(false); let deleteOpen = $state(false); let editUrl = $state(''); let editToken = $state('');
  async function load() { try { workers = (await api<{items:Worker[]}>('/workers')).items || []; } catch (cause) { message = cause instanceof Error ? cause.message : 'Worker gagal dimuat.'; } }
  async function add() { await post('/workers', { name, url, token }); name = url = token = ''; message = 'Worker ditambahkan.'; await load(); }
  async function select(worker: Worker) {
    if (worker.enabled === false) return;
    await session.chooseWorker(worker.name);
    message = `Job baru akan memakai ${worker.name}.`;
    await load();
  }
  async function toggle(worker: Worker) {
    try {
      const enabled = worker.enabled === false;
      await patch(`/workers/${encodeURIComponent(worker.name)}`, { enabled });
      message = enabled
        ? `${worker.name} diaktifkan dan dapat menerima job baru.`
        : `${worker.name} dinonaktifkan. Job lama tetap berjalan.`;
      await load();
    } catch (cause) {
      message = cause instanceof Error ? cause.message : 'Status worker gagal diubah.';
    }
  }
  async function update() { if (!editing) return; await put(`/workers/${encodeURIComponent(editing.name)}`, { url: editUrl, token: editToken }); editing = null; editOpen = false; await load(); }
  async function destroy() { if (!deleting) return; await remove(`/workers/${encodeURIComponent(deleting.name)}`); deleting = null; deleteOpen = false; await load(); }
  onMount(() => {
    const refresh = () => load();
    window.addEventListener('tme3:context-changed', refresh);
    load();
    return () => window.removeEventListener('tme3:context-changed', refresh);
  });
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">WORKERS</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Worker & routing</h1><p class="muted mt-2">Route baru hanya berlaku untuk job berikutnya; job lama tetap pada worker asal.</p></div><div class="page-icon"><Server size={23}/></div></header>
{#if message}<p class="mt-5 rounded-xl bg-[var(--brand-soft)] p-3 text-sm">{message}</p>{/if}
<div class="mt-7 grid gap-5 xl:grid-cols-[.72fr_1.28fr]">
  <section class="card p-5 sm:p-6"><h2 class="font-extrabold">Tambah worker</h2><div class="mt-4 space-y-3"><label class="block text-sm font-bold">Nama<input class="field mt-2" bind:value={name} placeholder="remote-1"/></label><label class="block text-sm font-bold">URL API<input class="field mt-2" bind:value={url} placeholder="https://worker.example.com"/></label><label class="block text-sm font-bold">Token<input class="field mt-2" type="password" bind:value={token} autocomplete="new-password"/></label></div><button class="button mt-5 w-full" onclick={add} disabled={!name || !url || !token}><Plus size={16}/>Tambahkan worker</button></section>
  <section class="card overflow-hidden"><div class="border-b border-[var(--line)] px-5 py-4"><h2 class="font-extrabold">Registry worker</h2><p class="muted mt-1 text-sm">Profile aktif: {session.current.actor?.profile || '-'}</p></div><div class="divide-y divide-[var(--line)]">
    {#each workers as worker}<article class="flex flex-wrap items-center justify-between gap-3 px-5 py-4"><div class="min-w-0"><div class="flex items-center gap-2"><b>{worker.name}</b>{#if worker.selected}<span class="badge succeeded">Route aktif</span>{/if}{#if worker.enabled === false}<span class="badge failed">Nonaktif</span>{:else}<span class="badge">Siap</span>{/if}</div><p class="muted mt-1 truncate text-sm">{worker.url}</p><p class="muted mt-1 text-xs">{worker.enabled === false ? 'Tidak menerima job baru; job lama tidak dihentikan.' : 'Dapat menerima job baru.'}</p></div><div class="flex flex-wrap gap-2"><button class="button secondary" onclick={() => select(worker)} disabled={worker.selected || worker.enabled === false}><CheckCircle2 size={15}/>Pilih</button><button class={`button ${worker.enabled === false ? '' : 'danger'}`} onclick={() => toggle(worker)}>{worker.enabled === false ? 'Aktifkan' : 'Nonaktifkan'}</button><button class="button secondary" onclick={() => { editing = worker; editUrl = worker.url; editToken = ''; editOpen = true; }}><Pencil size={15}/>Edit</button><button class="button ghost text-rose-600" onclick={() => { deleting = worker; deleteOpen = true; }}><Trash2 size={15}/></button></div></article>{:else}<p class="muted p-6 text-center">Belum ada worker.</p>{/each}
  </div></section>
</div>

<Modal bind:open={editOpen} title={editing ? `Edit ${editing.name}` : 'Edit worker'} size="md">{#if editing}<div class="space-y-3"><label class="block text-sm font-bold">URL<input class="field mt-2" bind:value={editUrl}/></label><label class="block text-sm font-bold">Token baru<input class="field mt-2" type="password" bind:value={editToken} placeholder="Wajib diisi saat memperbarui"/></label></div><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => editOpen = false}>Batal</button><button class="button" onclick={update} disabled={!editUrl || !editToken}>Simpan</button></div>{/if}</Modal>
<Modal bind:open={deleteOpen} title="Hapus worker?" size="sm"><p>Worker <b>{deleting?.name}</b> akan dihapus dari registry. Job yang sudah dibuat tidak dipindahkan.</p><div class="mt-5 flex justify-end gap-2"><button class="button secondary" onclick={() => deleteOpen = false}>Batal</button><button class="button danger" onclick={destroy}>Hapus</button></div></Modal>
