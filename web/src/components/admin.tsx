"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, Plus, Server, Shield, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { Badge, Button, Card, Empty, Field, inputClass } from "./ui";
import { PageHeader, tone } from "./page";

type Worker = {name: string; url: string; selected: boolean};

export function WorkersPage() {
  const client = useQueryClient();
  const workers = useQuery<{items: Worker[]}>({queryKey: ["workers"], queryFn: () => api("/workers")});
  const [form, setForm] = useState({name: "", url: "", token: ""});
  const add = useMutation({mutationFn: () => api("/workers", {method: "POST", body: JSON.stringify(form)}), onSuccess: () => {setForm({name: "", url: "", token: ""}); client.invalidateQueries({queryKey: ["workers"]});}});
  const route = useMutation({mutationFn: (name: string) => api("/me/worker-route", {method: "PUT", body: JSON.stringify({route: name})}), onSuccess: () => location.reload()});
  return <><PageHeader eyebrow="Infrastructure" title="Workers" description="Tambah worker secara dinamis tanpa rebuild backend. Perubahan route ditolak saat profile sibuk."/>
    <div className="grid gap-5 xl:grid-cols-[.65fr_1.35fr]"><Card><h2 className="mb-4 font-bold">Tambah worker</h2><div className="grid gap-4"><Field label="Nama"><input className={inputClass} value={form.name} onChange={(e) => setForm({...form, name: e.target.value})}/></Field><Field label="Endpoint"><input className={inputClass} placeholder="https://worker.example:5800" value={form.url} onChange={(e) => setForm({...form, url: e.target.value})}/></Field><Field label="API token" hint="Nilai tidak akan ditampilkan kembali."><input className={inputClass} type="password" value={form.token} onChange={(e) => setForm({...form, token: e.target.value})}/></Field><Button busy={add.isPending} disabled={!form.name || !form.url || !form.token} onClick={() => add.mutate()}><Plus className="size-4"/>Simpan worker</Button></div></Card>
      <Card><h2 className="mb-4 font-bold">Registry worker</h2>{!workers.data?.items.length ? <Empty title="Belum ada worker" description="Tambahkan worker lokal atau remote."/> : <div className="grid gap-3">{workers.data.items.map((worker) => <article className="flex flex-col justify-between gap-3 rounded-xl border p-4 sm:flex-row sm:items-center" key={worker.name}><div className="flex min-w-0 items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-[var(--brand-soft)] text-[var(--brand)]"><Server className="size-4"/></span><div className="min-w-0"><div className="flex items-center gap-2"><b>{worker.name}</b>{worker.selected && <Badge tone="good">aktif</Badge>}</div><p className="muted truncate text-xs">{worker.url}</p></div></div><Button disabled={worker.selected} onClick={() => route.mutate(worker.name)} className="bg-transparent text-[var(--brand)] border border-[var(--brand)] shadow-none">Pilih route</Button></article>)}</div>}</Card></div></>;
}

type Backup = {run_id: string; node_name: string; started_at: string; completed_at?: string; status: string; error?: string};

export function BackupsPage() {
  const client = useQueryClient();
  const status = useQuery<{enabled: boolean; schedule: string; timezone: string; retention: number; items: Backup[]}>({queryKey: ["backups"], queryFn: () => api("/backups/status"), refetchInterval: 5000});
  const run = useMutation({mutationFn: () => api("/backups", {method: "POST"}), onSuccess: () => client.invalidateQueries({queryKey: ["backups"]})});
  return <><PageHeader eyebrow="Disaster recovery" title="Backup terenkripsi" description="Snapshot per node dikirim ke channel backup dan dilindungi password Utility." action={<Button onClick={() => run.mutate()} busy={run.isPending}><DatabaseBackup className="size-4"/>Backup sekarang</Button>}/>
    <div className="mb-5 grid gap-4 sm:grid-cols-3"><Card><p className="muted text-sm">Scheduler</p><p className="mt-3 text-xl font-bold">{status.data?.schedule || "—"}</p><p className="muted mt-1 text-xs">{status.data?.timezone}</p></Card><Card><p className="muted text-sm">Retensi</p><p className="mt-3 text-xl font-bold">{status.data?.retention || "—"} backup/node</p></Card><Card><p className="muted text-sm">Status</p><p className="mt-3 text-xl font-bold">{status.data?.enabled ? "Aktif" : "Nonaktif"}</p></Card></div>
    <Card><h2 className="mb-4 font-bold">Backup terbaru per node</h2>{!status.data?.items.length ? <Empty title="Belum ada backup" description="Jalankan backup pertama untuk memverifikasi channel."/> : <div className="divide-y">{status.data.items.map((item) => <article key={`${item.run_id}-${item.node_name}`} className="grid gap-2 py-4 md:grid-cols-[1fr_auto]"><div><div className="flex items-center gap-2"><b>{item.node_name}</b><Badge tone={tone(item.status)}>{item.status}</Badge></div><p className="muted mt-1 text-xs">{item.run_id}</p>{item.error && <p className="mt-2 text-sm text-rose-600">{item.error}</p>}</div><time className="muted text-xs">{new Date(item.started_at).toLocaleString("id-ID")}</time></article>)}</div>}</Card></>;
}

