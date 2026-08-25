<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { Drawer, Dropdown, DropdownItem, Sidebar, Toast, Tooltip } from 'flowbite-svelte';
  import { session } from '$lib/session.svelte';
  import Login from './Login.svelte';
  import {
    Activity, Archive, Boxes, ChevronLeft, ChevronRight, Download, FileDown, HardDrive,
    LayoutDashboard, LogOut, Menu, Moon, Server, Settings, Sun, Users, Wrench
  } from '@lucide/svelte';

  let { children } = $props();

  type Theme = 'light' | 'dark' | 'system';
  const links = [
    { href: '/', label: 'Ringkasan', icon: LayoutDashboard },
    { href: '/exports/', label: 'Export', icon: FileDown },
    { href: '/downloads/', label: 'Download', icon: Download },
    { href: '/utility/', label: 'Utility', icon: Wrench },
    { href: '/storage/', label: 'Storage', icon: HardDrive },
    { href: '/activity/', label: 'Aktivitas', icon: Activity },
    { href: '/workers/', label: 'Workers', icon: Users },
    { href: '/backups/', label: 'Backup', icon: Archive },
    { href: '/settings/', label: 'Pengaturan', icon: Settings }
  ];

  let mobileOpen = $state(false);
  let collapsed = $state(false);
  let theme = $state<Theme>('light');
  let themeMenuOpen = $state(false);
  let actorMenuOpen = $state(false);
  let contextToast = $state(false);
  let contextError = $state('');

  const active = (href: string) => page.url.pathname === href || (href !== '/' && page.url.pathname.startsWith(href));
  const labelForTheme = (value: Theme) => value === 'light' ? 'Terang' : value === 'dark' ? 'Gelap' : 'Sistem';

  function setTheme(next: Theme) {
    theme = next;
    localStorage.setItem('tme3-theme', next);
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.classList.toggle('dark', next === 'dark' || (next === 'system' && systemDark));
    themeMenuOpen = false;
  }

  function toggleCollapsed() {
    collapsed = !collapsed;
    localStorage.setItem('tme3-sidebar-collapsed', String(collapsed));
  }

  async function chooseProfile(value: string) {
    try {
      await session.chooseProfile(value);
    } catch (cause) {
      contextError = cause instanceof Error ? cause.message : 'Profile gagal diganti.';
      contextToast = true;
    }
  }

  async function chooseWorker(value: string) {
    try {
      await session.chooseWorker(value);
    } catch (cause) {
      contextError = cause instanceof Error ? cause.message : 'Worker gagal diganti.';
      contextToast = true;
    }
  }

  onMount(() => {
    collapsed = localStorage.getItem('tme3-sidebar-collapsed') === 'true';
    const savedTheme = localStorage.getItem('tme3-theme');
    setTheme(savedTheme === 'dark' || savedTheme === 'system' ? savedTheme : 'light');
    session.restore();
  });
</script>

