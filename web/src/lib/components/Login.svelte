<script lang="ts">
  import { session } from '$lib/session.svelte';
  import { LockKeyhole, Send } from '@lucide/svelte';
  let waiting = $state(false);
  let error = $state('');
  async function begin() {
    error = '';
    try {
      await session.startLogin();
      waiting = true;
      while (waiting && session.challenge) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const result = await session.pollLogin();
        if (result.authenticated) waiting = false;
      }
    } catch (cause) { error = cause instanceof Error ? cause.message : 'Login gagal.'; waiting = false; }
  }
</script>

<main class="grid min-h-screen place-items-center p-5"><section class="card w-full max-w-md p-8 page-enter"><div class="grid size-12 place-items-center rounded-2xl bg-gradient-to-br from-violet-600 to-indigo-500 text-white shadow-xl shadow-violet-500/25"><LockKeyhole size={22}/></div><p class="eyebrow mt-6">TME3 CONTROL CENTER</p><h1 class="mt-2 text-3xl font-black tracking-tight">Masuk dengan Telegram</h1><p class="muted mt-3">Otorisasi dilakukan lewat bot. Token sesi tidak pernah disimpan di browser.</p>{#if session.challenge}<a class="button mt-6 w-full" href={session.challenge.verification_uri} target="_blank" rel="noreferrer"><Send size={16}/>Buka bot Telegram</a><p class="muted mt-4 rounded-xl bg-violet-50 px-3 py-2 text-center text-sm dark:bg-violet-950">Menunggu persetujuan pada perangkat ini...</p>{:else}<button class="button mt-6 w-full" onclick={begin}><LockKeyhole size={16}/>Mulai login</button>{/if}{#if error}<p class="mt-4 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:bg-rose-950 dark:text-rose-200">{error}</p>{/if}</section></main>
