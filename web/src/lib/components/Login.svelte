<script lang="ts">
  import { session } from '$lib/session.svelte';
  let waiting = $state(false); let error = $state('');
  async function begin() { error = ''; try { await session.startLogin(); waiting = true; while (waiting && session.challenge) { await new Promise((r) => setTimeout(r, 2000)); const result = await session.pollLogin(); if (result.authenticated) waiting = false; } } catch (err) { error = err instanceof Error ? err.message : 'Login gagal.'; waiting = false; } }
</script>

<main class="grid min-h-screen place-items-center p-5"><section class="card w-full max-w-md p-8"><p class="text-sm font-bold tracking-[.22em] text-indigo-300">TME3 CONTROL CENTER</p><h1 class="mt-3 text-3xl font-black">Masuk dengan Telegram</h1><p class="muted mt-3">Otorisasi dilakukan lewat bot. Token sesi tidak pernah disimpan di browser.</p>{#if session.challenge}<a class="button mt-6 w-full" href={session.challenge.verification_uri} target="_blank" rel="noreferrer">Buka bot Telegram</a><p class="muted mt-4 text-sm">Menunggu persetujuan pada perangkat ini…</p>{:else}<button class="button mt-6 w-full" onclick={begin}>Mulai login</button>{/if}{#if error}<p class="mt-4 text-sm text-rose-300">{error}</p>{/if}</section></main>