{#snippet navigation(compact = false, onNavigate: (() => void) | undefined = undefined, scope = 'nav')}
  <nav class="grid gap-1.5" aria-label="Menu utama">
    {#each links as link}
      {@const Icon = link.icon}
      <a
        id={`${scope}-${link.label.toLowerCase()}`}
        class:active={active(link.href)}
        class:compact
        class="nav-link group"
        href={link.href}
        onclick={onNavigate}
      >
        <Icon size={18} strokeWidth={2.1} />
        <span class="nav-label">{link.label}</span>
      </a>
      {#if compact}<Tooltip triggeredBy={`#${scope}-${link.label.toLowerCase()}`} placement="right">{link.label}</Tooltip>{/if}
    {/each}
  </nav>
{/snippet}

{#if session.loading}
  <main class="grid min-h-screen place-items-center p-5">
    <div class="card w-full max-w-sm p-7 text-center page-enter"><div class="mx-auto mb-4 size-9 animate-pulse rounded-xl bg-violet-200"></div><p class="font-semibold">Memuat sesi aman...</p><p class="muted mt-1 text-sm">Menyiapkan control center Anda.</p></div>
  </main>
{:else if !session.current.authenticated}
  <Login />
{:else}
  <div class:sidebar-collapsed={collapsed} class="app-shell min-h-screen lg:grid lg:grid-cols-[17.5rem_1fr]">
    <aside class="app-sidebar hidden border-r border-[var(--line)] lg:block">
      <Sidebar disableBreakpoints isOpen={true} class="!static !block !h-full !w-full !bg-transparent" classes={{ div: '!overflow-visible !bg-transparent !p-4' }}>
        <div class="flex h-full flex-col">
          <div class="mb-8 flex items-center gap-3 px-2">
            <div class="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-500 text-white shadow-lg shadow-violet-500/20"><Boxes size={21}/></div>
            <div class="brand-copy min-w-0"><b class="block text-base tracking-tight">tme3</b><p class="muted text-xs">Control center</p></div>
            <button class="collapse-button button ghost ms-auto hidden size-8 !p-0 lg:inline-flex" onclick={toggleCollapsed} aria-label={collapsed ? 'Lebarkan sidebar' : 'Ringkas sidebar'}>{#if collapsed}<ChevronRight size={17}/>{:else}<ChevronLeft size={17}/>{/if}</button>
          </div>
          {@render navigation(collapsed, undefined, 'desktop-nav')}
          <div class="mt-auto pt-6">
            <div class="worker-card rounded-2xl p-3.5">
              <p class="worker-label text-xs font-bold uppercase tracking-[.13em]">Worker aktif</p>
              <b class="mt-1 block truncate text-sm">{session.current.actor?.worker_route || '-'}</b>
              <span class="mt-2 inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-300"><i class="size-1.5 rounded-full bg-emerald-500"></i>Tersambung</span>
            </div>
          </div>
        </div>
      </Sidebar>
    </aside>

    <main class="min-w-0">
      <header class="topbar sticky top-0 z-20 border-b border-[var(--line)] bg-[color:var(--panel)]/92 px-3 py-2.5 backdrop-blur-xl sm:px-6 sm:py-3">
        <div class="flex min-w-0 items-center justify-between gap-2 sm:gap-3">
          <div class="topbar-left flex min-w-0 flex-1 items-center gap-2">
            <button class="button secondary menu-trigger size-10 shrink-0 !rounded-xl !p-0 lg:hidden" onclick={() => mobileOpen = true} aria-label="Buka navigasi"><Menu size={19}/></button>
            <div class="flex min-w-0 items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] px-3 py-2">
              <Users class="shrink-0 text-violet-500" size={15}/><div class="min-w-0"><p class="muted truncate text-[.65rem] font-bold uppercase tracking-[.12em]">Actor profile</p><b class="block max-w-28 truncate text-sm">{session.current.actor?.profile || '-'}</b></div>
            </div>
            <div class="hidden min-w-0 items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--panel-strong)] px-3 py-2 md:flex"><Server class="shrink-0 text-sky-500" size={15}/><div><p class="muted text-[.65rem] font-bold uppercase tracking-[.12em]">Target</p><span class="text-xs font-semibold text-[var(--muted)]">Dipilih per fitur</span></div></div>
            <span class="hidden items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-bold text-emerald-700 md:inline-flex dark:bg-emerald-950 dark:text-emerald-300"><i class="size-1.5 rounded-full bg-emerald-500"></i>Backend online</span>
          </div>
          <div class="topbar-actions flex shrink-0 items-center gap-1.5 sm:gap-2">
            <button id="theme-trigger" class="button secondary theme-trigger hidden size-10 !rounded-xl !p-0 sm:inline-flex" aria-label="Pilih tema"><span class="sr-only">Tema {labelForTheme(theme)}</span>{#if theme === 'dark'}<Moon size={17}/>{:else}<Sun size={17}/>{/if}</button>
            <Dropdown bind:isOpen={themeMenuOpen} triggeredBy="#theme-trigger" placement="bottom-end" class="!z-50 !w-40 !rounded-xl !border-[var(--line)] !bg-[var(--panel-strong)] !p-1 !shadow-xl" simple>
              {#each ['light', 'dark', 'system'] as option}<DropdownItem onclick={() => setTheme(option as Theme)} class="!rounded-lg !px-3 !py-2 !text-sm !text-[var(--ink)] hover:!bg-[var(--brand-soft)]">{labelForTheme(option as Theme)}{#if theme === option}<span class="float-right text-violet-600">&#10003;</span>{/if}</DropdownItem>{/each}
            </Dropdown>
            <button id="actor-trigger" class="button secondary flex size-10 max-w-40 items-center justify-center gap-2 !rounded-xl !p-0 sm:h-10 sm:justify-start sm:!px-3" aria-label="Menu akun"><span class="grid size-6 place-items-center rounded-full bg-violet-100 text-xs font-bold text-violet-700 dark:bg-violet-900 dark:text-violet-200">{String(session.current.actor?.telegram_user_id || '?').slice(-2)}</span><span class="hidden truncate text-xs font-bold sm:block">{session.current.actor?.telegram_user_id}</span></button>
            <Dropdown bind:isOpen={actorMenuOpen} triggeredBy="#actor-trigger" placement="bottom-end" class="!z-50 !w-52 !rounded-xl !border-[var(--line)] !bg-[var(--panel-strong)] !p-1 !shadow-xl" simple>
              <div class="border-b border-[var(--line)] px-3 py-2 text-xs"><p class="muted">Telegram user</p><b class="text-[var(--ink)]">{session.current.actor?.telegram_user_id}</b></div>
              <DropdownItem onclick={() => session.logout()} class="!mt-1 !rounded-lg !px-3 !py-2 !text-rose-600 hover:!bg-rose-50 dark:hover:!bg-rose-950"><LogOut size={15} class="mr-2 inline"/>Keluar</DropdownItem>
            </Dropdown>
          </div>
        </div>
      </header>
      <section class="mx-auto max-w-[96rem] p-4 sm:p-6 lg:p-8"><div class="page-enter">{@render children?.()}</div></section>
    </main>
  </div>

  <Drawer bind:open={mobileOpen} placement="left" outsideclose={true} class="!w-[18rem] !border-r !border-[var(--line)] !bg-[var(--panel-strong)] !p-0" transitionParams={{ x: -28, duration: 240 }} aria-label="Navigasi mobile">
    <div class="flex min-h-full flex-col p-4">
      <div class="mb-8 flex items-center gap-3 px-2"><div class="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-500 text-white"><Boxes size={21}/></div><div><b>tme3</b><p class="muted text-xs">Control center</p></div></div>
      {@render navigation(false, () => mobileOpen = false, 'mobile-nav')}
      <div class="mt-auto worker-card rounded-2xl p-3.5"><p class="worker-label text-xs font-bold uppercase tracking-[.13em]">Worker aktif</p><b class="mt-1 block truncate text-sm">{session.current.actor?.worker_route || '-'}</b></div>
    </div>
  </Drawer>
  <Toast bind:toastStatus={contextToast} position="bottom-right" color="red">{contextError}</Toast>
{/if}

<style>
  .app-shell { transition: grid-template-columns .24s cubic-bezier(.16, 1, .3, 1); }
  .topbar { box-shadow: 0 1px 0 color-mix(in srgb, var(--line) 75%, transparent); }
  .app-sidebar { background: color-mix(in srgb, var(--panel-strong) 92%, transparent); }
  .sidebar-collapsed { grid-template-columns: 5.5rem 1fr; }
  .sidebar-collapsed .brand-copy, .sidebar-collapsed .nav-label, .sidebar-collapsed .worker-card { display: none; }
  .sidebar-collapsed .collapse-button { margin-left: auto; }
  :global(.nav-link) { display: flex; align-items: center; gap: .72rem; border-radius: .8rem; padding: .72rem .8rem; color: var(--muted); font-size: .9rem; font-weight: 650; text-decoration: none; transition: background .18s ease, color .18s ease, transform .18s ease; }
  :global(.nav-link:hover) { color: var(--ink); background: var(--brand-soft); transform: translateX(2px); }
  :global(.nav-link.active) { color: var(--brand-strong); background: var(--brand-soft); box-shadow: inset 3px 0 0 var(--brand); }
  :global(.nav-link.compact) { justify-content: center; padding-inline: .5rem; }
  .worker-card { border: 1px solid color-mix(in srgb, var(--brand) 20%, var(--line)); background: linear-gradient(135deg, color-mix(in srgb, var(--brand-soft) 86%, transparent), transparent); }
  .worker-label { color: var(--brand); }
</style>
