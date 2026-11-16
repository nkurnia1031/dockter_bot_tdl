<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import { CircleAlert, Download, Link2, Pause, Play, RefreshCw } from '@lucide/svelte';
  import { api } from '$lib/api';

  type Props = { worker: string; directory: string; active: boolean; route?: 'non' | 'tor' };
  type PreviewFile = { item_id: string; source_url?: string; file_name: string; thumbnail_url: string };
  type PreviewItem = {
    source_index: number;
    kind: string;
    title: string;
    files: PreviewFile[];
    error: string;
  };
  type Preview = { items: PreviewItem[] };
  type LinkTask = {
    gid: string;
    kind: string;
    file_name: string;
    status: string;
    completed_bytes: number;
    total_bytes: number;
    speed_bytes_per_second: number;
    error_code: string;
    reason_code: string;
    refresh_attempts: number;
    retry_after_seconds: number;
    route: 'non' | 'tor';
    route_change_allowed: boolean;
  };
  type TaskResult = { items: LinkTask[] };
  type EnqueueResult = { items: Array<{ status: string; file_name?: string; reason_code?: string }> };

  const FILES_PER_PAGE = 6;

  let { worker, directory, active, route = $bindable('non') }: Props = $props();
  let sources = $state('');
  let preview = $state<Preview | null>(null);
  let previewSources = $state<string[]>([]);
  let selectedFiles = $state<Record<string, boolean>>({});
  let pageBySource = $state<Record<number, number>>({});
  let thumbnailAttempts = $state<Record<string, boolean>>({});
  let thumbnailLoading = $state<Record<string, boolean>>({});
  let previewGeneration = 0;
  let tasks = $state<LinkTask[]>([]);
  let checking = $state(false);
  let enqueueing = $state(false);
  let loadingTasks = $state(false);
  let taskAction = $state('');
  let message = $state('');
  let error = $state('');
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let lastWorker = '';

  function linksPath(name = worker) {
    return `/workers/${encodeURIComponent(name)}/aria2/links`;
  }

  function fileKey(sourceIndex: number, itemId: string) {
    return `${sourceIndex}:${itemId}`;
  }

  function activeTasks(items = tasks) {
    return items.some((task) => ['active', 'waiting', 'refreshing'].includes(task.status));
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = undefined;
  }

  function schedulePoll(name = worker) {
    stopPolling();
    if (!untrack(() => active && name === worker && activeTasks())) return;
    pollTimer = setTimeout(async () => {
      await untrack(() => loadTasks(name));
      schedulePoll(name);
    }, 2500);
  }

  async function loadTasks(name = worker) {
    if (!name) return;
    stopPolling();
    loadingTasks = true;
    try {
      const result = await api<TaskResult>(`${linksPath(name)}/tasks`);
      if (name === worker) {
        tasks = Array.isArray(result.items) ? result.items : [];
        error = '';
      }
    } catch (cause) {
      if (name === worker) error = cause instanceof Error ? cause.message : 'Status task gagal dimuat.';
    } finally {
      if (name === worker) loadingTasks = false;
      schedulePoll(name);
    }
  }

  $effect(() => {
    const name = worker;
    const visible = active;
    if (lastWorker && lastWorker !== name) {
      previewGeneration += 1;
      tasks = [];
      preview = null;
      previewSources = [];
      selectedFiles = {};
      pageBySource = {};
      thumbnailAttempts = {};
      thumbnailLoading = {};
      message = '';
      error = '';
    }
    lastWorker = name;
    if (!name || !visible) {
      stopPolling();
      return;
    }
    untrack(() => { void loadTasks(name); });
    return stopPolling;
  });

  onDestroy(stopPolling);

  function collectSources() {
    return sources.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  }

  function handleSourcesInput(event: Event) {
    sources = (event.currentTarget as HTMLTextAreaElement).value;
    if (checking) previewGeneration += 1;
    if (preview && JSON.stringify(collectSources()) !== JSON.stringify(previewSources)) {
      previewGeneration += 1;
      preview = null;
      previewSources = [];
      selectedFiles = {};
      pageBySource = {};
      thumbnailAttempts = {};
      thumbnailLoading = {};
      message = 'Link berubah; periksa ulang sebelum memasukkan file ke antrean.';
    }
  }

  function currentPage(source: PreviewItem) {
    const page = pageBySource[source.source_index] || 0;
    return Math.min(page, Math.max(0, Math.ceil(source.files.length / FILES_PER_PAGE) - 1));
  }

  function pageCount(source: PreviewItem) {
    return Math.max(1, Math.ceil(source.files.length / FILES_PER_PAGE));
  }

  function visibleFiles(source: PreviewItem) {
    const start = currentPage(source) * FILES_PER_PAGE;
    return (source.files || []).slice(start, start + FILES_PER_PAGE);
  }

  function allAlbumFilesSelected(current = preview) {
    const albums = (current?.items || []).filter((source) => source.kind === 'album');
    return albums.length > 0
      && albums.every((source) => (source.files || []).every((file) =>
        selectedFiles[fileKey(source.source_index, file.item_id)]
      ));
  }

  function toggleSelectAll() {
    if (!preview) return;
    const select = !allAlbumFilesSelected(preview);
    const next = { ...selectedFiles };
    for (const source of preview.items || []) {
      if (source.kind !== 'album') continue;
      for (const file of source.files || []) next[fileKey(source.source_index, file.item_id)] = select;
    }
    selectedFiles = next;
  }

  function changePage(source: PreviewItem, page: number) {
    pageBySource = { ...pageBySource, [source.source_index]: page };
    void loadPageThumbnails(source);
  }

  async function loadPageThumbnails(source: PreviewItem) {
    if (source.kind !== 'album' || !worker) return;
    const missing = visibleFiles(source).filter((file) =>
      Boolean(file.source_url)
      && !file.thumbnail_url
      && !thumbnailAttempts[fileKey(source.source_index, file.item_id)]
    );
    if (!missing.length) return;

    const generation = previewGeneration;
    const workerName = worker;
    const keys = missing.map((file) => fileKey(source.source_index, file.item_id));
    thumbnailAttempts = { ...thumbnailAttempts, ...Object.fromEntries(keys.map((key) => [key, true])) };
    thumbnailLoading = { ...thumbnailLoading, ...Object.fromEntries(keys.map((key) => [key, true])) };
    try {
      const result = await api<Preview>(`${linksPath(workerName)}/preview`, {
        method: 'POST',
        body: JSON.stringify({ sources: missing.map((file) => file.source_url) })
      });
      if (generation !== previewGeneration || workerName !== worker || !preview) return;
      const thumbnails = new Map<string, string>();
      missing.forEach((file, index) => {
        const thumbnail = result.items?.[index]?.files?.[0]?.thumbnail_url;
        if (thumbnail) thumbnails.set(fileKey(source.source_index, file.item_id), thumbnail);
      });
      if (thumbnails.size) {
        preview = {
          ...preview,
          items: preview.items.map((item) => item.source_index === source.source_index
            ? {
                ...item,
                files: item.files.map((file) => {
                  const thumbnail = thumbnails.get(fileKey(item.source_index, file.item_id));
                  return thumbnail ? { ...file, thumbnail_url: thumbnail } : file;
                })
              }
            : item)
        };
      }
      const failedKeys = missing
        .filter((file) => !thumbnails.has(fileKey(source.source_index, file.item_id)))
        .map((file) => fileKey(source.source_index, file.item_id));
      if (failedKeys.length) {
        const next = { ...thumbnailAttempts };
        for (const key of failedKeys) delete next[key];
        thumbnailAttempts = next;
      }
    } catch {
      // The album listing remains usable when a thumbnail page cannot be fetched.
      if (generation === previewGeneration && workerName === worker) {
        const next = { ...thumbnailAttempts };
        for (const key of keys) delete next[key];
        thumbnailAttempts = next;
      }
    } finally {
      if (generation === previewGeneration && workerName === worker) {
        const next = { ...thumbnailLoading };
        for (const key of keys) delete next[key];
        thumbnailLoading = next;
      }
    }
  }

  async function inspectLinks() {
    const values = collectSources();
    if (!values.length) {
      error = 'Masukkan minimal satu link.';
      return;
    }
    checking = true;
    const generation = ++previewGeneration;
    error = '';
    message = '';
    preview = null;
    previewSources = [];
    selectedFiles = {};
    try {
      const result = await api<Preview>(`${linksPath()}/preview`, {
        method: 'POST', body: JSON.stringify({ sources: values })
      });
      if (generation !== previewGeneration) return;
      previewSources = values;
      preview = result;
      pageBySource = {};
      thumbnailAttempts = {};
      thumbnailLoading = {};
      const next: Record<string, boolean> = {};
      for (const source of result.items || []) {
        for (const file of source.files || []) {
          next[fileKey(source.source_index, file.item_id)] = source.kind !== 'album';
        }
      }
      selectedFiles = next;
      const fileCount = Object.values(next).filter(Boolean).length;
      const albumCount = (result.items || []).filter((source) => source.kind === 'album')
        .reduce((count, source) => count + (source.files || []).length, 0);
      for (const source of result.items || []) void loadPageThumbnails(source);
      message = albumCount
        ? `${albumCount} file album ditemukan. Pilih file atau gunakan Pilih semua.`
        : fileCount ? `${fileCount} file dapat dipilih.` : 'Tidak ada file yang dapat dimasukkan ke antrean.';
    } catch (cause) {
      if (generation === previewGeneration) {
        error = cause instanceof Error ? cause.message : 'Preview link gagal dimuat.';
      }
    } finally {
      checking = false;
    }
  }

  function selectionPayload(current: Preview) {
    const selections: Record<string, string[]> = {};
    for (const source of current.items || []) {
      selections[String(source.source_index)] = (source.files || [])
        .filter((file) => source.kind === 'direct' || selectedFiles[fileKey(source.source_index, file.item_id)])
        .map((file) => file.item_id);
    }
    return selections;
  }

  function selectedCount(current = preview) {
    if (!current) return 0;
    return current.items.reduce((count, source) => count + (source.files || []).filter((file) =>
      source.kind === 'direct' || selectedFiles[fileKey(source.source_index, file.item_id)]
    ).length, 0);
  }

  function sourceSelectedCount(source: PreviewItem) {
    return (source.files || []).filter((file) =>
      source.kind === 'direct' || selectedFiles[fileKey(source.source_index, file.item_id)]
    ).length;
  }

  function previewFileCount(current = preview) {
    return (current?.items || []).reduce((count, source) => count + (source.files || []).length, 0);
  }

  async function enqueueSelected() {
    if (!preview || selectedCount() === 0) return;
    if (JSON.stringify(collectSources()) !== JSON.stringify(previewSources)) {
      preview = null;
      previewSources = [];
      selectedFiles = {};
      error = 'Link berubah; periksa ulang sebelum memasukkan file ke antrean.';
      return;
    }
    enqueueing = true;
    error = '';
    message = '';
    try {
      const result = await api<EnqueueResult>(`${linksPath()}/enqueue`, {
        method: 'POST',
        body: JSON.stringify({
          sources: previewSources,
          selections: selectionPayload(preview),
          directory,
          route
        })
      });
      const items = result.items || [];
      const queued = items.filter((item) => item.status === 'queued' || item.status === 'held').length;
      const failed = items.filter((item) => item.status === 'failed');
      const skipped = items.filter((item) => item.status === 'skipped').length;
      message = `${queued} task masuk antrean${failed.length ? `; ${failed.length} gagal/bentrok` : ''}${skipped ? `; ${skipped} dilewati` : ''}.`;
      if (failed.length) {
        message += ` ${failed.map((item) => `${item.file_name || 'Link'}: ${item.reason_code || 'gagal'}`).join('; ')}`;
      }
      sources = '';
      preview = null;
      previewSources = [];
      selectedFiles = {};
      await loadTasks();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Pengiriman task ke Aria2 gagal.';
    } finally {
      enqueueing = false;
    }
  }

  async function controlTask(task: LinkTask, action: 'pause' | 'resume' | 'route', nextRoute?: 'non' | 'tor') {
    const key = `${task.gid}:${action}`;
    taskAction = key;
    error = '';
    try {
      await api(`${linksPath()}/tasks/${encodeURIComponent(task.gid)}/${action}`, {
        method: 'POST', body: JSON.stringify(action === 'route' ? { route: nextRoute || task.route } : {})
      });
      await loadTasks();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Aksi task gagal.';
    } finally {
      taskAction = '';
    }
  }

  function statusLabel(task: LinkTask) {
    if (task.status === 'refreshing') {
      if (task.refresh_attempts <= 0) return 'Memperbarui URL otomatis…';
      if (task.retry_after_seconds > 0) return `Memperbarui URL otomatis · percobaan ${task.refresh_attempts} · coba lagi dalam ${task.retry_after_seconds} dtk`;
      return `Memperbarui URL otomatis · percobaan ${task.refresh_attempts}`;
    }
    if (task.status === 'held' && task.reason_code === 'ARIA2_TOR_UNAVAILABLE') return 'Ditahan · layanan Tor belum siap';
    if (task.status === 'held' && task.reason_code?.includes('MISMATCH')) return 'Ditahan · metadata file berubah';
    return task.status;
  }

  function formatBytes(value: number) {
    if (!Number.isFinite(value) || value < 0) return '0 B';
    if (value < 1024) return `${value} B`;
    const units = ['KiB', 'MiB', 'GiB', 'TiB'];
    let size = value / 1024;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
    return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[unit]}`;
  }

  function percent(task: LinkTask) {
    return task.total_bytes > 0
      ? Math.min(100, Math.round(task.completed_bytes * 100 / task.total_bytes))
      : 0;
  }
</script>

<section class="space-y-4 p-3 sm:p-5" hidden={!active} aria-label="Panel Bunkr">
  <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,.55fr)]">
    <form class="card space-y-3 p-4" onsubmit={(event) => { event.preventDefault(); void inspectLinks(); }}>
      <div class="flex items-start gap-3">
        <Link2 class="mt-0.5 shrink-0 text-[var(--brand)]" size={20}/>
        <div>
          <h2 class="font-extrabold">Tambahkan link</h2>
          <p class="muted mt-1 text-sm">Masukkan link Bunkr atau URL langsung, satu link per baris. Album bisa dipilih per file.</p>
        </div>
      </div>
      <label class="block text-sm font-bold" for="aria2-bunkr-sources">Link Bunkr atau URL langsung</label>
      <textarea id="aria2-bunkr-sources" class="field min-h-28 font-mono text-sm" value={sources} oninput={handleSourcesInput} placeholder="https://bunkr.cr/a/…" spellcheck="false"></textarea>
      <div class="flex flex-wrap items-end gap-3">
        <label class="min-w-40 text-sm font-bold">Rute unduh
          <select class="field mt-1" aria-label="Rute unduh" bind:value={route}>
            <option value="non">Non</option>
            <option value="tor">Tor</option>
          </select>
        </label>
        <div class="min-w-0 flex-1 text-sm">
          <span class="muted block text-xs font-bold uppercase tracking-wide">Folder tujuan</span>
          <span class="mt-1 block break-all font-mono">{directory}</span>
        </div>
        <button class="button primary" type="submit" disabled={checking || enqueueing || !worker}>
          <Link2 size={15}/>{checking ? 'Memeriksa…' : 'Periksa link'}
        </button>
      </div>
    </form>

    <aside class="card flex flex-col justify-between gap-3 p-4">
      <div>
        <p class="eyebrow">WORKER {worker}</p>
        <h2 class="mt-1 font-extrabold">Tujuan dan status</h2>
        <p class="muted mt-1 text-sm">Unduhan masuk ke folder Workspace terpilih. Pembaruan URL Bunkr dicoba otomatis saat aria2 mendeteksi link kedaluwarsa.</p>
      </div>
      <div class="rounded-xl border border-[var(--line)] bg-[var(--surface)] p-3 text-xs">
        <div class="flex items-center gap-2 font-bold"><Download size={15}/>Folder aktif</div>
        <p class="muted mt-1 break-all font-mono">{directory}</p>
      </div>
    </aside>
  </div>

  {#if error}<div class="alert error" role="alert">{error}</div>{/if}
  {#if message}<div class="alert success" role="status">{message}</div>{/if}

  {#if preview}
    <section class="card overflow-hidden p-0" aria-labelledby="bunkr-preview-title">
      <header class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] bg-[var(--panel-soft)] p-4 sm:p-5">
        <div class="flex min-w-0 items-center gap-3">
          <span class="page-icon shrink-0"><Download size={18}/></span>
          <div class="min-w-0">
            <p class="eyebrow">PRATINJAU LINK · {previewFileCount()} FILE</p>
            <h2 id="bunkr-preview-title" class="mt-1 text-lg font-extrabold">Pilih file untuk antrean</h2>
            <p class="muted mt-1 text-sm">Periksa isi album, lalu pilih file yang akan ditambahkan.</p>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="badge border border-[var(--line)] bg-[var(--panel)]">{selectedCount()} dipilih</span>
          {#if (preview.items || []).some((source) => source.kind === 'album' && source.files.length > 0)}
            <button class="button secondary" type="button" onclick={toggleSelectAll} aria-pressed={allAlbumFilesSelected()}>
              {allAlbumFilesSelected() ? 'Batalkan semua pilihan' : 'Pilih semua'}
            </button>
          {/if}
          <button class="button primary" type="button" onclick={enqueueSelected} disabled={enqueueing || selectedCount() === 0}>
            <Download size={15}/>{enqueueing ? 'Menambahkan…' : 'Masukkan pilihan ke Aria2'}
          </button>
        </div>
      </header>
      <div class="space-y-3 p-3 sm:p-4">
        {#each preview.items || [] as source (source.source_index)}
          {@const page = currentPage(source)}
          {@const totalPages = pageCount(source)}
          {@const pageFiles = visibleFiles(source)}
          <article class="min-w-0 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--panel)]">
            <header class="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-3 py-3 sm:px-4">
              <div class="flex min-w-0 items-center gap-3">
                <span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-[var(--line)] bg-[var(--panel-soft)] text-[var(--brand)]"><Link2 size={16}/></span>
                <div class="min-w-0">
                  <div class="mb-1 flex flex-wrap items-center gap-2">
                    <span class="eyebrow">{source.kind === 'album' ? 'ALBUM' : 'LINK LANGSUNG'}</span>
                    <span class="muted text-xs">{source.files.length} file · {sourceSelectedCount(source)} dipilih</span>
                  </div>
                  <h3 class="truncate font-bold" title={source.title || `Link ${source.source_index + 1}`}>{source.title || `Link ${source.source_index + 1}`}</h3>
                </div>
              </div>
              {#if source.kind === 'album' && source.files.length > 0}
                <span class="badge">Halaman {page + 1}/{totalPages}</span>
              {/if}
            </header>
            {#if source.error}
              <p class="m-3 flex items-start gap-2 rounded-lg border border-rose-500/25 bg-rose-500/10 p-3 text-sm text-rose-600 sm:m-4"><CircleAlert size={16} class="mt-0.5 shrink-0"/>{source.error}</p>
            {:else}
              <div class="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 sm:p-4 xl:grid-cols-3" aria-label={`Daftar file album ${source.title || source.source_index + 1}`}>
                {#each pageFiles as file (file.item_id)}
                  {@const key = fileKey(source.source_index, file.item_id)}
                  {@const isSelected = source.kind === 'direct' || Boolean(selectedFiles[key])}
                  <label class={`group min-w-0 overflow-hidden rounded-xl border bg-[var(--panel-soft)] transition duration-200 ${isSelected ? 'border-[var(--brand)] shadow-[0_0_0_1px_var(--brand-soft)]' : 'border-[var(--line)] hover:border-[var(--line-bright)]'}`}>
                    <span class="relative block aspect-video overflow-hidden bg-[var(--surface)]">
                      {#if file.thumbnail_url}
                        <img class="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" src={file.thumbnail_url} alt={file.file_name} loading="lazy" referrerpolicy="no-referrer" />
                      {:else}
                        <span class="grid h-full place-items-center bg-[radial-gradient(ellipse_at_top,var(--brand-soft),transparent_65%)]">
                          {#if thumbnailLoading[key]}<span class="muted px-2 text-center text-xs">Memuat thumbnail…</span>
                          {:else}<Download class="text-[var(--muted-dim)]" size={25}/>{/if}
                        </span>
                      {/if}
                      <input
                        type="checkbox"
                        class="absolute left-2.5 top-2.5 z-10 h-5 w-5 cursor-pointer accent-[var(--brand)]"
                        aria-label={`Pilih ${file.file_name}`}
                        checked={isSelected}
                        disabled={source.kind === 'direct'}
                        onchange={(event) => {
                          selectedFiles = { ...selectedFiles, [key]: (event.currentTarget as HTMLInputElement).checked };
                        }}
                      />
                      {#if isSelected}<span class="absolute right-2 top-2 rounded-full border border-[var(--brand)] bg-[var(--canvas)]/90 px-2 py-1 text-[10px] font-bold text-[var(--brand)]">Dipilih</span>{/if}
                    </span>
                    <span class="flex min-h-[68px] items-center justify-between gap-3 p-3">
                      <span class="min-w-0">
                        <span class="block line-clamp-2 break-all text-sm font-semibold">{file.file_name}</span>
                        <span class="muted mt-1 block text-[11px]">{source.kind === 'direct' ? 'URL langsung' : 'File album'}</span>
                      </span>
                      <span class={`grid h-7 w-7 shrink-0 place-items-center rounded-full border text-xs ${isSelected ? 'border-[var(--brand)] bg-[var(--brand-soft)] text-[var(--brand)]' : 'border-[var(--line-bright)] text-[var(--muted)]'}`} aria-hidden="true">{isSelected ? '✓' : '+'}</span>
                    </span>
                  </label>
                {/each}
              </div>
              {#if source.kind === 'album' && totalPages > 1}
                <footer class="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--line)] bg-[var(--panel-soft)] px-3 py-3 sm:px-4">
                  <span class="muted text-xs tabular-nums" aria-live="polite">
                    Menampilkan {page * FILES_PER_PAGE + 1}–{Math.min((page + 1) * FILES_PER_PAGE, source.files.length)} dari {source.files.length} file
                  </span>
                  <div class="flex items-center gap-2">
                    <button class="button secondary !px-3 !py-1.5" type="button" aria-label={`Halaman sebelumnya ${source.title}`} disabled={page === 0} onclick={() => changePage(source, page - 1)}>Sebelumnya</button>
                    <span class="muted min-w-24 text-center text-xs">Halaman {page + 1} dari {totalPages}</span>
                    <button class="button secondary !px-3 !py-1.5" type="button" aria-label={`Halaman berikutnya ${source.title}`} disabled={page + 1 >= totalPages} onclick={() => changePage(source, page + 1)}>Berikutnya</button>
                  </div>
                </footer>
              {/if}
            {/if}
          </article>
        {/each}
      </div>
    </section>
  {/if}

  <section class="card p-4" aria-labelledby="bunkr-task-title">
    <header class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div><p class="eyebrow">ARIA2 LINKS</p><h2 id="bunkr-task-title" class="mt-1 text-lg font-extrabold">Task dan retry otomatis</h2><p class="muted mt-1 text-xs">Status diperbarui otomatis hanya saat ada task aktif atau URL sedang dicoba ulang.</p></div>
      <button class="button secondary" type="button" onclick={() => loadTasks()} disabled={loadingTasks}>
        <RefreshCw size={15} class={loadingTasks ? 'animate-spin' : ''}/>{loadingTasks ? 'Memuat…' : 'Muat status'}
      </button>
    </header>
    <div class="responsive-card-table">
      <table class="mobile-card-table w-full min-w-[760px] text-left text-sm">
        <thead class="border-b border-[var(--line)] text-xs uppercase text-[var(--muted)]"><tr><th class="py-3">File</th><th>Status</th><th>Progres</th><th>Kecepatan</th><th>Rute</th><th>Aksi</th></tr></thead>
        <tbody class="divide-y divide-[var(--line)]">
          {#each tasks as task (task.gid)}
            {@const progress = percent(task)}
            <tr>
              <td class="py-3 font-semibold" data-label="File"><span class="block max-w-64 break-all">{task.file_name}</span><span class="muted text-[11px]">{task.kind === 'bunkr' ? 'Bunkr' : 'URL langsung'} · {task.gid}</span></td>
              <td data-label="Status"><span class={`badge ${task.status === 'error' || task.status === 'held' ? 'error' : task.status === 'complete' ? 'success' : ''}`}>{statusLabel(task)}</span>{#if task.reason_code && task.status !== 'refreshing'}<span class="muted mt-1 block text-xs">{task.reason_code}</span>{/if}</td>
              <td data-label="Progres"><span class="tabular-nums">{formatBytes(task.completed_bytes)}{task.total_bytes > 0 ? ` / ${formatBytes(task.total_bytes)}` : ''}</span>{#if task.total_bytes > 0}<div class="mt-1 h-1.5 w-32 overflow-hidden rounded-full bg-[var(--line)]"><div class="h-full rounded-full bg-[var(--brand)]" style={`width:${progress}%`}></div></div>{/if}</td>
              <td data-label="Kecepatan" class="tabular-nums">{task.speed_bytes_per_second > 0 ? `${formatBytes(task.speed_bytes_per_second)}/s` : '—'}</td>
              <td data-label="Rute"><span class="badge">{task.route.toUpperCase()}</span></td>
              <td data-label="Aksi"><div class="flex flex-wrap gap-1">
                {#if task.status === 'active' || task.status === 'waiting'}
                  <button class="button secondary !px-2 !py-1" type="button" onclick={() => controlTask(task, 'pause')} disabled={taskAction === `${task.gid}:pause`} aria-label={`Jeda ${task.file_name}`}><Pause size={14}/></button>
                {/if}
                {#if task.status === 'paused' || (task.status === 'held' && task.reason_code === 'ARIA2_TOR_UNAVAILABLE')}
                  <select class="field !w-auto !py-1" aria-label={`Rute ${task.file_name}`} value={task.route} onchange={(event) => void controlTask(task, 'route', (event.currentTarget as HTMLSelectElement).value as 'non' | 'tor')}>
                    <option value="non">Non</option><option value="tor">Tor</option>
                  </select>
                  <button class="button secondary !px-2 !py-1" type="button" onclick={() => controlTask(task, 'resume')} disabled={taskAction === `${task.gid}:resume`} aria-label={`Lanjutkan ${task.file_name}`}><Play size={14}/></button>
                {/if}
                {#if task.status === 'complete'}<span class="text-emerald-600">Selesai</span>{/if}
              </div></td>
            </tr>
          {:else}
            <tr><td colspan="6" class="muted py-10 text-center">{loadingTasks ? 'Memuat task…' : 'Belum ada task pada worker ini.'}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
</section>
