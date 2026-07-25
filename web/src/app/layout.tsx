import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {title: "tme3 Control Center", description: "Admin dashboard tme3bot"};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="id" suppressHydrationWarning><body><Providers><AppShell>{children}</AppShell></Providers></body></html>;
}
