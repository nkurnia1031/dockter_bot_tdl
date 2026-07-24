"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { LoaderCircle, X } from "lucide-react";
import { cn } from "@/lib/cn";

export function Button({className, busy, children, ...props}: React.ButtonHTMLAttributes<HTMLButtonElement> & {busy?: boolean}) {
  return <button className={cn("inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50", className)} disabled={busy || props.disabled} {...props}>
    {busy && <LoaderCircle className="size-4 animate-spin" aria-hidden />}{children}
  </button>;
}

export function Card({className, children}: {className?: string; children: React.ReactNode}) {
  return <section className={cn("panel p-5 shadow-[0_8px_30px_rgba(15,23,42,.04)]", className)}>{children}</section>;
}

export function Badge({children, tone = "neutral"}: {children: React.ReactNode; tone?: "neutral"|"good"|"warn"|"bad"|"brand"}) {
  const tones = {
    neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    good: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    warn: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    bad: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
    brand: "bg-[var(--brand-soft)] text-[var(--brand)]",
  };
  return <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-semibold", tones[tone])}>{children}</span>;
}

export function Field({label, hint, children}: {label: string; hint?: string; children: React.ReactNode}) {
  return <label className="grid gap-1.5 text-sm font-medium">{label}{children}{hint && <span className="muted text-xs font-normal">{hint}</span>}</label>;
}

export const inputClass = "min-h-11 w-full rounded-xl border bg-transparent px-3 text-sm outline-none transition focus:border-[var(--brand)]";

export function ConfirmDialog({title, description, trigger, onConfirm}: {title: string; description: string; trigger: React.ReactNode; onConfirm: () => void}) {
  return <Dialog.Root><Dialog.Trigger asChild>{trigger}</Dialog.Trigger><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm" />
    <Dialog.Content className="panel fixed left-1/2 top-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 p-6 shadow-2xl">
      <div className="flex items-start justify-between"><div><Dialog.Title className="text-lg font-bold">{title}</Dialog.Title><Dialog.Description className="muted mt-2 text-sm">{description}</Dialog.Description></div><Dialog.Close aria-label="Tutup"><X className="size-5"/></Dialog.Close></div>
      <div className="mt-6 flex justify-end gap-2"><Dialog.Close className="rounded-xl border px-4 py-2 text-sm">Batal</Dialog.Close><Dialog.Close asChild><Button onClick={onConfirm} className="bg-rose-600">Lanjutkan</Button></Dialog.Close></div>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}

export function Empty({title, description}: {title: string; description: string}) {
  return <div className="grid min-h-44 place-items-center rounded-xl border border-dashed p-6 text-center"><div><p className="font-semibold">{title}</p><p className="muted mt-1 text-sm">{description}</p></div></div>;
}
