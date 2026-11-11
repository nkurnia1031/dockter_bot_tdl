<script setup lang="ts">
import JobMonitor from '../components/JobMonitor.vue';
</script>

<template>
  <main class="page-stack activity-page">
    <header class="page-heading">
      <div><p class="eyebrow">MONITOR · REALTIME</p><h1>Aktivitas</h1><p class="muted">Job aktif, progres transfer, dan riwayat terbaru.</p></div>
      <span class="activity-live"><i aria-hidden="true"></i>Monitor langsung</span>
    </header>
    <JobMonitor title="Seluruh job" scope="current" polling-mode="activity" />
  </main>
</template>

<style scoped>
.activity-live{display:inline-flex;align-items:center;gap:.45rem;padding:.45rem .65rem;border:1px solid color-mix(in srgb,var(--success) 25%,var(--line));border-radius:99px;background:color-mix(in srgb,var(--success) 7%,var(--panel));color:var(--success);font-family:"DM Mono",monospace;font-size:.62rem}.activity-live i{width:6px;height:6px;border-radius:50%;background:currentColor}
@media(max-width:650px){.activity-page .page-heading{align-items:flex-start;flex-direction:column}}
</style>
