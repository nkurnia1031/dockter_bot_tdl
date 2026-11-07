# Bookmarklet Resolver Safelink

Bookmarklet ini dijalankan langsung pada tab Safelink di desktop Chrome atau Edge. Setiap klik memproses paling banyak satu langkah Livewire. Bila halaman berpindah ke langkah gate berikutnya, klik bookmarklet lagi. URL tujuan akhir ditampilkan untuk disalin; halaman tujuan tidak dibuka otomatis.

## Memasang

1. Buat bookmark browser baru bernama `Resolver Safelink`.
2. Salin seluruh isi blok bookmarklet di bawah ke kolom URL/alamat bookmark, termasuk awalan `javascript:`.
3. Buka URL Safelink. Setelah halaman gate tampil, klik bookmarklet. Ulangi setelah setiap perpindahan halaman.

Bookmarklet menggunakan sesi browser halaman aktif dan hanya mengirim satu request Livewire ke origin halaman itu. Bookmarklet tidak memanggil API TME3Bot, tidak membuat job worker, tidak mengirim URL/sesi ke backend aplikasi, dan tidak mengambil isi URL tujuan. Selesaikan CAPTCHA secara manual sebelum menjalankannya kembali.

## Bookmarklet siap salin

```bookmarklet
javascript:(async () => {
  const panelId = "tme3-safelink-bookmarklet";
  const gateDomains = ["pndk.to", "go.fakta.id", "datapendidikan.com", "urlwebsite.com", "adtival.network"];
  const isDomain = (host, domain) => host === domain || host.endsWith(`.${domain}`);
  const isGate = (host) => gateDomains.some((domain) => isDomain(host, domain));
  const isSafelinkEarn = (host) => isDomain(host, "safelinkearn.com");

  function show(title, message, url = "") {
    document.getElementById(panelId)?.remove();
    const panel = document.createElement("div");
    panel.id = panelId;
    panel.style.cssText = "position:fixed;z-index:2147483647;inset:auto 16px 16px auto;max-width:min(620px,calc(100vw - 32px));padding:16px;background:#fff;color:#111827;border:1px solid #94a3b8;border-radius:12px;box-shadow:0 12px 40px #0005;font:14px/1.5 system-ui,sans-serif";

    const heading = document.createElement("strong");
    heading.textContent = title;
    panel.appendChild(heading);

    const detail = document.createElement("p");
    detail.textContent = message;
    detail.style.cssText = "margin:8px 0";
    panel.appendChild(detail);

    if (url) {
      const field = document.createElement("input");
      field.type = "text";
      field.readOnly = true;
      field.value = url;
      field.setAttribute("aria-label", "URL tujuan");
      field.style.cssText = "box-sizing:border-box;width:100%;padding:8px;border:1px solid #94a3b8;border-radius:6px";
      panel.appendChild(field);

      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "Salin URL";
      copy.style.cssText = "margin-top:8px;padding:7px 12px;cursor:pointer";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(url);
          copy.textContent = "Tersalin";
        } catch {
          field.focus();
          field.select();
          try {
            document.execCommand("copy");
            copy.textContent = "Tersalin";
          } catch {
            copy.textContent = "Pilih URL lalu salin manual";
          }
        }
      });
      panel.appendChild(copy);
    }

    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Tutup";
    close.style.cssText = "margin:8px 0 0 8px;padding:7px 12px;cursor:pointer";
    close.addEventListener("click", () => panel.remove());
    panel.appendChild(close);
    document.body.appendChild(panel);
  }

  function safeWebUrl(raw) {
    if (typeof raw !== "string" || !raw || raw.length > 4096) throw Error("URL halaman tidak valid.");
    const url = new URL(raw);
    if (!["http:", "https:"].includes(url.protocol) || !url.hostname || url.username || url.password) {
      throw Error("Hanya URL HTTP/HTTPS tanpa kredensial yang didukung.");
    }
    return url;
  }

  function decodeSafelinkEarn(url) {
    for (const key of ["shortid", "url", "u", "link", "target"]) {
      const value = url.searchParams.get(key);
      if (!value) continue;
      try {
        const encoded = value.replace(/ /g, "+").replace(/-/g, "+").replace(/_/g, "/").replace(/=+$/, "");
        const padded = encoded + "=".repeat((4 - (encoded.length % 4)) % 4);
        const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
        const destination = new TextDecoder().decode(bytes).trim();
        return safeWebUrl(destination).href;
      } catch {
        // Try the next known SafelinkEarn parameter.
      }
    }
    return "";
  }

  try {
    const current = safeWebUrl(window.location.href);
    if (isSafelinkEarn(current.hostname)) {
      const destination = decodeSafelinkEarn(current);
      if (!destination) throw Error("Parameter tujuan pada halaman SafelinkEarn tidak dapat dibaca.");
      show("URL tujuan ditemukan", "Salin URL ini untuk melanjutkan.", destination);
      return;
    }
    if (!isGate(current.hostname)) throw Error("Halaman ini bukan domain Safelink yang didukung.");

    const visible = document.body.innerText || document.body.textContent || "";
    const visibleCaptcha = /(captcha|recaptcha|hcaptcha|turnstile|verify\s+you\s+are\s+human|verifikasi\s+(?:bahwa\s+)?anda manusia|i\s+am\s+not\s+a\s+robot)/i.test(visible);
    if (visibleCaptcha) throw Error("Selesaikan CAPTCHA secara manual, lalu jalankan bookmarklet kembali.");

    const node = document.querySelector("[wire\\:initial-data]");
    if (!node) throw Error("State langkah gate tidak ditemukan. Pastikan redirect awal selesai lalu jalankan bookmarklet lagi.");
    const initial = JSON.parse(node.getAttribute("wire:initial-data") || "{}");
    const fingerprint = initial.fingerprint;
    const serverMemo = initial.serverMemo;
    const data = serverMemo?.data || {};
    if (!fingerprint || typeof fingerprint.name !== "string" || typeof fingerprint.id !== "string" || !fingerprint.id || !serverMemo) {
      throw Error("State langkah gate tidak lengkap.");
    }

    if (data.hasCaptcha === true && data.captcha !== true) {
      throw Error("Selesaikan CAPTCHA secara manual, lalu jalankan bookmarklet kembali.");
    }

    const step = visible.match(/\bStep\s*(\d+)\s*\/\s*\d+/i);
    if (!step) throw Error("Nomor langkah gate tidak ditemukan.");
    const tokenMatch = document.documentElement.innerHTML.match(/window\.livewire_token\s*=\s*[\"']([^\"']+)[\"']/);
    if (!tokenMatch) throw Error("Token sesi halaman tidak ditemukan.");
    if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(fingerprint.name) || fingerprint.id.length > 128) {
      throw Error("Komponen halaman tidak didukung.");
    }

    const endpoint = new URL(`/livewire/message/${encodeURIComponent(fingerprint.name)}`, current.href);
    if (endpoint.origin !== current.origin) throw Error("Request keluar dari origin halaman ditolak.");
    const event = Number(step[1]) >= 5 && String(data.phase) === "5" ? "getData" : "changePhase";
    const response = await fetch(endpoint.href, {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      headers: {
        "X-Livewire": "true",
        "X-CSRF-TOKEN": tokenMatch[1],
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        fingerprint,
        serverMemo,
        updates: [{ type: "fireEvent", payload: { id: fingerprint.id, event, params: [] } }]
      })
    });
    if (!response.ok) throw Error(`Tahap gate gagal (HTTP ${response.status}).`);

    const result = await response.json();
    const emits = result?.effects?.emits;
    if (!Array.isArray(emits)) throw Error("Respons gate tidak membawa langkah berikutnya.");
    const emission = emits.find((item) => item?.event === "setLink" && Array.isArray(item.params) && typeof item.params[0] === "string");
    if (!emission) throw Error("Respons gate tidak membawa link tujuan.");

    const next = safeWebUrl(emission.params[0]);
    if (isSafelinkEarn(next.hostname)) {
      const destination = decodeSafelinkEarn(next);
      if (destination) {
        show("URL tujuan ditemukan", "Salin URL ini untuk melanjutkan.", destination);
        return;
      }
      window.location.assign(next.href);
      return;
    }
    if (isGate(next.hostname)) {
      window.location.assign(next.href);
      return;
    }
    show("URL tujuan ditemukan", "Salin URL ini untuk melanjutkan.", next.href);
  } catch (error) {
    show("Resolver Safelink", error instanceof Error ? error.message : "Bookmarklet gagal memproses halaman.");
  }
})();
```
