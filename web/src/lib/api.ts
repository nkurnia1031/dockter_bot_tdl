export type ApiError = {error?: {code?: string; message?: string}};

function csrf() {
  return document.cookie.split("; ").find((item) => item.startsWith("tme3_csrf="))?.split("=")[1] || "";
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (init.method && !["GET", "HEAD"].includes(init.method)) headers.set("X-CSRF-Token", decodeURIComponent(csrf()));
  const response = await fetch(`/ui/api/backend${path}`, {...init, headers, cache: "no-store"});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((payload as ApiError).error?.message || `HTTP ${response.status}`);
  return payload as T;
}

export const formatBytes = (value?: number | null) => {
  if (value === null || value === undefined) return "Tidak diketahui";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let result = value / 1024;
  let unit = units[0];
  for (let i = 1; result >= 1024 && i < units.length; i++) {
    result /= 1024;
    unit = units[i];
  }
  return `${result.toFixed(result >= 10 ? 1 : 2)} ${unit}`;
};
