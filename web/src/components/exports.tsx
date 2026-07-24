"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api } from "@/lib/api";
import { Badge, Button, Card, Empty, Field, inputClass } from "./ui";
import { JobList, PageHeader } from "./page";

const schema = z.object({chat_ref: z.string().min(1, "Username atau ID wajib diisi"), start_id: z.number().int().positive(), label: z.string().optional()});
type Form = z.infer<typeof schema>;
type Source = {chat_ref: string; label?: string; last_id: number; updated_at: string};

export function ExportsPage() {
  const client = useQueryClient();
  const sources = useQuery<{items: Source[]}>({queryKey: ["sources"], queryFn: () => api("/sources")});
  const form = useForm<Form>({resolver: zodResolver(schema), defaultValues: {chat_ref: "", start_id: 1, label: ""}});
  const submit = useMutation({mutationFn: (value: Form) => api("/exports", {method: "POST", body: JSON.stringify(value)}), onSuccess: () => {form.reset(); client.invalidateQueries({queryKey: ["jobs"]});}});
  const remove = useMutation({mutationFn: (chatRef: string) => api(`/sources/${encodeURIComponent(chatRef)}`, {method: "DELETE"}), onSuccess: () => client.invalidateQueries({queryKey: ["sources"]})});
  return <><PageHeader eyebrow="Export" title="Source & pembuatan export" description="Masukkan username tanpa tautan lengkap, atau gunakan numeric chat ID. Source baru tersimpan setelah export berhasil."/>
    <div className="grid gap-5 xl:grid-cols-[.75fr_1.25fr]"><Card><div className="mb-5 flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-[var(--brand-soft)] text-[var(--brand)]"><FilePlus2 className="size-5"/></span><div><h2 className="font-bold">Export baru</h2><p className="muted text-xs">Start ID dapat dioverride per request.</p></div></div>
      <form className="grid gap-4" onSubmit={form.handleSubmit((value) => submit.mutate(value))}>
        <Field label="Username atau chat ID"><input className={inputClass} placeholder="nama_channel atau -100…" {...form.register("chat_ref")}/>{form.formState.errors.chat_ref && <span className="text-xs text-rose-600">{form.formState.errors.chat_ref.message}</span>}</Field>
        <Field label="Start message ID"><input className={inputClass} type="number" min="1" {...form.register("start_id", {valueAsNumber: true})}/></Field>
        <Field label="Label opsional"><input className={inputClass} placeholder="arsip-2026" {...form.register("label")}/></Field>
        <Button busy={submit.isPending}>Mulai export</Button>{submit.error && <p className="text-sm text-rose-600">{submit.error.message}</p>}
      </form></Card>
      <Card><div className="mb-4 flex items-center justify-between"><h2 className="font-bold">Source tersimpan</h2><Badge>{sources.data?.items.length || 0} source</Badge></div>
        {!sources.isLoading && !sources.data?.items.length ? <Empty title="Belum ada source" description="Source akan muncul setelah export pertama berhasil."/> : <div className="scrollbar overflow-x-auto"><table className="w-full min-w-[36rem] text-left text-sm"><thead className="muted border-b text-xs uppercase"><tr><th className="py-3">Source</th><th>Label</th><th>Last ID</th><th>Update</th><th/></tr></thead><tbody>{sources.data?.items.map((item) => <tr key={item.chat_ref} className="border-b last:border-0"><td className="py-3 font-semibold">{item.chat_ref}</td><td>{item.label || "—"}</td><td>{item.last_id}</td><td className="muted text-xs">{new Date(item.updated_at).toLocaleString("id-ID")}</td><td><button className="text-rose-600" aria-label={`Hapus ${item.chat_ref}`} onClick={() => remove.mutate(item.chat_ref)}><Trash2 className="size-4"/></button></td></tr>)}</tbody></table></div>}
      </Card></div><div className="mt-5"><JobList kind="export" title="Riwayat export"/></div>
  </>;
}
