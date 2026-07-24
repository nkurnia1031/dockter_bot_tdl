"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { Activity, Archive, Bot, Boxes, ChevronDown, CloudDownload, DatabaseBackup, FileOutput, LayoutDashboard, LogOut, Menu, Moon, Settings, Sun, UsersRound, WandSparkles, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { Login } from "./login";

const links = [
  ["/", "Ringkasan", LayoutDashboard],
  ["/exports", "Export", FileOutput],
  ["/downloads", "Download", CloudDownload],
  ["/utility", "Utility", WandSparkles],
  ["/storage", "Storage", Archive],
  ["/activity", "Aktivitas", Activity],
  ["/workers", "Workers", Boxes],
  ["/backups", "Backup", DatabaseBackup],
  ["/settings", "Pengaturan", Settings],
] as const;

type Session = {actor: {telegram_user_id: number; profile: string; worker_route: string}; profiles: {name: string; selected: boolean; worker_route: string}[]};

export function AppShell({children}: {children: React.ReactNode}) {
  const path = usePathname();
  const client = useQueryClient();
  const {theme, setTheme} = useTheme();
  const [open, setOpen] = useState(false);
  const session = useQuery<Session>({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await fetch("/api/session", {cache: "no-store"});
      if (!response.ok) throw new Error("unauthorized");
      return response.json();
    },
    retry: false,
  });
  if (session.isLoading) return <div className="grid min-h-screen place-items-center"><div className="size-9 animate-spin rounded-full border-4 border-[var(--line)] border-t-[var(--brand)]"/></div>;
  if (session.isError || !session.data) return <Login/>;
  const actor = session.data.actor;

  async function switchProfile(profile: string) {
    const csrf = document.cookie.split("; ").find((item) => item.startsWith("tme3_csrf="))?.split("=")[1] || "";
    await fetch("/api/session", {method: "PUT", headers: {"Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf)}, body: JSON.stringify({profile})});
    await client.invalidateQueries();
    location.reload();
  }
  async function logout() {
    const csrf = document.cookie.split("; ").find((item) => item.startsWith("tme3_csrf="))?.split("=")[1] || "";
    await fetch("/api/auth/logout", {method: "POST", headers: {"X-CSRF-Token": decodeURIComponent(csrf)}});
    location.reload();
  }

  const sidebar = <aside className="flex h-full w-64 flex-col border-r bg-[var(--panel)] p-4">
    <Link href="/" className="mb-7 flex items-center gap-3 px-2"><span className="grid size-10 place-items-center rounded-2xl bg-[var(--brand)] text-white"><Bot className="size-5"/></span><span><b className="block">tme3</b><small className="muted">Control center</small></span></Link>
    <nav className="grid gap-1" aria-label="Navigasi utama">
      {links.map(([href, label, Icon]) => {
        const active = href === "/" ? path === href : path.startsWith(href);
        return <Link key={href} href={href} onClick={() => setOpen(false)} className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition", active ? "bg-[var(--brand-soft)] text-[var(--brand)]" : "muted hover:bg-[var(--surface)] hover:text-[var(--ink)]")}><Icon className="size-[18px]"/>{label}</Link>;
      })}
    </nav>
    <div className="mt-auto rounded-2xl bg-[var(--brand-soft)] p-3 text-sm"><p className="font-semibold text-[var(--brand)]">Worker aktif</p><p className="mt-1 truncate">{actor.worker_route}</p></div>
  </aside>;

  return <div className="min-h-screen lg:grid lg:grid-cols-[16rem_1fr]">
    <div className="hidden lg:block">{sidebar}</div>
    {open && <div className="fixed inset-0 z-40 lg:hidden"><button className="absolute inset-0 bg-black/40" aria-label="Tutup menu" onClick={() => setOpen(false)}/><div className="relative h-full w-64">{sidebar}<button className="absolute right-3 top-3" onClick={() => setOpen(false)}><X/></button></div></div>}
    <div className="min-w-0">
      <header className="sticky top-0 z-30 flex h-17 items-center gap-3 border-b bg-[color-mix(in_srgb,var(--panel)_88%,transparent)] px-4 backdrop-blur-xl md:px-7">
        <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Buka menu"><Menu/></button>
        <div className="relative">
          <select aria-label="Profile aktif" value={actor.profile} onChange={(event) => switchProfile(event.target.value)} className="appearance-none rounded-xl border bg-[var(--panel)] py-2 pl-3 pr-9 text-sm font-semibold">
            {session.data.profiles.map((profile) => <option key={profile.name}>{profile.name}</option>)}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 size-4"/>
        </div>
        <span className="hidden rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 sm:inline">● Backend online</span>
        <div className="ml-auto flex items-center gap-2">
          <button className="grid size-10 place-items-center rounded-xl border" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Ganti tema">{theme === "dark" ? <Sun className="size-4"/> : <Moon className="size-4"/>}</button>
          <div className="hidden items-center gap-2 rounded-xl border px-3 py-2 text-sm sm:flex"><UsersRound className="size-4"/><span>{actor.telegram_user_id}</span></div>
          <button className="grid size-10 place-items-center rounded-xl border text-rose-600" onClick={logout} aria-label="Keluar"><LogOut className="size-4"/></button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] p-4 md:p-7">{children}</main>
    </div>
  </div>;
}
