"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpToLine, Download, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, formatBytes } from "@/lib/api";
import { Badge, Button, Card, Empty } from "./ui";
import { JobList, PageHeader, tone } from "./page";

type Artifact = {id: string; filename: string; status: string; worker: string; json_bytes?: number; message_count: number; media_count: number; photo_count: number; video_count: number; expected_media_bytes?: number; created_at: string};

export function DownloadsPage() {
  const client = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);
  const artifacts = useQuery<{items: Artifact[]; total: number}>({queryKey: ["artifacts"], queryFn: () => api("/downloads/artifacts?archived=false&limit=100"), refetchInterval: 3000});
  const run = useMutation({mutationFn: (priority: string) => api("/downloads", {method: "POST", body: JSON.stringify({artifact_ids: selected, priority})}), onSuccess: () => {setSelected([]); client.invalidateQueries({queryKey: ["jobs"]});}});
  const reconcile = useMutation({mutationFn: () => api("/downloads/artifacts/reconcile", {method: "POST"}), onSuccess: () => setTimeout(() => client.invalidateQueries({queryKey: ["artifacts"]}), 1200)});
  const pending = useMemo(() => artifacts.data?.items.filter((item) => ["pending", "failed"].includes(item.status)) || [], [artifacts.data]);
  return <><PageHeader eyebrow="Download manager" title="Antrean JSON & realtime progress" description="Prioritas next masuk tepat setelah operasi aktif. Job aktif tidak dihentikan." action={<Button busy={reconcile.isPending} onClick={() => reconcile.mutate()} className="bg-transparent text-[var(--ink)] border shadow-none"><RefreshCw className="size-4"/>Rekonsiliasi</Button>}/>
    <div className="grid gap-5 xl:grid-cols-[1.4fr_.6fr]"><Card><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold">Artifact siap diproses</h2><p className="muted mt-1 text-xs">{pending.length} pending/failed dari {artifacts.data?.total || 0} artifact</p></div><div className="flex gap-2"><Button disabled={!selected.length} onClick={() => run.mutate("next")} className="bg-transparent text-[var(--brand)] border border-[var(--brand)] shadow-none"><ArrowUpToLine className="size-4"/>Jadikan berikutnya</Button><Button disabled={!selected.length} onClick={() => run.mutate("normal")}><Download className="size-4"/>Mulai terpilih</Button></div></div>
      {!pending.length ? <Empty title="Antrean kosong" description="Lakukan export atau rekonsiliasi worker."/> : <div className="scrollbar overflow-x-auto"><table className="w-full min-w-[50rem] text-left text-sm"><thead className="muted border-b text-xs uppercase"><tr><th className="py-3"><span className="sr-only">Pilih</span></th><th>JSON</th><th>Media</th><th>Estimasi</th><th>Worker</th><th>Status</th></tr></thead><tbody>{pending.map((item) => <tr key={item.id} className="border-b last:border-0"><td className="py-3"><input type="checkbox" checked={selected.includes(item.id)} onChange={(event) => setSelected((old) => event.target.checked ? [...old, item.id] : old.filter((id) => id !== item.id))}/></td><td><b>{item.filename}</b><p className="muted text-xs">{formatBytes(item.json_bytes)} · {item.message_count} pesan</p></td><td>{item.media_count}<p className="muted text-xs">{item.photo_count} foto · {item.video_count} video</p></td><td>{formatBytes(item.expected_media_bytes)}</td><td>{item.worker}</td><td><Badge tone={tone(item.status)}>{item.status}</Badge></td></tr>)}</tbody></table></div>}
    </Card><JobList kind="download" title="Download aktif & terbaru" limit={12}/></div>
    <div className="mt-5"><Card><h2 className="mb-4 font-bold">History download</h2><div className="grid gap-3 md:grid-cols-3">{artifacts.data?.items.filter((item) => item.status === "downloaded").slice(0, 9).map((item) => <article key={item.id} className="rounded-xl border p-4"><div className="flex justify-between gap-2"><b className="truncate text-sm">{item.filename}</b><Badge tone="good">selesai</Badge></div><p className="muted mt-3 text-xs">{item.photo_count} foto · {item.video_count} video · {item.worker}</p></article>)}</div></Card></div>
  </>;
}
