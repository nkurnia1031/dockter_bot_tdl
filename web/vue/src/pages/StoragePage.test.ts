import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoragePage from "./StoragePage.vue";

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), patch: vi.fn() }));
vi.mock("../lib/api", () => ({ ...mocks, put: vi.fn(), remove: vi.fn() }));
vi.mock("../session", () => ({
  session: {
    current: { profiles: ["default"], actor: { profile: "default", worker_route: "local", telegram_user_id: 1 } },
    refreshProfileCatalog: vi.fn(),
  },
}));

const browser = (folderId: string | null, scope: string | null) => scope === "trash"
  ? { current_folder: null, breadcrumbs: [], folders: [], items: [{ id: 30, display_name: "trashed.zip", original_name: "trashed.zip", file_size: 10, status: "trash" }], total_folders: 0, total_items: 1 }
  : folderId === "1"
  ? { current_folder: { id: 1, name: "Projects" }, breadcrumbs: [{ id: 1, name: "Projects" }], folders: [], items: [{ id: 9, display_name: "report.pdf", original_name: "report.pdf", file_size: 10, status: "active" }], total_folders: 0, total_items: 1 }
  : { current_folder: null, breadcrumbs: [], folders: [{ id: 1, parent_id: null, name: "Projects", path: "Projects", file_count: 2, folder_count: 1, size_bytes: 30, size_complete: true }], items: [], total_folders: 1, total_items: 0 };

function setupApi() {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/workers") return { items: [{ name: "local", url: "http://worker", enabled: true, public_url: "https://files.example.test" }, { name: "remote-1", url: "http://remote", enabled: true }] };
    if (path === "/profiles/local") return { runtime_readiness: { checked_at: "2026-11-11T10:00:00Z", workers: [{ name: "local", status: "success" }], cells: [{ worker: "local", profile: "default", runtime: "storage", status: "ready", checked_at: "2026-11-11T10:00:00Z" }] } };
    if (path.startsWith("/jobs/metrics") || path.startsWith("/jobs?")) return { items: [] };
    if (path.startsWith("/jobs/")) return { id: path.split("/").at(-1), status: "running" };
    if (path.startsWith("/storage/download-links")) return { items: [] };
    if (path.startsWith("/storage/browser?")) {
      const params = new URLSearchParams(path.split("?")[1]);
      return browser(params.get("folder_id"), params.get("scope"));
    }
    if (path === "/storage/folders/tree") return { items: [{ id: 1, parent_id: null, name: "Projects", path: "Projects" }] };
    if (path.startsWith("/utility/tree?")) {
      const worker = new URLSearchParams(path.split("?")[1]).get("worker");
      return { path: "/workspace", items: [{ name: "downloads", path: "/workspace/downloads", kind: "directory", files: 3, directories: 1 }, { name: `worker-${worker}`, path: `/workspace/worker-${worker}`, kind: "directory", files: 1, directories: 0 }] };
    }
    if (path.startsWith("/storage/rclone/browser?")) {
      const params = new URLSearchParams(path.split("?")[1]);
      const current = params.get("path") || "";
      return { path: current, breadcrumbs: current ? [current] : [], items: current ? [{ name: "nested.txt", path: `${current}/nested.txt`, is_dir: false, size: 20, updated_at: "now" }] : [{ name: "Archive", path: "Archive", is_dir: true, size: 0, updated_at: "now" }, { name: "report.zip", path: "report.zip", is_dir: false, size: 42, updated_at: "now" }], total: current ? 1 : 2, limit: 100, offset: 0, trash_supported: true, permanent_delete_supported: true };
    }
    if (path.startsWith("/storage/rclone/folder-summaries?")) return { summaries: [{ path: "Archive", file_count: 4, folder_count: 2, size_bytes: 3145728, size_complete: false }] };
    if (path.startsWith("/storage/rclone/trash?")) return { supported: true, permanent_delete_supported: true, items: [{ id: "trash-1", name: "old.zip", path: "Archive/old.zip", is_dir: false, size: 12, updated_at: "now" }], total: 1, limit: 100, offset: 0 };
    if (path === "/storage/settings") return {};
    throw new Error(`Unexpected GET ${path}`);
  });
  mocks.post.mockResolvedValue({ id: "job-12345678", cleanup_status: "deleted" });
  mocks.patch.mockResolvedValue({});
}

