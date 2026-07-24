"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Badge, Card, Empty, inputClass } from "./ui";
import { Job, PageHeader, tone } from "./page";

export function ActivityPage() {
  const params = useSearchParams();
  const status = params.get("status") || "";
  const jobs = useQuery<{items: Job[]; total: number}>({queryKey: ["activity", status], queryFn: () => api(`/jobs?limit=100&archived=false${status ? `&status=${status}` : ""}`), refetchInterval: 3000});
  return <><PageHeader eyebrow="Audit trail" title="Seluruh aktivitas" description="Riwayat persisten lintas Telegram dan web pada profile aktif."/><Card><div className="mb-4 flex items-center justify-between"><h2 className="font-bold">{jobs.data?.total || 0} job</h2><select className={`${inputClass} w-44`} value={status} onChange={(event) => {const url = new URL(location.href); event.target.value ? url.searchParams.set("status", event.target.value) : url.searchParams.delete("status"); location.href = url.toString();}}><option value="">Semua status</option><option>running</option><option>succeeded</option><option>failed</option><option>cancelled</option></select></div>{!jobs.data?.items.length ? <Empty title="Tidak ada aktivitas" description="Ubah filter atau jalankan job baru."/> : <div className="divide-y">{jobs.data.items.map((job) => <article key={job.id} className="grid gap-2 py-4 md:grid-cols-[1fr_auto]"><div><div className="flex items-center gap-2"><b>{job.kind.replaceAll("_", " ")}</b><Badge tone={tone(job.status)}>{job.status}</Badge></div><p className="muted mt-1 text-xs">{job.id} · {job.worker}</p><p className="mt-2 text-sm">{String(job.progress?.message || job.error?.message || "")}</p></div><time className="muted text-xs">{new Date(job.updated_at).toLocaleString("id-ID")}</time></article>)}</div>}</Card></>;
}
