"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FolderUp, Pencil, Search, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, formatBytes } from "@/lib/api";
import { Badge, Button, Card, ConfirmDialog, Empty, Field, inputClass } from "./ui";
import { JobList, PageHeader } from "./page";

type Item = {id: number; display_name: string; original_name: string; folder: string; keywords: string; file_size?: number; mime_type: string; owner_profile: string; owner_user_id: number; uploaded_at: string; status: string};

export function StoragePage() {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [logical, setLogical] = useState("");
  const [keywords, setKeywords] = useState("");
  const catalog = useQuery<{items: Item[]; total: number}>({queryKey: ["storage", q], queryFn: () => api(`/storage/items?q=${encodeURIComponent(q)}&limit=50`)});
  const upload = useMutation({mutationFn: () => api("/storage/uploads", {method: "POST", body: JSON.stringify({folder_path: folderPath, folder: logical, keywords})}), onSuccess: () => {setFolderPath(""); setLogical(""); setKeywords(""); client.invalidateQueries({queryKey: ["jobs"]});}});
  const rename = useMutation({mutationFn: ({id, name}: {id: number; name: string}) => api(`/storage/items/${id}`, {method: "PATCH", body: JSON.stringify({display_name: name})}), onSuccess: () => client.invalidateQueries({queryKey: ["storage"]})});
  const deliver = useMutation({mutationFn: (id: number) => api(`/storage/items/${id}/deliveries`, {method: "POST", body: JSON.stringify({method: "telegram"})})});
  const deepLink = useMutation({
    mutationFn: (id: number) => api<{url: string}>(`/storage/items/${id}/deep-link`),
    onSuccess: ({url}) => window.open(url, "_blank", "noopener,noreferrer"),
  });
  const remove = useMutation({mutationFn: (id: number) => api(`/storage/items/${id}`, {method: "DELETE"}), onSuccess: () => client.invalidateQueries({queryKey: ["storage"]})});
  return <><PageHeader eyebrow="Storage channel" title="Upload & katalog file" description="Pencarian menggabungkan FTS prefix dan trigram untuk typo/substring. Upload membaca folder dari /workspace."/>
    <div className="grid gap-5 xl:grid-cols-[.65fr_1.35fr]"><Card><div className="mb-5 flex items-center gap-3"><FolderUp className="text-[var(--brand)]"/><div><h2 className="font-bold">Upload folder workspace</h2><p className="muted text-xs">Semua file dipindai rekursif.</p></div></div><div className="grid gap-4"><Field label="Path workspace" hint="Wajib berada di dalam /workspace"><input className={inputClass} value={folderPath} placeholder="/workspace/downloads/batch-01" onChange={(event) => setFolderPath(event.target.value)}/></Field><Field label="Folder logis"><input className={inputClass} value={logical} placeholder="2026-arsip" onChange={(event) => setLogical(event.target.value)}/></Field><Field label="Keyword opsional"><input className={inputClass} value={keywords} placeholder="javascript, laporan" onChange={(event) => setKeywords(event.target.value)}/></Field><Button disabled={!folderPath || !logical} busy={upload.isPending} onClick={() => upload.mutate()}>Mulai upload</Button></div></Card><JobList kind="storage_upload" title="Progress upload" limit={10}/></div>
    <Card className="mt-5"><div className="mb-4 flex flex-col justify-between gap-3 md:flex-row md:items-center"><div><h2 className="font-bold">Katalog global</h2><p className="muted text-xs">{catalog.data?.total || 0} file aktif</p></div><label className="relative"><Search className="muted absolute left-3 top-3 size-4"/><input className={`${inputClass} pl-9 md:w-80`} value={q} onChange={(event) => setQ(event.target.value)} placeholder="Cari nama, folder, keyword…"/></label></div>
      {!catalog.data?.items.length ? <Empty title="File tidak ditemukan" description="Coba keyword lain atau upload folder pertama."/> : <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">{catalog.data.items.map((item) => <article key={item.id} className="rounded-2xl border p-4"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><b className="block truncate">{item.display_name}</b><p className="muted truncate text-xs">{item.original_name}</p></div><Badge>{item.mime_type?.split("/")[0] || "file"}</Badge></div><dl className="muted mt-4 grid grid-cols-2 gap-2 text-xs"><div><dt>Folder</dt><dd className="mt-1 truncate font-semibold text-[var(--ink)]">{item.folder}</dd></div><div><dt>Ukuran</dt><dd className="mt-1 font-semibold text-[var(--ink)]">{formatBytes(item.file_size)}</dd></div><div className="col-span-2"><dt>Keyword</dt><dd className="mt-1 truncate font-semibold text-[var(--ink)]">{item.keywords || "—"}</dd></div></dl><div className="mt-4 flex gap-2 border-t pt-3"><button title="Rename metadata" onClick={() => {const name = prompt("Nama tampilan baru", item.display_name); if (name) rename.mutate({id: item.id, name});}} className="grid size-9 place-items-center rounded-lg border"><Pencil className="size-4"/></button><button title="Kirim ke Telegram" onClick={() => deliver.mutate(item.id)} className="grid size-9 place-items-center rounded-lg border text-[var(--brand)]"><Send className="size-4"/></button><button title="Buka deep link bot" onClick={() => deepLink.mutate(item.id)} className="grid size-9 place-items-center rounded-lg border"><ExternalLink className="size-4"/></button><ConfirmDialog title="Hapus file?" description="Message channel dan metadata aktif akan dihapus." onConfirm={() => remove.mutate(item.id)} trigger={<button title="Hapus" className="grid size-9 place-items-center rounded-lg border text-rose-600"><Trash2 className="size-4"/></button>}/></div></article>)}</div>}
    </Card></>;
}