const projectFolderSummary = "2 file · 1 folder · 30 B";
const findSummary = (expected: string) => screen.findByText((_, element) => element?.textContent?.replace(/\s+/g, " ").trim() === expected);
const findProjectFolderButton = async () => {
  const summary = await findSummary(projectFolderSummary);
  const button = summary.closest("button.entry-main");
  if (!button) throw new Error("Folder Projects tidak memiliki tombol buka.");
  return button;
};
const openRcloneFolderButton = async (name: string) => {
  const checkbox = await screen.findByRole("checkbox", { name: `Pilih folder ${name}` });
  const row = checkbox.closest(".storage-entry");
  const button = row?.querySelector("button.entry-main");
  if (!button) throw new Error(`Folder rclone ${name} tidak memiliki tombol buka.`);
  return button;
};

describe("StoragePage", () => {
  beforeEach(() => { window.history.replaceState({}, "", "/"); vi.clearAllMocks(); setupApi(); });
  afterEach(() => { cleanup(); window.history.replaceState({}, "", "/"); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

  it("keeps Telegram navigation and recursive folder summaries", async () => {
    render(StoragePage);
    expect(await findSummary("2 file · 1 folder · 30 B")).toBeTruthy();
    expect(await screen.findByText("Storage siap")).toBeTruthy();
    expect(mocks.api).toHaveBeenCalledWith("/profiles/local");
    expect(screen.getByRole("button", { name: "Recycle Bin" })).toBeTruthy();
    expect(screen.queryByText("Folder bersama")).toBeNull();
    await fireEvent.click(await findProjectFolderButton());
    expect((await screen.findAllByText("report.pdf")).length).toBeGreaterThan(0);
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("folder_id=1"))).toBe(true);
  });

  it("purges the currently listed Telegram Trash after explicit bulk selection", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("button", { name: "Recycle Bin" }));
    expect((await screen.findAllByText("trashed.zip")).length).toBeGreaterThan(0);
    await fireEvent.click(screen.getByRole("button", { name: "Kosongkan Trash" }));
    expect(await screen.findByRole("heading", { name: "Hapus permanen?" })).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Purge permanen" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/actions/purge", { item_ids: [30], folder_ids: [] }));
  });

  it("submits Telegram upload with the selected worker, workspace path, and safe Move confirmation", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await findSummary("1 folder · 3 file");
    await fireEvent.click(screen.getByRole("button", { name: "Pilih folder" }));
    await fireEvent.change(screen.getByLabelText("Transfer"), { target: { value: "move" } });
    const confirmation = screen.getByRole("checkbox", { name: /file Workspace dihapus per file/ });
    await fireEvent.click(confirmation);
    await fireEvent.click(screen.getByRole("button", { name: "Mulai upload" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/uploads", {
      folder_path: "/workspace",
      destination_folder_id: null,
      provider: "telegram",
      rclone_path: "",
      transfer_mode: "move",
      preserve_structure: true,
      keywords: "",
      worker: "local",
      move_confirmed: true,
    }));
  });

  it("still submits Telegram upload when the saved Storage readiness snapshot is not ready", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    mocks.api.mockImplementation(async (path: string) => path === "/profiles/local"
      ? { runtime_readiness: { cells: [{ worker: "local", profile: "default", runtime: "storage", status: "not_ready", reason_code: "TDL_ACCESS_NOT_VERIFIED" }] } }
      : baseImplementation!(path));
    render(StoragePage);
    expect(await screen.findByText("Storage belum siap")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await findSummary("1 folder · 3 file");
    await fireEvent.click(screen.getByRole("button", { name: "Pilih folder" }));
    await fireEvent.click(screen.getByRole("button", { name: "Mulai upload" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/uploads", expect.objectContaining({ worker: "local", provider: "telegram", transfer_mode: "copy" })));
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("/tdl-access/verification"))).toBe(false);
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("/context/verify"))).toBe(false);
  });

  it("submits a Telegram download even when its saved Download cell is not ready", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    mocks.api.mockImplementation(async (path: string) => path === "/profiles/local"
      ? { runtime_readiness: { cells: [{ worker: "local", profile: "default", runtime: "download", status: "not_ready", reason_code: "PROFILE_CANARY_DOWNLOAD_FAILED" }] } }
      : baseImplementation!(path));
    render(StoragePage);
    await fireEvent.click(await findProjectFolderButton());
    await screen.findAllByText("report.pdf");
    await fireEvent.click(screen.getByRole("checkbox", { name: "Pilih file report.pdf" }));
    await fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByLabelText("Profil dengan lane Download siap")).toBeTruthy();
    await fireEvent.click(await screen.findByRole("radio", { name: "Pilih downloads" }));
    await fireEvent.click(screen.getByRole("button", { name: "Mulai download" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/downloads", {
      provider: "telegram", worker: "local", profile: "default", item_ids: [9], folder_ids: [], destination_path: "/workspace/downloads", publish_public_links: false,
    }));
  });

  it("creates and renames rclone folders and entries with the selected worker", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Folder baru" }));
    await fireEvent.input(screen.getByLabelText("Nama folder"), { target: { value: "2026" } });
    await fireEvent.click(screen.getByRole("button", { name: "Buat folder" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/rclone/actions", { worker: "local", action: "create_folder", path: "", name: "2026" }));
    await fireEvent.click(await screen.findByRole("button", { name: "Rename Archive" }));
    await fireEvent.input(screen.getByLabelText("Nama file atau folder"), { target: { value: "Archive-old" } });
    await fireEvent.click(screen.getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/rclone/actions", { worker: "local", action: "rename", path: "Archive", name: "Archive-old" }));
  });

  it("loads recursive rclone summaries once and resets selection when worker changes", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    expect(await screen.findByText("4 file · 2 folder · Ukuran tidak lengkap")).toBeTruthy();
    const summaryCalls = mocks.api.mock.calls.filter(([path]) => String(path).startsWith("/storage/rclone/folder-summaries?"));
    expect(summaryCalls).toHaveLength(1);
    await fireEvent.click(screen.getByRole("checkbox", { name: "Pilih folder Archive" }));
    expect(screen.getByText("1 dipilih")).toBeTruthy();
    await fireEvent.change(screen.getByLabelText("Worker target"), { target: { value: "remote-1" } });
    await waitFor(() => expect(screen.queryByText("1 dipilih")).toBeNull());
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("worker=remote-1"))).toBe(true);
  });

  it("browses rclone folders read-only under the selected worker", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    await fireEvent.click(await openRcloneFolderButton("Archive"));
    expect(await screen.findByText("nested.txt")).toBeTruthy();
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("worker=local") && String(path).includes("path=Archive"))).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("submits recursive rclone download for the selected worker and workspace destination", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    await screen.findByRole("checkbox", { name: "Pilih folder Archive" });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Pilih folder Archive" }));
    await fireEvent.click(screen.getByRole("button", { name: "Download 1 dipilih" }));
    await screen.findByRole("heading", { name: "Download ke worker" });
    await findSummary("1 folder · 3 file");
    await fireEvent.click(screen.getByRole("radio", { name: "Pilih downloads" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Buat link publik tanpa kedaluwarsa untuk setiap file" }));
    await fireEvent.click(screen.getByRole("button", { name: "Mulai download" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/downloads", {
      provider: "rclone", worker: "local", rclone_sources: [{ path: "Archive", is_dir: true, size: 0 }], destination_path: "/workspace/downloads", publish_public_links: true,
    }));
  });

  it("submits copy management as an asynchronous rclone job", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    await fireEvent.click(await screen.findByRole("checkbox", { name: "Pilih file report.zip" }));
    await fireEvent.click(screen.getByRole("button", { name: "Copy ke sini" }));
    await fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/rclone/jobs", {
      worker: "local", action: "copy", sources: [{ path: "report.zip", is_dir: false }], destination_path: "", trashed: false, confirmed: false,
    }));
  });

  it("selects visible rclone entries and explains the remote Trash restore boundary", async () => {
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    await screen.findByRole("checkbox", { name: "Pilih folder Archive" });
    await fireEvent.click(screen.getByRole("button", { name: "Pilih semua di halaman" }));
    expect(screen.getByRole("button", { name: "Copy ke sini" })).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "Trash" }));
    await screen.findByRole("checkbox", { name: "Pilih file old.zip" });
    await fireEvent.click(screen.getByRole("button", { name: "Pilih semua di halaman" }));
    await fireEvent.click(screen.getByRole("button", { name: "Pulihkan" }));
    expect(await screen.findByText(/Google Drive hanya menyediakan restore seluruh item Trash/)).toBeTruthy();
  });

  it("lists and revokes public links for the selected worker", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    let revoked = false;
    mocks.api.mockImplementation(async (path: string) => path.startsWith("/storage/download-links")
      ? { items: revoked ? [] : [{ id: "public-1", worker: "local", relative_path: "Archive/report.zip", file_name: "report.zip", provider: "rclone", job_id: "job-1", created_at: "2026-11-11T10:00:00Z", url: "https://files.example.test/public/download/token" }] }
      : baseImplementation!(path));
    mocks.post.mockImplementation(async (path: string) => {
      if (path.includes("/storage/download-links/public-1/revoke")) { revoked = true; return { cleanup_status: "deleted" }; }
      return { id: "job-12345678" };
    });
    render(StoragePage);
    expect(await screen.findByText("report.zip")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Cabut & hapus file" }));
    expect(await screen.findByRole("heading", { name: "Cabut link dan hapus file worker?" })).toBeTruthy();
    await fireEvent.click(screen.getAllByRole("button", { name: "Cabut & hapus file" })[1]);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/download-links/public-1/revoke?worker=local", { confirmed: true }));
  });

  it("keeps old public links manageable while a disabled worker rejects new jobs", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    let revoked = false;
    mocks.api.mockImplementation(async (path: string) => {
      if (path === "/workers") return { items: [{ name: "local", enabled: true }, { name: "remote-1", enabled: false, public_url: "https://remote.example.test" }] };
      if (path.startsWith("/storage/download-links")) return { items: !revoked && path.includes("worker=remote-1") ? [{ id: "remote-link", worker: "remote-1", relative_path: "archive/file.zip", file_name: "file.zip", provider: "rclone", job_id: "old-job", created_at: "2026-11-11T10:00:00Z", url: "https://remote.example.test/public/download/token" }] : [] };
      return baseImplementation!(path);
    });
    mocks.post.mockImplementation(async (path: string) => {
      if (path.includes("remote-link/revoke")) { revoked = true; return { cleanup_status: "deleted" }; }
      return { id: "job-12345678" };
    });
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.change(screen.getByLabelText("Worker target"), { target: { value: "remote-1" } });
    expect(await screen.findByText("file.zip")).toBeTruthy();
    expect(screen.getAllByText(/Worker nonaktif/).length).toBeGreaterThan(0);
    await fireEvent.click(screen.getByRole("tab", { name: "Rclone" }));
    expect((await screen.findByRole("button", { name: "Upload ke folder ini" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mocks.post).not.toHaveBeenCalledWith("/storage/downloads", expect.anything());
    await fireEvent.click(screen.getByRole("button", { name: "Cabut & hapus file" }));
    await fireEvent.click(screen.getAllByRole("button", { name: "Cabut & hapus file" })[1]);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/download-links/remote-link/revoke?worker=remote-1", { confirmed: true }));
  });

  it("submits catalogue sync for an authorized profile and reports the stored job result", async () => {
    mocks.post.mockResolvedValue({ id: "sync-1" });
    const baseImplementation = mocks.api.getMockImplementation();
    mocks.api.mockImplementation(async (path: string) => path === "/jobs/sync-1"
      ? { id: "sync-1", status: "succeeded", result: { value: { history_complete: false, catalog: { recovered: 1, updated: 2, restored: 0, deleted: 0, deletion_held: 3 } } } }
      : baseImplementation!(path));
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("button", { name: "Sinkronkan sekarang" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/sync", { worker: "local", profile: "default" }));
    window.dispatchEvent(new CustomEvent("tme3:job-finished", { detail: { jobIds: ["sync-1"] } }));
    expect(await screen.findByText(/1 dipulihkan, 2 diperbarui/)).toBeTruthy();
    expect(screen.getByText(/Riwayat belum terbukti lengkap/)).toBeTruthy();
  });

  it("scans Storage for one selected worker and shows per-profile operation results", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    mocks.api.mockImplementation(async (path: string) => {
      if (path === "/tdl-access/verification") return { operation_id: "scan-1", status: "succeeded", phase: "completed" };
      if (path === "/operations/scan-1") return { operation_id: "scan-1", status: "succeeded", phase: "completed", progress: { message: "Selesai", overall: { current: 2, total: 2 } } };
      if (path.startsWith("/tdl-access/verification?")) return { profiles: [{ profile: "default", ready: true }, { profile: "archive", ready: false, error_code: "TDL_ACCESS_DENIED" }] };
      return baseImplementation!(path);
    });
    render(StoragePage);
    await findProjectFolderButton();
    await fireEvent.click(screen.getByRole("button", { name: "Scan worker" }));
    expect(await screen.findByText("Pemeriksaan selesai: 1/2 profil dapat mengirim ke Storage.")).toBeTruthy();
    expect(screen.getByText("archive")).toBeTruthy();
    expect(mocks.api).toHaveBeenCalledWith("/tdl-access/verification", expect.objectContaining({ method: "POST", body: JSON.stringify({ purpose: "storage", worker: "local" }) }));
  });

  it("surfaces Storage catalog API errors with a manual retry action", async () => {
    const baseImplementation = mocks.api.getMockImplementation();
    mocks.api.mockImplementation(async (path: string) => path.startsWith("/storage/browser?")
      ? Promise.reject(new Error("catalog unavailable"))
      : baseImplementation!(path));
    render(StoragePage);
    expect((await screen.findByRole("alert")).textContent).toContain("catalog unavailable");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
  });

  it("closes the file detail dialog on Escape and restores focus to its trigger", async () => {
    render(StoragePage);
    await fireEvent.click(await findProjectFolderButton());
    await screen.findAllByText("report.pdf");
    const trigger = screen.getByRole("button", { name: "Detail report.pdf" });
    await fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Detail file" });
    const close = screen.getByRole("button", { name: "Tutup detail file" });
    expect(document.activeElement).toBe(close);
    await fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Detail file" })).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("moves a dragged Telegram file through the existing catalogue action", async () => {
    render(StoragePage);
    await fireEvent.click(await findProjectFolderButton());
    await screen.findAllByText("report.pdf");
    const browser = screen.getByRole("region", { name: "Browser Telegram Storage" });
    await fireEvent.drop(within(browser).getByRole("list"), { dataTransfer: { getData: () => JSON.stringify({ kind: "item", id: 9 }) } });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/storage/actions/move", { item_ids: [9], folder_ids: [], destination_folder_id: 1 }));
  });

  it("keeps keyboard focus inside the file detail dialog", async () => {
    render(StoragePage);
    await fireEvent.click(await findProjectFolderButton());
    await screen.findAllByText("report.pdf");
    await fireEvent.click(screen.getByRole("button", { name: "Detail report.pdf" }));
    const close = screen.getByRole("button", { name: "Tutup detail file" });
    const last = screen.getByRole("button", { name: "Pindahkan ke Trash" });
    await fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    await fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(close);
  });
});
