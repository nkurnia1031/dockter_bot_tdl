<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import { routeDefinitions } from '../router';

const route = useRoute();
const page = computed(() => routeDefinitions.find((item) => item.path === route.path));
</script>

<template>
  <main class="page-stack">
    <header class="page-heading">
      <div>
        <p class="eyebrow">MIGRASI VUE</p>
        <h1>{{ page?.label || 'Halaman' }}</h1>
        <p class="muted">{{ page?.description }}</p>
      </div>
      <span class="status-pill status-warn">Menunggu migrasi</span>
    </header>
    <section class="panel placeholder-panel">
      <div class="placeholder-mark" aria-hidden="true">↗</div>
      <div>
        <h2>Halaman Vue sedang disiapkan</h2>
        <p>Halaman production Svelte tetap aktif sampai seluruh alur dan tes halaman ini dipindahkan.</p>
        <RouterLink v-if="route.path === '/profiles/'" class="button button-secondary vault-shortcut" to="/profiles/vault/">Buka Vault</RouterLink>
      </div>
    </section>
  </main>
</template>
