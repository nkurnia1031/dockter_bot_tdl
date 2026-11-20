<script lang="ts">
  import type { MediaProgress } from '$lib/job-progress';

  let { media }: { media: MediaProgress } = $props();
</script>

<section class="mt-2 rounded-lg border border-[var(--line)] bg-[var(--panel-strong)] px-3 py-2 text-[11px]" aria-label="Ringkasan konversi media">
  <div class="flex flex-wrap gap-x-4 gap-y-1 font-semibold text-[var(--ink)]">
    <span>Video: {media.video.total} total · {media.video.running} berjalan · {media.video.succeeded} berhasil · {media.video.failed} gagal</span>
    <span>Gambar: {media.image.total} total · {media.image.running} berjalan · {media.image.succeeded} berhasil · {media.image.failed} gagal</span>
  </div>
  <div class="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[var(--muted)]">
    <span>Estimasi hemat ≤40%: {media.skipped.estimatedSavingsBelowThreshold}</span>
    <span>Output _recode sudah ada: {media.skipped.recodeOutputExists}</span>
  </div>
</section>
