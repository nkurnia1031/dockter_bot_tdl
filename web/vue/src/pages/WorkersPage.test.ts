import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import WorkersPage from "./WorkersPage.vue";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("../lib/api", () => mocks);

const workerSettings = {
  worker: "remote-tts",
  worker_api_token_configured: true,
  job_stall_timeout_seconds: 600,
  tdl_export_stall_timeout_seconds: 300,
  tdl_download_stall_timeout_seconds: 300,
  storage_profile: "default",
  storage_profile_available: true,
  available_storage_profiles: ["default"],
  tts_helper_urls: ["http://tts-1", "http://tts-2", "http://tts-3"],
  tts_part_retries: 4,
  tts_retry_base_seconds: 2,
  tts_newnym_after_retries: 3,
};

function setupApi() {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/workers")
      return {
        items: [
          {
            name: "remote-tts",
            url: "http://worker",
            public_url: "",
            enabled: true,
          },
        ],
      };
    if (path.endsWith("/settings")) return workerSettings;
    if (path.endsWith("/tts/health"))
      return {
        worker: "remote-tts",
        ready: false,
        helpers_ready: false,
        profile_session_ready: true,
        reason_code: "TTS_HELPER_NOT_READY",
        helpers: [
          {
            slot: 1,
            status: "ready",
            bootstrap_percent: 100,
            checked_at: "now",
          },
          {
            slot: 2,
            status: "bootstrapping",
            bootstrap_percent: 63,
            checked_at: "now",
          },
          {
            slot: 3,
            status: "helper_unreachable",
            bootstrap_percent: null,
            checked_at: "now",
          },
        ],
      };
    throw new Error(`Unexpected GET ${path}`);
  });
  mocks.post.mockResolvedValue({
    worker: "remote-tts",
    slot: 2,
    accepted: true,
    status: "restarting",
  });
}

describe("WorkersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("checks TTS health only on manual action and does not poll", async () => {
    render(WorkersPage);
    await screen.findByText("remote-tts");
    await fireEvent.click(screen.getByRole("button", { name: "Runtime" }));
    await screen.findByText("Mesin TTS");
    expect(mocks.api).not.toHaveBeenCalledWith(
      "/workers/remote-tts/tts/health",
    );

    await fireEvent.click(
      screen.getByRole("button", { name: "Periksa ulang TTS remote-tts" }),
    );
    expect(await screen.findByText("Bootstrap 63%")).toBeTruthy();
    expect(screen.getByText("Helper tidak terjangkau")).toBeTruthy();
    expect(
      screen.getByText(/Profil yang terverifikasi mengirim: belum ada/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Pulihkan helper 3 remote-tts" }),
    ).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: "Pulihkan helper 2 remote-tts" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/workers/remote-tts/tts/helpers/2/recover",
        {},
      ),
    );
    expect(
      mocks.api.mock.calls.filter(([path]) => path.endsWith("/tts/health")),
    ).toHaveLength(1);
    expect(
      await screen.findByText(/Periksa ulang status secara manual/),
    ).toBeTruthy();
  });

  it("stores a separate public HTTPS origin without exposing the active token", async () => {
    render(WorkersPage);
    await screen.findByText("remote-tts");

    await fireEvent.input(screen.getByPlaceholderText("remote-1"), {
      target: { value: "remote-files" },
    });
    const urls = screen.getAllByPlaceholderText("https://worker.example.com");
    await fireEvent.input(urls[0], {
      target: { value: "http://worker-api:8080" },
    });
    await fireEvent.input(urls[1], {
      target: { value: "https://files.example.test" },
    });
    await fireEvent.input(screen.getByLabelText("Token"), {
      target: { value: "worker-token-value" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Tambahkan worker" }));

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/workers", {
        name: "remote-files",
        url: "http://worker-api:8080",
        public_url: "https://files.example.test",
        token: "worker-token-value",
      }),
    );
    expect(await screen.findByText(/Domain link publik: belum diatur/)).toBeTruthy();
    expect(screen.queryByText("worker-token-value")).toBeNull();
  });
});
