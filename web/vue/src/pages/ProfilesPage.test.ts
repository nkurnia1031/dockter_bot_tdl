import { mount, flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProfilesPage from "./ProfilesPage.vue";
import { session } from "../session";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  post: vi.fn(),
  remove: vi.fn(),
}));
vi.mock("../lib/api", () => ({
  api: mocks.api,
  post: mocks.post,
  remove: mocks.remove,
}));

const profile = (name = "default", ready = true, deletable = false) => ({
  name,
  ready,
  deletable,
  reason_codes: [],
  checks: [{ name: "identity", ready: true, code: "OK" }],
  upload_lane: {
    status: "ready",
    phase: "complete",
    progress: 100,
    code: "OK",
    updated_at: "2026-11-11T10:00:00Z",
  },
});
const catalog = () => ({
  checked_at: "2026-11-11T10:00:00Z",
  workers: [
    {
      name: "local",
      status: "success",
      checked_at: "2026-11-11T10:00:00Z",
      error_code: "",
    },
    {
      name: "remote-1",
      status: "success",
      checked_at: "2026-11-11T10:00:00Z",
      error_code: "",
    },
  ],
  inventories: [
    {
      worker: "local",
      checked_at: "2026-11-11T10:00:00Z",
      items: [profile("default", true), profile("irang", false, true)],
    },
    {
      worker: "remote-1",
      checked_at: "2026-11-11T10:00:00Z",
      items: [profile("default", true)],
    },
  ],
  runtime_readiness: {
    checked_at: "2026-11-11T10:00:00Z",
    workers: [
      { name: "local", status: "success" },
      { name: "remote-1", status: "success" },
    ],
    cells: [
      {
        worker: "local",
        profile: null,
        runtime: "tts_helper",
        status: "ready",
        checked_at: "2026-11-11T10:00:00Z",
        reason_code: "",
      },
      {
        worker: "local",
        profile: "default",
        runtime: "export",
        status: "ready",
        checked_at: "2026-11-11T10:00:00Z",
        reason_code: "",
      },
      {
        worker: "local",
        profile: "default",
        runtime: "download",
        status: "not_ready",
        checked_at: "2026-11-11T10:00:00Z",
        reason_code: "PROFILE_SESSION_UNAVAILABLE",
        last_attempt: {
          target: { worker: "local", profile: "default", runtime: "download" },
          checked_at: "2026-11-11T09:59:00Z",
          phase: "download_canary",
          checks: [
            {
              name: "download",
              status: "not_ready",
              reason_code: "PROFILE_SESSION_UNAVAILABLE",
            },
          ],
          status: "not_ready",
          reason_code: "PROFILE_SESSION_UNAVAILABLE",
          dependencies: [],
          cleanup: { status: "not_needed", reason_code: "" },
        },
      },
    ],
  },
});
const management = () => ({
  items: [
    {
      name: "vaulted",
      vault: true,
      status: "stored",
      source: "vault",
      desired_revision: 2,
      workers: [],
    },
  ],
  workers: [
    { name: "local", enabled: true, online: true, secure: true },
    { name: "remote-1", enabled: true, online: true, secure: true },
  ],
});

const mounted: ReturnType<typeof mount>[] = [];
function mountPage() {
  const wrapper = mount(ProfilesPage, {
    global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
  });
  mounted.push(wrapper);
  return wrapper;
}

