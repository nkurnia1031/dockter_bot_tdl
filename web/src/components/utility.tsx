"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Folder, Play } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, Empty, Field, inputClass } from "./ui";
import { JobList, PageHeader } from "./page";

export function UtilityPage() {
  const client = useQueryClient();
  const folders = useQuery<{items: string[]}>({queryKey: ["utility-folders"], queryFn: () => api("/utility/folders")});
  const [utility, setUtility] = useState("pindah");
  const [selected, setSelected] = useState<string[]>([]);
  const submit = useMutation({mutationFn: () => api("/utility/jobs", {method: "POST", body: JSON.stringify({utility, folders: selected})}), onSuccess: () => client.invalidateQueries({queryKey: ["jobs"]})});
  return <><PageHeader eyebrow="Utility" title="Operasi workspace" description="Pilih folder workspace dan jalankan utility. Password tidak pernah masuk event atau log."/>
    <div className="grid gap-5 xl:grid-cols-[.65fr_1.35fr]"><Card><div className="grid gap-4"><Field label="Jenis operasi"><select className={inputClass} value={utility} onChange={(event) => setUtility(event.target.value)}><option value="pindah">Pindah / group</option><option value="compress">Compress 7z</option><option value="extract">Extract</option><option value="export">Organizer export</option></select></Field><div><p className="mb-2 text-sm font-medium">Folder target</p>{!folders.data?.items.length ? <Empty title="Folder belum diatur" description="Tambahkan folder melalui Pengaturan."/> : <div className="grid gap-2">{folders.data.items.map((folder) => <label key={folder} className="flex items-center gap-3 rounded-xl border p-3 text-sm"><input type="checkbox" checked={selected.includes(folder)} onChange={(event) => setSelected((old) => event.target.checked ? [...old, folder] : old.filter((item) => item !== folder))}/><Folder className="size-4 text-[var(--brand)]"/><span className="truncate">{folder}</span></label>)}</div>}</div><Button disabled={!selected.length} busy={submit.isPending} onClick={() => submit.mutate()}><Play className="size-4"/>Jalankan utility</Button>{submit.error && <p className="text-sm text-rose-600">{submit.error.message}</p>}</div></Card><JobList kind="utility" title="Progress & history utility" limit={20}/></div>
  </>;
}
