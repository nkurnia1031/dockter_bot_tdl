<script lang="ts">
  import JobTable from '$lib/components/JobTable.svelte';
  import { Activity } from '@lucide/svelte';
</script>

<header class="flex flex-wrap items-end justify-between gap-4"><div><p class="eyebrow">AKTIVITAS</p><h1 class="mt-2 text-3xl font-black tracking-tight sm:text-4xl">Seluruh job</h1><p class="muted mt-2">Buka report/log snapshot atau terminate job yang masih aktif.</p></div><div class="grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200"><Activity size={23}/></div></header>
<JobTable title="Daftar aktivitas" />
