<script lang="ts">
  import '../styles.css';
  import Shell from '$lib/components/Shell.svelte';
  let { children } = $props();
</script>

<Shell>{@render children()}</Shell>
