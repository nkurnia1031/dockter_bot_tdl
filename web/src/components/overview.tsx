"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Archive, CloudDownload, DatabaseBackup, HardDrive, Server } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "@/lib/api";
import { Card } from "./ui";
import { JobList, PageHeader } from "./page";

type Summary = {profile: string; worker: string; jobs: {active: number; failed: number}; artifacts: Record<string, number>; storage: {has_items: boolean}; last_backup?: {started_at: string; status: string}};

export function Overview() {
  const query = useQuery<Summary>({queryKey: ["summary"], queryFn: () => api("/dashboard/summary"), refetchInterval: 5000});
  const data = query.data;
  const cards = [
    ["Worker aktif", data?.worker || "—", Server, "Route profile saat ini"],
    ["Job berjalan", data?.jobs.active ?? "—", Activity, `${data?.jobs.failed || 0} gagal belum diarsipkan`],
    ["JSON pending", data?.artifacts.pending ?? "—", CloudDownload, `${data?.artifacts.downloaded || 0} selesai`],
    ["Storage", data?.storage.has_items ? "Aktif" : "Kosong", Archive, "Katalog channel global"],
    ["Backup terakhir", data?.last_backup ? new Date(data.last_backup.started_at).toLocaleDateString("id-ID") : "Belum ada", DatabaseBackup, data?.last_backup?.status || "Jalankan backup pertama"],
  ] as const;
  const chart = Object.entries(data?.artifacts || {}).map(([name, value]) => ({name, value}));
  return <><PageHeader eyebrow="Overview" title={`Selamat datang di profile ${data?.profile || "…"}`} description="Pantau antrean, worker, storage, dan backup dari satu control plane."/>
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{cards.map(([label, value, Icon, hint]) => <Card key={label} className="min-h-36"><div className="flex items-start justify-between"><span className="muted text-sm">{label}</span><span className="grid size-9 place-items-center rounded-xl bg-[var(--brand-soft)] text-[var(--brand)]"><Icon className="size-4"/></span></div><p className="mt-5 truncate text-2xl font-bold">{value}</p><p className="muted mt-1 text-xs">{hint}</p></Card>)}</div>
    <div className="mt-5 grid gap-5 xl:grid-cols-[1.45fr_.55fr]"><JobList/><Card><h2 className="font-bold">Distribusi JSON</h2>{chart.length ? <div className="mt-3 h-64"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={chart} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={4}>{chart.map((_, index) => <Cell key={index} fill={["#5b5ce2","#22c55e","#f59e0b","#ef4444","#06b6d4"][index % 5]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer></div> : <div className="muted grid h-64 place-items-center text-sm"><HardDrive className="size-8"/>Belum ada artifact</div>}</Card></div>
  </>;
}
