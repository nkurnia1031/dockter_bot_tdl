"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock3, OctagonX, RefreshCw, Terminal, X } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, ConfirmDialog, Empty } from "./ui";

export function PageHeader({eyebrow, title, description, action}: {eyebrow: string; title: string; description: string; action?: React.ReactNode}) {
  return <div className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-end"><div><p className="text-xs font-bold uppercase tracking-[.18em] text-[var(--brand)]">{eyebrow}</p><h1 className="mt-2 text-2xl font-bold tracking-tight md:text-3xl">{title}</h1><p className="muted mt-2 max-w-2xl text-sm leading-6">{description}</p></div>{action}</div>;
}

export type Job = {
  id: string; kind: string; status: string; worker: string; progress: Record<string, unknown>;
  result?: Record<string, unknown>; error?: {message?: string}; created_at: string; updated_at: string;
};

type JobEvent = {
  sequence: number; event_type: string; status: string; created_at: string;
  progress: Record<string, unknown>; result?: Record<string, unknown> | null; error?: {message?: string} | null;
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

function JobLogDialog({job}: {job: Job}) {
  const [open, setOpen] = useState(false);
  const events = useQuery<{items: JobEvent[]}>({
    queryKey: ["job-log", job.id],
    queryFn: () => api(`/jobs/${job.id}/events`),
    enabled: open,
    staleTime: Infinity,
  });
  const snapshot = [...(events.data?.items || [])].reverse().find((event) => event.event_type === "log.snapshot")?.result?.log as {lines?: string[]; line_count?: number; truncated?: boolean} | undefined;
  const text = snapshot?.lines?.join("\n") || "Belum ada snapshot log untuk job ini. Job lama yang dibuat sebelum pembaruan tidak memiliki log tersimpan.";

  return <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger asChild><button className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-semibold text-[var(--brand)] hover:bg-[var(--brand-soft)]" aria-label={`Buka log ${job.kind}`}><Terminal className="size-3.5"/>Log</button></Dialog.Trigger><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm"/>
    <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[min(86vh,48rem)] w-[min(96vw,70rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-slate-700 bg-[#0b1020] text-slate-100 shadow-2xl">
      <header className="flex items-center justify-between border-b border-slate-700 px-5 py-4"><div className="min-w-0"><Dialog.Title className="flex items-center gap-2 font-bold"><Terminal className="size-4 text-emerald-400"/>Log job: {job.kind.replaceAll("_", " ")}</Dialog.Title><Dialog.Description className="mt-1 truncate font-mono text-xs text-slate-400">{job.id}</Dialog.Description></div><div className="flex items-center gap-2"><button onClick={() => events.refetch()} disabled={events.isFetching} className="inline-flex items-center gap-1 rounded-lg border border-slate-600 px-2.5 py-1.5 text-xs font-semibold hover:bg-slate-800 disabled:opacity-50"><RefreshCw className={`size-3.5 ${events.isFetching ? "animate-spin" : ""}`}/>Refresh</button><Dialog.Close className="rounded-lg p-2 hover:bg-slate-800" aria-label="Tutup log"><X className="size-4"/></Dialog.Close></div></header>
      <div className="flex-1 overflow-auto p-5"><pre className="whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-200">{events.isLoading ? "Memuat snapshot log…" : text}</pre></div>
      <footer className="border-t border-slate-700 px-5 py-3 text-xs text-slate-400">{snapshot ? `${snapshot.line_count || snapshot.lines?.length || 0} baris${snapshot.truncated ? " · dipotong pada batas penyimpanan" : ""}` : "Snapshot tidak realtime. Tekan Refresh untuk mengambil versi terbaru."}</footer>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}

function TerminateJobButton({job}: {job: Job}) {
  const client = useQueryClient();
  const terminate = useMutation({
    mutationFn: () => api(`/jobs/${job.id}/cancel`, {method: "POST"}),
    onSuccess: () => {
      client.invalidateQueries({queryKey: ["jobs"]});
      client.invalidateQueries({queryKey: ["job-log", job.id]});
    },
  });
  if (job.status !== "running") return null;
  return <ConfirmDialog title="Terminate job aktif?" description="Sistem mengirim interrupt setara Ctrl+C ke proses worker. File yang sedang diproses dapat tersisa sebagian." trigger={<button disabled={terminate.isPending} className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 px-2 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-500/10 disabled:opacity-50"><OctagonX className="size-3.5"/>Terminate</button>} onConfirm={() => terminate.mutate()}/>;
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
    <div className="divide-y">{jobs.data?.items.map((job) => <div key={job.id} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto] sm:items-center"><div className="min-w-0"><div className="flex items-center gap-2"><b className="truncate text-sm">{job.kind.replaceAll("_", " ")}</b><Badge tone={tone(job.status)}>{job.status}</Badge></div><p className="muted mt-1 truncate text-xs">{jobMessage(job)}</p></div><div className="flex flex-wrap items-center justify-between gap-2 sm:justify-end"><span className="muted flex items-center gap-1 text-xs"><Clock3 className="size-3"/>{new Date(job.updated_at).toLocaleString("id-ID")}</span><JobLogDialog job={job}/><TerminateJobButton job={job}/></div></div>)}</div>
  </Card>;
}

export function ProgressBar({value}: {value: number}) {
  return <div className="h-2 overflow-hidden rounded-full bg-[var(--line)]" role="progressbar" aria-valuenow={value}><div className="h-full rounded-full bg-[var(--brand)] transition-all" style={{width: `${Math.max(0, Math.min(value, 100))}%`}}/></div>;
}
