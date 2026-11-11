<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  import { page } from '$app/state';
  import { session } from '$lib/session.svelte';
  import { profileOptionLabel } from '$lib/profile-catalog';
  import Login from './Login.svelte';
  import RequestIndicator from './RequestIndicator.svelte';
  import {
    Activity, Archive, Boxes, ChevronLeft, ChevronRight, Code2, Download, FileDown,
    HardDrive, KeyRound, LayoutDashboard, LogOut, Menu, MessageCircle, Moon,
    Monitor, Server, Settings, Sun, UserRoundPlus, Users, Volume2, Wrench, X, Zap
  } from '@lucide/svelte';

  let { children } = $props();

  type Theme = 'light' | 'dark' | 'system';
  type NavigationLink = { href: string; label: string; icon: typeof LayoutDashboard };
  const navigationGroups: Array<{ label: string; links: NavigationLink[] }> = [
    { label: 'Monitor', links: [
      { href: '/', label: 'Ringkasan', icon: LayoutDashboard },
      { href: '/activity/', label: 'Aktivitas', icon: Activity }
    ] },
    { label: 'Transfer', links: [
      { href: '/storage/', label: 'Storage', icon: HardDrive },
      { href: '/downloads/', label: 'Download', icon: Download },
      { href: '/aria2/', label: 'AriaNg', icon: Boxes },
      { href: '/chat-send/', label: 'Kirim ke Chat', icon: MessageCircle }
    ] },
    { label: 'Pemrosesan', links: [
      { href: '/exports/', label: 'Export', icon: FileDown },
      { href: '/quick-mode/', label: 'Quick Mode', icon: Zap },
      { href: '/tts/', label: 'TTS', icon: Volume2 },
      { href: '/decrypt/', label: 'Dekripsi', icon: KeyRound },
      { href: '/utility/', label: 'Utility', icon: Wrench },
      { href: '/backups/', label: 'Backup', icon: Archive }
    ] },
    { label: 'Sistem', links: [
      { href: '/profiles/', label: 'Profil / Vault', icon: UserRoundPlus },
      { href: '/workers/', label: 'Workers', icon: Users },
      { href: '/settings/', label: 'Pengaturan', icon: Settings },
      { href: '/development/', label: 'Pengembangan', icon: Code2 }
    ] }
  ];

  let mobileOpen = $state(false);
  let collapsed = $state(false);
  let theme = $state<Theme>('dark');
  let themeMenuOpen = $state(false);
  let actorMenuOpen = $state(false);
  let mobileTrigger: HTMLButtonElement | null = $state(null);
  let mobileCloseButton: HTMLButtonElement | null = $state(null);
  let mobileDrawer: HTMLElement | null = $state(null);
  let themeMenuElement: HTMLDivElement | null = $state(null);
  let accountMenuElement: HTMLDivElement | null = $state(null);
  let motionDuration = $state(220);

  const active = (href: string) => href === '/' ? page.url.pathname === '/' : page.url.pathname === href || page.url.pathname.startsWith(href);
  const titleForPath = (pathname: string) => {
    if (pathname.startsWith('/profiles/vault')) return 'Vault profil';
    for (const group of navigationGroups) {
      const match = group.links.find((link) => active(link.href));
      if (match) return match.label;
    }
    return 'TME3Bot';
  };
  const labelForTheme = (value: Theme) => value === 'light' ? 'Terang' : value === 'dark' ? 'Gelap' : 'Sistem';

  function applyTheme(value: Theme) {
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const dark = value === 'dark' || (value === 'system' && systemDark);
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }

  function setTheme(next: Theme) {
    theme = next;
    localStorage.setItem('tme3-theme', next);
    applyTheme(next);
    themeMenuOpen = false;
  }

  function toggleCollapsed() {
    collapsed = !collapsed;
    localStorage.setItem('tme3-sidebar-collapsed', String(collapsed));
  }

  function chooseTargetProfile(value: string) {
    session.chooseTargetProfile(value);
  }

  async function openMobileNav() {
    mobileOpen = true;
    await tick();
    mobileCloseButton?.focus();
  }

  async function closeMobileNav() {
    mobileOpen = false;
    await tick();
    mobileTrigger?.focus();
  }

  function handleGlobalKeydown(event: KeyboardEvent) {
    if (event.defaultPrevented) return;
    if (event.key === 'Escape') {
      if (mobileOpen) void closeMobileNav();
      themeMenuOpen = false;
      actorMenuOpen = false;
    }
  }

  function handleWindowClick(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (themeMenuOpen && !themeMenuElement?.contains(target)) themeMenuOpen = false;
    if (actorMenuOpen && !accountMenuElement?.contains(target)) actorMenuOpen = false;
  }

  function handleDrawerKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      void closeMobileNav();
      return;
    }
    if (event.key !== 'Tab' || !mobileDrawer) return;
    const focusable = [...mobileDrawer.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter((element) => !element.hasAttribute('hidden'));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  onMount(() => {
    collapsed = localStorage.getItem('tme3-sidebar-collapsed') === 'true';
    const savedTheme = localStorage.getItem('tme3-theme');
    theme = savedTheme === 'light' || savedTheme === 'system' ? savedTheme : 'dark';
    applyTheme(theme);
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    motionDuration = motionQuery.matches ? 0 : 220;
    const updateMotion = (event: MediaQueryListEvent) => { motionDuration = event.matches ? 0 : 220; };
    motionQuery.addEventListener?.('change', updateMotion);
    const themeQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const updateSystemTheme = () => { if (theme === 'system') applyTheme(theme); };
    themeQuery.addEventListener?.('change', updateSystemTheme);
    session.restore();
    return () => {
      motionQuery.removeEventListener?.('change', updateMotion);
      themeQuery.removeEventListener?.('change', updateSystemTheme);
    };
  });
</script>

<svelte:window onkeydown={handleGlobalKeydown} onclick={handleWindowClick} />
<a class="skip-link" href="#main-content">Lewati ke konten</a>
<RequestIndicator />

{#snippet navigation(scope: string, onNavigate: (() => void) | undefined = undefined)}
  <nav class="side-nav" aria-label="Menu utama">
    {#each navigationGroups as group}
      <section class="nav-group" aria-label={group.label}>
        <h2 class="nav-group-title">{group.label}</h2>
        {#each group.links as link}
          {@const Icon = link.icon}
          {@const id = `${scope}-${link.href === '/' ? 'home' : link.href.replaceAll('/', '-')}`}
          <a
            id={id}
            class="nav-link"
            class:active={active(link.href)}
            href={link.href}
            title={collapsed && scope === 'desktop-nav' ? link.label : undefined}
            aria-label={collapsed && scope === 'desktop-nav' ? link.label : undefined}
            aria-current={active(link.href) ? 'page' : undefined}
            onclick={onNavigate}
          >
            <span class="nav-symbol"><Icon size={17} strokeWidth={1.9}/></span>
            <span class="nav-label">{link.label}</span>
            {#if active(link.href)}<span class="nav-active-mark" aria-hidden="true"></span>{/if}
          </a>
        {/each}
      </section>
    {/each}
  </nav>
{/snippet}

{#if session.loading}
  <main class="boot-screen" id="main-content">
    <section class="boot-card"><div class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></div><p class="eyebrow">TME3BOT · OPERATIONS</p><h1>Menyiapkan ruang kerja</h1><p class="muted">Memuat sesi aman dan status control plane.</p></section>
  </main>
{:else if !session.current.authenticated}
  <Login />
{:else}
  <div class="application" class:sidebar-is-collapsed={collapsed}>
    <aside class="app-sidebar" aria-label="Navigasi utama">
      <div class="sidebar-brand">
        <a class="brand-lockup" href="/" aria-label="TME3Bot Ringkasan">
          <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
          <span class="brand-name"><strong>TME3Bot</strong><small>Operations</small></span>
        </a>
        <button class="icon-button collapse-control" type="button" onclick={toggleCollapsed} aria-label={collapsed ? 'Lebarkan sidebar' : 'Ringkas sidebar'} aria-expanded={!collapsed}>
          {#if collapsed}<ChevronRight size={16}/>{:else}<ChevronLeft size={16}/>{/if}
        </button>
      </div>
      {@render navigation('desktop-nav')}
      <footer class="sidebar-footer">
        <div class="worker-summary"><span class="route-mark"><Server size={14}/></span><span class="worker-summary-text"><strong>{session.current.actor?.worker_route || 'Belum dipilih'}</strong><small>Worker route profil</small></span></div>
        <span class="sidebar-version">TME3BOT CONTROL</span>
      </footer>
    </aside>

    <div class="main-column">
      <div id="main-content" class="sr-only" tabindex="-1"></div>
      <header class="topbar">
        <div class="topbar-start">
          <button bind:this={mobileTrigger} class="icon-button mobile-menu" type="button" aria-label="Buka navigasi" aria-expanded={mobileOpen} onclick={openMobileNav}><Menu size={19}/></button>
          <div class="breadcrumb"><span>OPERATIONS</span><i aria-hidden="true">/</i><strong>{titleForPath(page.url.pathname)}</strong></div>
        </div>
        <div class="topbar-end">
          <label class="target-picker"><span>Profil target</span>
            <select aria-label="Profil target default" value={session.selectedTargetProfile} onchange={(event) => chooseTargetProfile(event.currentTarget.value)} disabled={session.profileCatalog.length < 2}>
              {#if !session.profileCatalog.length}<option value="">Belum scan</option>{/if}
              {#each session.profileCatalog as profile}<option value={profile.name}>{profileOptionLabel(profile)}</option>{/each}
            </select>
          </label>
          <span class="backend-status"><i></i><span>Backend online</span></span>
          <a class="icon-button decrypt-shortcut" href="/decrypt/" aria-label="Buka dekripsi teks" title="Dekripsi teks"><KeyRound size={16}/></a>
          <div bind:this={themeMenuElement} class="theme-menu">
            <button class="icon-button" type="button" aria-label="Pilih tema" aria-expanded={themeMenuOpen} onclick={() => themeMenuOpen = !themeMenuOpen}>
              {#if theme === 'dark'}<Moon size={16}/>{:else if theme === 'light'}<Sun size={16}/>{:else}<Monitor size={16}/>{/if}
            </button>
            {#if themeMenuOpen}
              <div class="theme-popover" role="menu" aria-label="Pilihan tema">
                {#each ['dark', 'light', 'system'] as option}
                  <button role="menuitem" class:chosen={theme === option} type="button" onclick={() => setTheme(option as Theme)}>{labelForTheme(option as Theme)}{#if theme === option}<span aria-hidden="true">✓</span>{/if}</button>
                {/each}
              </div>
            {/if}
          </div>
          <div bind:this={accountMenuElement} class="account-menu">
            <button class="account-trigger" type="button" aria-label="Menu akun" aria-expanded={actorMenuOpen} onclick={() => actorMenuOpen = !actorMenuOpen}>
              <span class="account-avatar">{String(session.current.actor?.telegram_user_id || '?').slice(-2)}</span>
              <span class="account-id">{session.current.actor?.telegram_user_id}</span>
              <span aria-hidden="true">⌄</span>
            </button>
            {#if actorMenuOpen}
              <div class="account-popover">
                <small>Telegram user</small><strong>{session.current.actor?.telegram_user_id}</strong>
                <small>Identity profile</small><strong>{session.current.actor?.profile || '—'}</strong>
                <button class="logout-button" type="button" onclick={() => session.logout()}><LogOut size={14}/>Keluar</button>
              </div>
            {/if}
          </div>
        </div>
      </header>

      <section class="page-content">
        {#key page.url.pathname}
          <div class="route-transition">{@render children?.()}</div>
        {/key}
      </section>
    </div>
  </div>

  {#if mobileOpen}
    <div class="mobile-overlay" role="presentation" onclick={(event) => { if (event.target === event.currentTarget) void closeMobileNav(); }} transition:fade={{ duration: motionDuration }}>
      <div bind:this={mobileDrawer} class="mobile-drawer" role="dialog" aria-modal="true" aria-label="Navigasi mobile" tabindex="-1" onkeydown={handleDrawerKeydown} transition:fly={{ x: -22, duration: motionDuration }}>
        <div class="sidebar-brand">
          <a class="brand-lockup" href="/" onclick={closeMobileNav}><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span class="brand-name"><strong>TME3Bot</strong><small>Operations</small></span></a>
          <button bind:this={mobileCloseButton} class="icon-button" type="button" aria-label="Tutup navigasi" onclick={closeMobileNav}><X size={17}/></button>
        </div>
        {@render navigation('mobile-nav', closeMobileNav)}
        <div class="worker-summary mobile-worker"><span class="route-mark"><Server size={14}/></span><span class="worker-summary-text"><strong>{session.current.actor?.worker_route || 'Belum dipilih'}</strong><small>Worker route profil</small></span></div>
      </div>
    </div>
  {/if}
{/if}