export function SettingsPage() {
  const client = useQueryClient();
  type UtilitySetting = {key: string; label: string; description: string; format: string; examples: string[]; secret: boolean};
  const settings = useQuery<Record<string, string | boolean>>({queryKey: ["utility-settings"], queryFn: () => api("/utility/settings")});
  const metadata = useQuery<{items: UtilitySetting[]}>({queryKey: ["utility-settings-meta"], queryFn: () => api("/utility/settings/meta")});
  const storage = useQuery<{title: string; channel: string}>({queryKey: ["storage-settings"], queryFn: () => api("/storage/settings")});
  const [key, setKey] = useState("compress_size");
  const [value, setValue] = useState("");
  const save = useMutation({mutationFn: () => api(`/utility/settings/${key}`, {method: "PUT", body: JSON.stringify({value})}), onSuccess: () => {setValue(""); client.invalidateQueries({queryKey: ["utility-settings"]});}});
  const setting = metadata.data?.items.find((item) => item.key === key);
  const current = setting?.secret ? (settings.data?.compress_password_configured ? "Sudah diatur (dirahasiakan)" : "Belum diatur") : String(settings.data?.[key] || "—");
  return <><PageHeader eyebrow="Configuration" title="Pengaturan" description="Secret dapat diganti tetapi tidak pernah ditampilkan kembali oleh dashboard."/>
    <div className="grid gap-5 xl:grid-cols-2"><Card><h2 className="mb-1 font-bold">Default Utility</h2><p className="muted mb-4 text-sm">Batas ini diterapkan pada job berikutnya; job yang sedang berjalan tidak berubah.</p><div className="grid gap-4"><Field label="Pengaturan"><select className={inputClass} value={key} onChange={(event) => {setKey(event.target.value); setValue("");}}>{metadata.data?.items.map((item) => <option key={item.key} value={item.key}>{item.label}</option>) || <><option value="move_size">Batas ukuran grup pindah</option><option value="compress_size">Ukuran volume arsip 7z</option><option value="compress_password">Password arsip dan backup</option></>}</select></Field>
        <div className="rounded-xl border bg-[var(--surface-muted)] p-4 text-sm"><p className="font-semibold">{setting?.label || "Memuat panduan…"}</p><p className="muted mt-1">{setting?.description}</p><p className="mt-3"><span className="font-medium">Format diterima:</span> {setting?.format}</p>{setting?.examples.length ? <div className="mt-3 flex flex-wrap gap-2">{setting.examples.map((example) => <button key={example} type="button" className="rounded-md border bg-[var(--surface)] px-2 py-1 font-mono text-xs hover:border-[var(--brand)] hover:text-[var(--brand)]" onClick={() => setValue(example)}>Pakai {example}</button>)}</div> : null}</div>
        <Field label="Nilai baru" hint={`Nilai saat ini: ${current}`}><input className={inputClass} type={setting?.secret ? "password" : "text"} placeholder={setting?.examples[0] || "Minimal 8 karakter"} inputMode={setting?.secret ? "text" : "decimal"} minLength={setting?.secret ? 8 : undefined} maxLength={setting?.secret ? 128 : undefined} value={value} onChange={(event) => setValue(event.target.value)} aria-describedby="utility-setting-hint"/></Field>
        <Button disabled={!value.trim()} busy={save.isPending} onClick={() => save.mutate()}>Simpan default</Button>{save.error && <p className="text-sm text-rose-600">{save.error.message}</p>}</div></Card>
      <Card><div className="mb-4 flex items-center gap-3"><Shield className="text-[var(--brand)]"/><h2 className="font-bold">Channel & keamanan</h2></div><dl className="grid gap-4 text-sm"><div className="rounded-xl border p-4"><dt className="muted">Storage channel</dt><dd className="mt-1 font-semibold">{storage.data?.title || "Belum terhubung"}</dd></div><div className="rounded-xl border p-4"><dt className="muted">Session token</dt><dd className="mt-1 font-semibold">HttpOnly · SameSite Lax · Path /ui</dd></div><div className="rounded-xl border p-4"><dt className="muted">Password backup</dt><dd className="mt-1 font-semibold">Mengikuti default compress Utility</dd></div></dl></Card></div></>;
}
