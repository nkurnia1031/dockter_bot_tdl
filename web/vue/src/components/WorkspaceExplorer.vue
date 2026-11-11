<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { api } from "../lib/api";

type TreeItem = {
  name: string;
  path: string;
  kind: "directory" | "file";
  files?: number;
  directories?: number;
  has_children?: boolean;
};
type TreeResponse = { path: string; items: TreeItem[] };

const props = withDefaults(defineProps<{
  selected?: string[];
  single?: boolean;
  worker?: string;
}>(), { selected: () => [], single: false, worker: "" });
const emit = defineEmits<{ "update:selected": [value: string[]] }>();
const current = ref("/workspace");
const items = ref<TreeItem[]>([]);
const loading = ref(false);
const error = ref("");
let generation = 0;
const folders = computed(() => items.value.filter((item) => item.kind === "directory"));
const crumbs = computed(() => current.value.split("/").filter(Boolean));

function isWorkspacePath(path: string) {
  if (path === "/workspace") return true;
  if (!path.startsWith("/workspace/")) return false;
  return path.slice(1).split("/").every((part) => part && part !== "." && part !== "..");
}

async function load(path = current.value) {
  if (!isWorkspacePath(path)) {
    error.value = "Path harus berada di dalam /workspace.";
    return;
  }
  const request = ++generation;
  loading.value = true;
  error.value = "";
  try {
    const workerQuery = props.worker ? `&worker=${encodeURIComponent(props.worker)}` : "";
    const result = await api<TreeResponse>(`/utility/tree?path=${encodeURIComponent(path)}${workerQuery}`);
    if (request !== generation) return;
    if (!isWorkspacePath(result.path)) {
      items.value = [];
      error.value = "Worker mengembalikan lokasi di luar /workspace.";
      return;
    }
    current.value = result.path;
    items.value = Array.isArray(result.items)
      ? result.items.filter((item) => item.kind === "directory" && isWorkspacePath(item.path) && item.path.slice(0, item.path.lastIndexOf("/")) === result.path)
      : [];
  } catch (cause) {
    if (request === generation)
      error.value = cause instanceof Error ? cause.message : "Worker tidak dapat membaca workspace.";
  } finally {
    if (request === generation) loading.value = false;
  }
}

function choose(path: string) {
  if (!isWorkspacePath(path)) return;
  const currentSelection = props.selected || [];
  const next = props.single
    ? currentSelection.includes(path) ? [] : [path]
    : currentSelection.includes(path)
      ? currentSelection.filter((item) => item !== path)
      : [...currentSelection, path];
  emit("update:selected", next);
}

function goUp() {
  if (current.value === "/workspace") return;
  load(current.value.slice(0, current.value.lastIndexOf("/")) || "/workspace");
}

function openCrumb(index: number) {
  load("/" + crumbs.value.slice(0, index + 1).join("/"));
}

watch(() => props.worker, (next, previous) => {
  if (next === previous) return;
  generation++;
  current.value = "/workspace";
  items.value = [];
  emit("update:selected", []);
  void load("/workspace");
});
onMounted(() => void load());
</script>

<template>
  <section class="workspace-browser" aria-label="Penjelajah Workspace">
    <header class="workspace-toolbar">
      <nav class="workspace-crumbs" aria-label="Lokasi Workspace">
        <button v-for="(crumb, index) in crumbs" :key="index" class="crumb-button" type="button" @click="openCrumb(index)">{{ crumb }}</button>
      </nav>
      <div class="toolbar-actions">
        <button class="button button-secondary button-small" type="button" aria-label="Folder induk" :disabled="current === '/workspace' || loading" @click="goUp">←</button>
        <button class="button button-secondary button-small" type="button" aria-label="Refresh folder" :disabled="loading" @click="load()">{{ loading ? "Memuat…" : "Refresh" }}</button>
      </div>
    </header>
    <div class="workspace-current">
      <div><small class="muted">Folder saat ini</small><code>{{ current }}</code></div>
      <button class="button button-secondary button-small" type="button" @click="choose(current)">{{ (selected || []).includes(current) ? "Batalkan" : "Pilih folder" }}</button>
    </div>
    <p v-if="error" class="notice notice-error" role="alert">{{ error }} <button class="button button-secondary button-small" type="button" @click="load()">Coba lagi</button></p>
    <div v-else-if="loading && !items.length" class="empty-state" role="status">Memuat isi Workspace…</div>
    <div v-else class="workspace-items">
      <div v-for="item in folders" :key="item.path" class="workspace-item">
        <input :type="single ? 'radio' : 'checkbox'" name="workspace-folder-choice" :checked="(selected || []).includes(item.path)" :aria-label="`Pilih ${item.name}`" @change="choose(item.path)" />
        <button class="workspace-open" type="button" @click="load(item.path)">
          <strong>{{ item.name }}</strong><small class="muted">{{ item.directories ?? 0 }} folder · {{ item.files ?? 0 }} file</small>
        </button>
        <button class="button button-secondary button-small" type="button" :aria-label="`Buka ${item.name}`" @click="load(item.path)">›</button>
      </div>
      <p v-if="!folders.length" class="empty-state">Tidak ada subfolder di lokasi ini.</p>
    </div>
    <div v-if="selected?.length" class="workspace-selection" aria-label="Folder terpilih">
      <button v-for="path in selected" :key="path" type="button" class="selection-chip" @click="choose(path)">{{ path }} ×</button>
    </div>
  </section>
</template>

<style scoped>
.workspace-browser{overflow:hidden;border:1px solid var(--line);border-radius:.8rem;background:var(--panel)}
.workspace-toolbar,.workspace-current,.workspace-item{display:flex;align-items:center;justify-content:space-between;gap:.65rem;padding:.65rem .8rem}
.workspace-toolbar,.workspace-item{border-bottom:1px solid var(--line)}
.workspace-crumbs,.toolbar-actions{display:flex;align-items:center;gap:.35rem;min-width:0}
.crumb-button{overflow:hidden;max-width:12rem;text-overflow:ellipsis;border-radius:.4rem;padding:.3rem .45rem;font-size:.75rem;font-weight:700}
.crumb-button:hover,.workspace-open:hover{background:var(--panel-soft)}
.workspace-current{background:var(--panel-soft)}
.workspace-current>div,.workspace-open{display:grid;min-width:0;gap:.18rem;text-align:left}
.workspace-current code{overflow:hidden;text-overflow:ellipsis;font-size:.72rem}
.workspace-items{max-height:18rem;overflow:auto}
.workspace-open{flex:1;padding:.25rem .4rem}
.workspace-open strong,.workspace-open small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.workspace-open strong{font-size:.8rem}.workspace-open small{font-size:.68rem}
.workspace-selection{display:flex;flex-wrap:wrap;gap:.35rem;padding:.6rem .8rem}
.selection-chip{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:.25rem .6rem;font-size:.68rem}
.empty-state{padding:1.2rem;text-align:center;color:var(--muted);font-size:.75rem}
@media(prefers-reduced-motion:reduce){.workspace-open,.crumb-button{transition:none}}
</style>
