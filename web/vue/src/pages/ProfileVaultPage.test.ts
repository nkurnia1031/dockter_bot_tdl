import { mount, flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProfileVaultPage from "./ProfileVaultPage.vue";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../lib/api", () => ({ api: mocks.api }));

const operation = {
  id: "distribution-1",
  profile: "ruth2",
  revision: 7,
  target_workers: ["local", "remote-1"],
  status: "failed",
  created_at: "2026-11-11T10:00:00Z",
  updated_at: "2026-11-11T10:01:00Z",
  workers: [
    {
      worker: "local",
      status: "failed",
      phase: "failed",
      reason_code: "PROFILE_INSTALL_FAILED",
      updated_at: "2026-11-11T10:01:00Z",
    },
    {
      worker: "remote-1",
      status: "ready",
      phase: "completed",
      reason_code: "",
      updated_at: "2026-11-11T10:01:00Z",
    },
  ],
};
const management = () => ({
  workers: [
    { name: "local", enabled: true, online: true, secure: true },
    { name: "remote-1", enabled: true, online: true, secure: true },
  ],
  items: [
    {
      name: "ruth2",
      active: true,
      vault: true,
      status: "stored",
      desired_revision: 7,
      workers: [],
    },
  ],
});

const mounted: ReturnType<typeof mount>[] = [];
function mountPage() {
  const wrapper = mount(ProfileVaultPage, {
    global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
  });
  mounted.push(wrapper);
  return wrapper;
}

describe("ProfileVaultPage", () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.api.mockImplementation((path: string) => {
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/profiles/ruth2/distributions")
        return Promise.resolve({ items: [] });
      if (path.startsWith("/profile-distributions/"))
        return Promise.resolve({ items: [], active: false, next_after_id: 0 });
      return Promise.resolve({ items: [] });
    });
  });
  afterEach(() => {
    for (const wrapper of mounted.splice(0)) wrapper.unmount();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows Vault membership independently from installed worker state", async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === "/profiles/management")
        return Promise.resolve({
          workers: [
            { name: "remote-1", enabled: true, online: false, secure: true },
          ],
          items: [
            {
              name: "ruth2",
              active: true,
              vault: true,
              status: "stored",
              desired_revision: 3,
              workers: [
                {
                  worker: "remote-1",
                  status: "waiting",
                  desired_revision: 3,
                  installed_revision: null,
                  error: "Worker belum menerima sesi.",
                },
              ],
            },
          ],
        });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain("ruth2");
    expect(wrapper.text()).toContain("Tersimpan di Vault");
    expect(wrapper.text()).toContain("Menunggu worker");
    expect(wrapper.text()).toContain("Worker belum menerima sesi.");
    expect(
      mocks.api.mock.calls.some(([path]) =>
        String(path).includes("profile-sync"),
      ),
    ).toBe(false);
  });

  it("distributes one pinned revision and retries only the worker that failed", async () => {
    const calls: Array<{ path: string; method: string; key?: string }> = [];
    let started = false;
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      const method = init?.method || "GET";
      calls.push({
        path,
        method,
        key: new Headers(init?.headers).get("Idempotency-Key") || undefined,
      });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/profiles/ruth2/distributions" && method === "GET")
        return Promise.resolve({ items: started ? [operation] : [] });
      if (path === "/profile-distributions/distribution-1/events?limit=100")
        return Promise.resolve({
          items: [
            {
              id: 1,
              worker: "local",
              sequence: 1,
              phase: "archive_download",
              status: "failed",
              code: "PROFILE_INSTALL_FAILED",
              created_at: "2026-11-11T10:01:00Z",
            },
          ],
          active: false,
          next_after_id: 1,
        });
      if (path === "/profiles/ruth2/distributions" && method === "POST") {
        started = true;
        return Promise.resolve(operation);
      }
      if (path.endsWith("/workers/local/retry") && method === "POST")
        return Promise.resolve({ ...operation, status: "queued" });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper
      .get(
        'button[aria-label="Distribusikan ruth2 revision 7 ke semua worker"]',
      )
      .trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("snapshot: local, remote-1");
    expect(wrapper.text()).toContain("Unduh arsip dari channel");
    const retry = wrapper.get(
      'button[aria-label="Retry distribusi distribution-1 pada local"]',
    );
    await retry.trigger("click");
    await flushPromises();
    const distribution = calls.find(
      (call) =>
        call.path === "/profiles/ruth2/distributions" && call.method === "POST",
    );
    const retryCall = calls.find(
      (call) =>
        call.path.endsWith("/workers/local/retry") && call.method === "POST",
    );
    expect(distribution?.key).toBeTruthy();
    expect(retryCall?.key).toBeTruthy();
    expect(
      calls.some((call) => call.path.endsWith("/workers/remote-1/retry")),
    ).toBe(false);
  });

  it("deletes only the Vault bundle after explicit confirmation", async () => {
    const confirmation = vi.spyOn(window, "confirm").mockReturnValue(true);
    const deletes: string[] = [];
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/profiles/ruth2/vault" && init?.method === "DELETE") {
        deletes.push(path);
        return Promise.resolve({
          deleted: true,
          profile: "ruth2",
          local_copies_unchanged: true,
        });
      }
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper
      .get('button[aria-label="Hapus bundle ruth2 dari Vault"]')
      .trigger("click");
    await flushPromises();
    expect(confirmation).toHaveBeenCalledWith(
      expect.stringContaining("Sesi pada worker lokal tidak akan dihapus"),
    );
    expect(deletes).toEqual(["/profiles/ruth2/vault"]);
    expect(wrapper.text()).toContain(
      "Bundle ruth2 dihapus dari Vault. Sesi worker lokal tetap utuh.",
    );
    expect(wrapper.text()).toContain(
      "Belum ada profil yang tersimpan di Vault.",
    );
  });

  it("polls an active distribution and stops after the terminal result", async () => {
    vi.useFakeTimers();
    let reads = 0;
    mocks.api.mockImplementation((path: string) => {
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/profiles/ruth2/distributions") {
        reads += 1;
        return Promise.resolve({
          items: [
            { ...operation, status: reads === 1 ? "running" : "succeeded" },
          ],
        });
      }
      return Promise.resolve({ items: [], active: false, next_after_id: 0 });
    });
    const wrapper = mountPage();
    await flushPromises();
    expect(reads).toBe(1);
    await vi.advanceTimersByTimeAsync(3000);
    await flushPromises();
    expect(reads).toBe(2);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(reads).toBe(2);
    wrapper.unmount();
    mounted.splice(mounted.indexOf(wrapper), 1);
  });
});
