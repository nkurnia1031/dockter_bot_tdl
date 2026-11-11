import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WorkspaceExplorer from "./WorkspaceExplorer.vue";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../lib/api", () => ({ ...mocks, patch: vi.fn(), post: vi.fn(), put: vi.fn(), remove: vi.fn() }));

describe("WorkspaceExplorer", () => {
  const findSummary = (expected: string) => screen.findByText((_, element) => element?.textContent?.replace(/\s+/g, " ").trim() === expected);
  const findFolderButton = async () => {
    const summary = await findSummary("1 folder · 2 file");
    const button = summary.closest("button.workspace-open");
    if (!button) throw new Error("Folder media tidak memiliki tombol buka.");
    return button;
  };
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.api.mockImplementation(async (path: string) => {
      if (path.includes("path=%2Fworkspace%2Fmedia")) return { path: "/workspace/media", items: [] };
      return { path: "/workspace", items: [{ name: "media", path: "/workspace/media", kind: "directory", files: 2, directories: 1 }] };
    });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("navigates inside Workspace and returns absolute paths", async () => {
    const Harness = {
      components: { WorkspaceExplorer },
      template: `<WorkspaceExplorer v-model:selected="selected" worker="local" />`,
      data: () => ({ selected: [] as string[] }),
    };
    render(Harness);
    await fireEvent.click(await findFolderButton());
    expect(await screen.findByText("/workspace/media")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "Folder induk" }));
    await waitFor(() => expect(screen.getByText("/workspace")).toBeTruthy());
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("worker=local"))).toBe(true);
  });

  it("clears selections and resets to the workspace root when worker changes", async () => {
    const Harness = {
      components: { WorkspaceExplorer },
      template: `<div><button @click="worker = 'remote-2'">Ganti worker</button><WorkspaceExplorer v-model:selected="selected" :worker="worker" /></div>`,
      data: () => ({ selected: ["/workspace/old"], worker: "remote-1" }),
    };
    render(Harness);
    await findFolderButton();
    await fireEvent.click(screen.getByRole("button", { name: "Ganti worker" }));
    await waitFor(() => expect(screen.getByText("/workspace")).toBeTruthy());
    expect(screen.queryByText("/workspace/old ×")).toBeNull();
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes("worker=remote-2"))).toBe(true);
  });

  it("shows an error and refuses to navigate when the worker returns an outside path", async () => {
    mocks.api.mockResolvedValueOnce({ path: "/data/private", items: [] });
    render(WorkspaceExplorer, { props: { worker: "local" } });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("lokasi di luar /workspace");
    expect(screen.queryByText("/data/private")).toBeNull();
  });
});
