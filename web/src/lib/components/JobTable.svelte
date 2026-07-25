<script lang="ts">
  import { onMount } from 'svelte';
  import { api, post } from '$lib/api';
  let { kind = '', title = 'Aktivitas terbaru' }: { kind?: string; title?: string } = $props();
  let jobs = $state<any[]>([]); let error = $state(''); let selected = $state<any | null>(null); let timer: ReturnType<typeof setInterval>;
  async function load() { try { const result = await api<any>(`/jobs?limit=30${kind ? `&kind=${encodeURIComponent(kind)}` : ''}`); jobs = result.items || []; error = ''; } catch (e) { error = e instanceof Error ? e.message : 'Tidak dapat memuat job.'; } }
  async function terminate(id: string) { await post(`/jobs/${id}/cancel`); await load(); }
  async function terminateAll() { await post('/jobs/terminate-active'); await load(); }
  onMount(() => { load(); timer = setInterval(load, 2500); return () => clearInterval(timer); });
</script>

<section class="card mt-6 p-5"><div class="flex flex-wrap items-center justify-between gap-3"><h2 class="text-lg font-bold">{title}</h2><div class="flex gap-2"><button class="button danger" onclick={terminateAll}>Terminate semua aktif</button><button class="button secondary" onclick={load}>Refresh</button></div></div>{#if error}<p class="mt-3 text-sm text-rose-300">{error}</p>{/if}<div class="mt-4 divide-y divide-slate-800">{#each jobs as job}<article class="grid gap-2 py-3 sm:grid-cols-[1fr_auto]"><div><div class="flex flex-wrap items-center gap-2"><b>{job.kind.replaceAll('_', ' ')}</b><span class="badge {job.status}">{job.status}</span></div><p class="muted mt-1 truncate text-sm">{job.progress?.message || job.result?.status || job.error?.message || 'Menunggu proses'}</p></div><div class="flex flex-wrap items-center gap-2"><small class="muted">{new Date(job.updated_at).toLocaleString('id-ID')}</small><button class="button secondary" onclick={() => selected = job}>Report / log</button>{#if ['queued','dispatched','running'].includes(job.status)}<button class="button danger" onclick={() => terminate(job.id)}>Terminate</button>{/if}</div></article>{:else}<p class="muted py-8 text-center">Belum ada job.</p>{/each}</div></section>

{#if selected}<dialog open><div class="flex items-center justify-between border-b border-slate-700 px-5 py-4"><b>Snapshot job {selected.id.slice(0, 12)}</b><button class="button secondary" onclick={() => selected = null}>Tutup</button></div><pre class="max-h-[70vh] overflow-auto p-5 text-xs leading-6">{JSON.stringify({ progress: selected.progress, result: selected.result, error: selected.error, payload: selected.payload }, null, 2)}</pre></dialog>{/if}
