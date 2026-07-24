"use client";

import { useState } from "react";
import { Bot, ExternalLink, LoaderCircle, ShieldCheck } from "lucide-react";
import { Button, Card } from "./ui";

export function Login() {
  const [challenge, setChallenge] = useState<{verification_uri: string} | null>(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");

  async function begin() {
    setStatus("loading");
    const response = await fetch("/ui/api/auth/challenge", {method: "POST"});
    const data = await response.json();
    if (!response.ok) { setError(data?.error?.message || "Gagal membuat login."); setStatus("idle"); return; }
    setChallenge(data); setStatus("waiting");
    window.open(data.verification_uri, "_blank", "noopener,noreferrer");
    poll();
  }

  async function poll() {
    for (let attempt = 0; attempt < 100; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      const response = await fetch("/ui/api/auth/poll", {method: "POST"});
      if (response.ok) { location.reload(); return; }
      if (response.status !== 202) {
        const data = await response.json().catch(() => ({}));
        setError(data?.error?.message || "Sesi login berakhir.");
        setStatus("idle"); return;
      }
    }
    setError("Waktu login habis. Silakan ulangi."); setStatus("idle");
  }

  return <main className="grid min-h-screen place-items-center p-5">
    <Card className="w-full max-w-md p-7">
      <div className="mb-7 flex size-12 items-center justify-center rounded-2xl bg-[var(--brand-soft)] text-[var(--brand)]"><Bot /></div>
      <p className="muted text-sm font-semibold uppercase tracking-[.18em]">tme3 control center</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight">Kelola semua profile dalam satu dashboard.</h1>
      <p className="muted mt-3 text-sm leading-6">Login disetujui lewat bot Telegram. Token tetap berada di cookie HttpOnly dan tidak pernah diberikan ke JavaScript.</p>
      <Button onClick={begin} busy={status === "loading"} className="mt-7 w-full">
        {status === "waiting" ? <LoaderCircle className="size-4 animate-spin"/> : <ShieldCheck className="size-4"/>}
        {status === "waiting" ? "Menunggu persetujuan Telegram…" : "Login dengan Telegram"}
      </Button>
      {challenge && <a className="mt-3 flex justify-center gap-2 text-sm font-semibold text-[var(--brand)]" href={challenge.verification_uri} target="_blank" rel="noreferrer">Buka bot lagi <ExternalLink className="size-4"/></a>}
      {error && <p className="mt-4 rounded-xl bg-rose-50 p-3 text-sm text-rose-700" role="alert">{error}</p>}
    </Card>
  </main>;
}
