"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Folder, Play, RefreshCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Empty, Field, inputClass } from "./ui";
import { JobList, PageHeader } from "./page";

type TreeItem = {name: string; path: string; kind: "directory" | "file"; files?: number; directories?: number; has_children?: boolean; size?: number | null};
type Tree = {path: string; items: TreeItem[]};

export function UtilityPage() {
  const client = useQueryClient();
  const [utility, setUtility] = useState("pindah");
  const [currentPath, setCurrentPath] = useState("/workspace");
  const [selected, setSelected] = useState<string[]>([]);
  const tree = useQuery<Tree>({
    queryKey: ["utility-tree", currentPath],
    queryFn: () => api(`/utility/tree?path=${encodeURIComponent(currentPath)}`),
  });
  const folders = useMemo(() => tree.data?.items.filter((item) => item.kind === "directory") || [], [tree.data]);
  const parentPath = currentPath === "/workspace" ? null : currentPath.split("/").slice(0, -1).join("/") || "/workspace";
  const submit = useMutation({
    mutationFn: () => api("/utility/jobs", {method: "POST", body: JSON.stringify({utility, folders: selected})}),
    onSuccess: () => {setSelected([]); client.invalidateQueries({queryKey: ["jobs"]});},
  });

  function toggleFolder(path: string) {
    setSelected((old) => old.includes(path) ? old.filter((item) => item !== path) : [...old, path]);
  }

  return <><PageHeader eyebrow="Utility" title="Operasi workspace" description="Workspace dipindai oleh worker yang sedang dipilih. Buka folder untuk menjelajah, lalu pilih beberapa folder sekaligus."/>
    <div className="grid gap-5 xl:grid-cols-[.8fr_1.2fr]"><Card>
      <div className="grid gap-5">
        <Field label="Jenis operasi"><select className={`${inputClass} dark:[color-scheme:dark]`} value={utility} onChange={(event) => setUtility(event.target.value)}><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option></select></Field>
        <div>
          <div className="mb-3 flex items-center justify-between gap-3"><div><p className="text-sm font-semibold">Workspace worker</p><p className="muted text-xs">{tree.data?.path || currentPath}</p></div><button className="rounded-lg border p-2" onClick={() => tree.refetch()} aria-label="Refresh folder"><RefreshCw className="size-4"/></button></div>
          <div className="mb-3 flex items-center gap-2"><button className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium disabled:opacity-40" disabled={!parentPath} onClick={() => parentPath && setCurrentPath(parentPath)}><ChevronLeft className="size-3.5"/>Naik</button><Badge>{selected.length} dipilih</Badge></div>
          {tree.isLoading ? <div className="grid min-h-40 place-items-center muted text-sm">Memindai workspace worker…</div> : tree.isError ? <Empty title="Workspace tidak dapat dibaca" description="Pastikan worker aktif dan route profile benar."/> : !folders.length ? <Empty title="Tidak ada folder" description="Folder workspace ini belum memiliki subfolder."/> : <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1">{folders.map((folder) => <div key={folder.path} className={`flex items-center gap-2 rounded-xl border p-3 transition ${selected.includes(folder.path) ? "border-[var(--brand)] bg-[var(--brand-soft)]" : ""}`}><input type="checkbox" checked={selected.includes(folder.path)} onChange={() => toggleFolder(folder.path)} aria-label={`Pilih ${folder.name}`}/><Folder className="size-4 shrink-0 text-[var(--brand)]"/><button type="button" className="min-w-0 flex-1 text-left" onClick={() => setCurrentPath(folder.path)}><span className="block truncate text-sm font-medium">{folder.name}</span><span className="muted text-xs">{folder.directories || 0} folder · {folder.files || 0} file</span></button><ChevronRight className="size-4 muted"/></div>)}</div>}
        </div>
        {selected.length > 0 && <div><p className="mb-2 text-sm font-semibold">Folder terpilih</p><div className="flex flex-wrap gap-2">{selected.map((path) => <button key={path} type="button" className="inline-flex max-w-full items-center gap-1 rounded-full bg-[var(--brand-soft)] px-2.5 py-1 text-xs text-[var(--brand)]" onClick={() => toggleFolder(path)}><span className="truncate">{path.replace("/workspace/", "")}</span><X className="size-3"/></button>)}</div></div>}
        <Button disabled={!selected.length} busy={submit.isPending} onClick={() => submit.mutate()}><Play className="size-4"/>Jalankan Utility</Button>{submit.error && <p className="text-sm text-rose-600">{submit.error.message}</p>}
      </div>
    </Card><JobList kind="utility" title="Progress & history utility" limit={20}/></div>
  </>;
}
