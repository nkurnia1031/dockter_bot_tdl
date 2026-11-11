<script setup lang="ts">
withDefaults(defineProps<{ name: string }>(), { name: 'settings' });

const paths: Record<string, string[]> = {
  dashboard: ['M3 3h8v8H3z', 'M13 3h8v5h-8z', 'M13 10h8v11h-8z', 'M3 13h8v8H3z'],
  activity: ['M3 12h4l3-8 4 16 3-8h4'],
  storage: ['M4 5h16v4H4z', 'M4 11h16v4H4z', 'M4 17h16v2H4z', 'M8 7h.01', 'M8 13h.01'],
  download: ['M12 3v12', 'm7 10 5 5 5-5', 'M5 20h14'],
  aria: ['M6 4h12', 'M12 4v15', 'm7 14 5 5 5-5', 'M5 8h2', 'M17 8h2'],
  send: ['m22 2-7 20-4-9-9-4Z', 'M22 2 11 13'],
  export: ['M12 15V3', 'm7 8 5-5 5 5', 'M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6'],
  quick: ['m13 2-3 9h8L8 22l3-9H3z'],
  tts: ['M3 10v4', 'M7 7v10', 'M11 4v16', 'M15 8v8', 'M19 10v4', 'M22 11v2'],
  decrypt: ['M7 14a5 5 0 1 1 4.5-2.8L21 21', 'm15 15 3 3', 'm18 12 3 3'],
  utility: ['M14.7 6.3a5 5 0 0 0-6.4 6.4L3 18a2.1 2.1 0 0 0 3 3l5.3-5.3a5 5 0 0 0 6.4-6.4L14 13l-3-3z'],
  backup: ['M4 4h16v16H4z', 'M8 2v4', 'M16 2v4', 'M8 12h8', 'M8 16h5'],
  profile: ['M20 21a8 8 0 0 0-16 0', 'M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z'],
  workers: ['M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2', 'M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M20 8v6', 'M23 11h-6'],
  settings: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z', 'M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.7 2.94-.08-.02a1.7 1.7 0 0 0-1.7.98l-.03.08h-3.4l-.03-.08a1.7 1.7 0 0 0-1.7-.98l-.08.02-1.7-2.94.06-.06a1.7 1.7 0 0 0 .34-1.88l-.04-.08-2.96-1.7.02-.08a1.7 1.7 0 0 0 0-1.96l-.02-.08 2.96-1.7.04-.08a1.7 1.7 0 0 0-.34-1.88l-.06-.06 1.7-2.94.08.02a1.7 1.7 0 0 0 1.7-.98l.03-.08h3.4l.03.08a1.7 1.7 0 0 0 1.7.98l.08-.02 1.7 2.94-.06.06A1.7 1.7 0 0 0 19.4 9l.04.08 2.96 1.7-.02.08a1.7 1.7 0 0 0 0 1.96l.02.08-2.96 1.7z'],
  development: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3 6h.01', 'M3 12h.01', 'M3 18h.01']
};
</script>

<template>
  <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path v-for="(path, index) in (paths[name] || paths.settings)" :key="index" :d="path" />
  </svg>
</template>