describe("ProfilesPage", () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.post.mockReset();
    mocks.remove.mockReset();
    session.current = {
      authenticated: true,
      actor: {
        telegram_user_id: 17,
        profile: "default",
        worker_route: "local",
      },
      profiles: ["default"],
    };
    mocks.api.mockImplementation((path: string) => {
      if (path === "/workers")
        return Promise.resolve({
          items: [
            { name: "local", enabled: true },
            { name: "remote-1", enabled: true },
          ],
        });
      if (path === "/profiles/local")
        return Promise.resolve({
          ...catalog(),
          profiles: [
            { name: "default", workers: ["local"], exclusive_worker: "" },
          ],
        });
      if (path === "/profiles/local/scan")
        return Promise.resolve({ operation: null });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/operations?limit=100")
        return Promise.resolve({ items: [] });
      if (path.startsWith("/profiles/") && path.endsWith("/distributions"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({ items: [] });
    });
    mocks.post.mockResolvedValue({ id: "operation-1", status: "queued" });
    mocks.remove.mockResolvedValue({ cancelled: true });
  });

  afterEach(() => {
    for (const wrapper of mounted.splice(0)) wrapper.unmount();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("groups workers, profiles, and runtime readiness while keeping unscanned cells visible", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(wrapper.text()).toContain("Kesiapan layanan per worker dan profil");
    expect(wrapper.text()).toContain("Worker local");
    expect(wrapper.text()).toContain("Profil default");
    expect(wrapper.text()).toContain("TorTTS");
    expect(wrapper.text()).toContain("Export");
    expect(wrapper.text()).toContain("Download");
    expect(wrapper.text()).toContain("Belum dipindai");
    expect(
      wrapper
        .find('button[aria-label="Hapus profil default dari local"]')
        .exists(),
    ).toBe(false);
  });

  it("sends a lane scan to exactly the selected worker and profile and shows its last attempt log", async () => {
    mocks.post.mockResolvedValue({
      id: "lane-scan",
      status: "succeeded",
      target: {
        kind: "profile_runtime",
        worker: "local",
        profile: "default",
        runtime: "download",
      },
      error_code: "",
      progress: {
        workers: [],
        total_workers: 1,
        completed_workers: 1,
        total_profiles: 1,
        completed_profiles: 1,
      },
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper
      .get('button[aria-label="Scan Download profil default worker local"]')
      .trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith("/profiles/local/scan/service", {
      worker: "local",
      profile: "default",
      runtime: "download",
    });
    expect(wrapper.text()).toContain(
      "Download profil default pada worker local",
    );
    await wrapper
      .get(
        'button[aria-label="Lihat log uji Download profil default worker local"]',
      )
      .trigger("click");
    expect(wrapper.get('[role="dialog"]').text()).toContain(
      "Pemeriksaan sesi tidak tersedia.",
    );
    expect(wrapper.get('[role="dialog"]').text()).toContain("Cleanup");
  });

  it("streams raw per-worker scan logs as text without interpreting markup", async () => {
    const operation = {
      id: "scan-local",
      status: "running",
      target: { kind: "worker", worker: "local" },
      error_code: "",
      progress: {
        workers: [
          {
            name: "local",
            status: "running",
            phase: "profile_probe",
            profiles: [],
          },
        ],
        total_workers: 1,
        completed_workers: 0,
        total_profiles: 1,
        completed_profiles: 0,
      },
    };
    mocks.post.mockResolvedValue(operation);
    mocks.api.mockImplementation((path: string) => {
      if (path === "/workers")
        return Promise.resolve({
          items: [
            { name: "local", enabled: true },
            { name: "remote-1", enabled: true },
          ],
        });
      if (path === "/profiles/local") return Promise.resolve(catalog());
      if (path === "/profiles/local/scan")
        return Promise.resolve({ operation: null });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path.startsWith("/profiles/local/scan/scan-local/logs?"))
        return Promise.resolve({
          events: [
            {
              sequence: 1,
              worker: "local",
              profile: "default",
              runtime: "export",
              kind: "output",
              stream: "stdout",
              text: "<script>raw command output</script>",
              exit_code: null,
              created_at: "2026-11-11T10:00:00Z",
            },
          ],
          next_sequence: 1,
          has_more: false,
        });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper.get('select[aria-label="Worker"]').setValue("local");
    await flushPromises();
    const scanSelected = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Scan worker terpilih"));
    expect(scanSelected).toBeDefined();
    await scanSelected!.trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith("/profiles/local/scan/worker", {
      worker: "local",
    });
    expect(mocks.post).not.toHaveBeenCalledWith(
      "/profiles/local/scan",
      undefined,
    );
    await wrapper
      .get('button[aria-label="Buka log realtime worker local"]')
      .trigger("click");
    await flushPromises();
    const dialog = wrapper.get('[role="dialog"][aria-label="Worker local"]');
    expect(dialog.text()).toContain("<script>raw command output</script>");
    expect(dialog.find("script").exists()).toBe(false);
    expect(
      mocks.api.mock.calls.some(([path]) =>
        String(path).includes("scan-local/logs?worker=local&after_sequence=0"),
      ),
    ).toBe(true);
  });

  it("preserves local rows when a delete request fails before worker execution", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.api.mockImplementation((path: string) => {
      if (path === "/workers")
        return Promise.resolve({
          items: [
            { name: "local", enabled: true },
            { name: "remote-1", enabled: true },
          ],
        });
      if (path === "/profiles/local") return Promise.resolve(catalog());
      if (path === "/profiles/local/scan")
        return Promise.resolve({ operation: null });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/operations?limit=100")
        return Promise.resolve({ items: [] });
      return Promise.resolve({ items: [] });
    });
    const failure = Object.assign(new Error("worker offline"), {
      code: "WORKER_UNAVAILABLE",
    });
    const baseApi = mocks.api.getMockImplementation();
    mocks.api.mockImplementation((path: string, options?: RequestInit) => {
      if (
        path === "/workers/local/profiles/local/irang" &&
        options?.method === "DELETE"
      )
        return Promise.reject(failure);
      return baseApi?.(path, options) ?? Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper.get('select[aria-label="Worker"]').setValue("local");
    await flushPromises();
    const removeButton = wrapper.find(
      'button[aria-label="Hapus profil irang dari local"]',
    );
    await removeButton.trigger("click");
    await flushPromises();
    expect(mocks.api).toHaveBeenCalledWith(
      "/workers/local/profiles/local/irang",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          "Idempotency-Key": expect.any(String),
        }),
      }),
    );
    expect(wrapper.find('[role="alert"]').text()).toContain("worker offline");
    expect(wrapper.text()).toContain("Profil irang");
  });

  it("uses the selected worker for local provisioning and displays the returned QR without leaking input state", async () => {
    mocks.post.mockResolvedValue({
      id: "provision-1",
      status: "authenticating",
    });
    mocks.api.mockImplementation((path: string) => {
      if (path === "/workers")
        return Promise.resolve({
          items: [
            { name: "local", enabled: true },
            { name: "remote-1", enabled: true },
          ],
        });
      if (path === "/profiles/local") return Promise.resolve(catalog());
      if (path === "/profiles/local/scan")
        return Promise.resolve({ operation: null });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/profiles/provisionings/provision-1")
        return Promise.resolve({
          id: "provision-1",
          profile: "newprofile",
          status: "authenticating",
          source: "login",
          bootstrap_worker: "remote-1",
          workers: [],
          login: { status: "running", step: "qr", qr_text: "QR-CODE-LOCAL" },
        });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper
      .get('select[aria-label="Worker penambahan"]')
      .setValue("remote-1");
    await wrapper
      .get('input[aria-label="Nama profil baru"]')
      .setValue("newprofile");
    await wrapper.get('button[aria-pressed="false"]').trigger("click");
    const startLogin = wrapper
      .findAll("button")
      .find((button) => button.text().includes("Mulai login QR"));
    expect(startLogin).toBeDefined();
    await startLogin!.trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith("/profiles/provisionings/login", {
      name: "newprofile",
      worker: "remote-1",
      method: "qr",
      phone: "",
      local_only: true,
    });
    expect(wrapper.text()).toContain("QR-CODE-LOCAL");
  });

  it("adopts a ready profile from only the selected worker", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.post.mockResolvedValue({ id: "adopt-1", status: "validating" });
    mocks.api.mockImplementation((path: string) => {
      if (path === "/workers")
        return Promise.resolve({
          items: [
            { name: "local", enabled: true },
            { name: "remote-1", enabled: true },
          ],
        });
      if (path === "/profiles/local") return Promise.resolve(catalog());
      if (path === "/profiles/local/scan")
        return Promise.resolve({ operation: null });
      if (path === "/profiles/management") return Promise.resolve(management());
      if (path === "/operations?limit=100")
        return Promise.resolve({ items: [] });
      if (path === "/profiles/provisionings/adopt-1")
        return Promise.resolve({ id: "adopt-1", status: "stored" });
      return Promise.resolve({ items: [] });
    });
    const wrapper = mountPage();
    await flushPromises();
    await wrapper.get('select[aria-label="Worker"]').setValue("local");
    await flushPromises();
    await wrapper
      .get('button[aria-label="Adopsi profil default dari local ke Vault"]')
      .trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith("/profiles/default/adopt", {
      worker: "local",
    });
    expect(mocks.post).not.toHaveBeenCalledWith(
      "/profiles/default/distributions",
      expect.anything(),
    );
    expect(wrapper.text()).toContain("tersimpan di Vault");
  });
});
