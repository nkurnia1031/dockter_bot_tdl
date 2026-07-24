"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock3, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Empty } from "./ui";

export function PageHeader({eyebrow, title, description, action}: {eyebrow: string; title: string; description: string; action?: React.ReactNode}) {
  return <div className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><p className="text-xs font-bold uppercase tracking-[.18em] text-[var(--brand)]">{eyebrow}</p><h1 className="mt-2 text-2xl font-bold tracking-tight md:text-3xl">{title}</h1><p className="muted mt-2 max-w-2xl text-sm leading-6">{description}</p></div>{action}</div>;
}

export type Job = {
  id: string; kind: string; status: string; worker: string; progress: Record<string, unknown>;
  result?: Record<string, unknown>; error?: {message?: string}; created_at: string; updated_at: string;
};

export function tone(status: string) {
  if (["succeeded", "downloaded", "complete", "active"].includes(status)) return "good" as const;
  if (["failed", "cancelled", "offline"].includes(status)) return "bad" as const;
  if (["running", "processing", "dispatched"].includes(status)) return "brand" as const;
  return "neutral" as const;
}

function utilitySummary(job: Job): string | null {
  if (job.kind !== "utility" || job.status !== "succeeded") return null;
  const value = (job.result?.value || {}) as {utility?: string; summary?: Record<string, unknown>};
  const summary = value.summary || {};
  const folders = Number(summary.folders_processed || 0);
  const failed = Number(summary.folders_failed || 0);
  const suffix = failed ? ` · ${failed} gagal` : "";
  if (value.utility === "export") {
    return `${folders} folder · ${Number(summary.groups_created || 0)} group dibuat · ${Number(summary.items_moved || 0)} item dipindahkan${suffix}`;
  }
  return `${folders} folder diproses · ${Number(summary.files_after || 0)} file${suffix}`;
}

function jobMessage(job: Job): string {
  return utilitySummary(job) || String(job.error?.message || job.progress?.message || (job.status === "succeeded" ? "Selesai" : `Worker ${job.worker}`));
}

export function JobList({kind, title = "Aktivitas terbaru", limit = 8}: {kind?: string; title?: string; limit?: number}) {
  const jobs = useQuery<{items: Job[]}>({
    queryKey: ["jobs", kind, limit],
    queryFn: () => api(`/jobs?archived=false&limit=${limit}${kind ? `&kind=${kind}` : ""}`),
    refetchInterval: (query) => {
      const items = (query.state.data as {items?: Job[]})?.items || [];
      return items.some((item) => ["queued", "dispatched", "running"].includes(item.status)) ? 1000 : 5000;
    },
  });
  return <Card><div className="mb-4 flex items-center justify-between"><h2 className="font-bold">{title}</h2><button onClick={() => jobs.refetch()} className="muted" aria-label="Muat ulang"><RefreshCw className="size-4"/></button></div>
    {jobs.isError && <div className="flex gap-2 rounded-xl bg-rose-50 p-3 text-sm text-rose-700"><AlertTriangle className="size-4"/>Gagal mengambil aktivitas.</div>}
    {!jobs.isLoading && !jobs.data?.items.length && <Empty title="Belum ada aktivitas" description="Job baru akan muncul di sini."/>}
    <div className="divide-y">{jobs.data?.items.map((job) => <div key={job.id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto] sm:items-center"><div className="min-w-0"><div className="flex items-center gap-2"><b className="truncate text-sm">{job.kind.replaceAll("_", " ")}</b><Badge tone={tone(job.status)}>{job.status}</Badge></div><p className="muted mt-1 truncate text-xs">{jobMessage(job)}</p></div><span className="muted flex items-center gap-1 text-xs"><Clock3 className="size-3"/>{new Date(job.updated_at).toLocaleString("id-ID")}</span></div>)}</div>
  </Card>;
}

export function ProgressBar({value}: {value: number}) {
  return <div className="h-2 overflow-hidden rounded-full bg-[var(--line)]" role="progressbar" aria-valuenow={value}><div className="h-full rounded-full bg-[var(--brand)] transition-all" style={{width: `${Math.max(0, Math.min(value, 100))}%`}}/></div>;
}
