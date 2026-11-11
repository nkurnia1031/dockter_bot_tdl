import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./SettingsPage.vue";

const mocks = vi.hoisted(() => ({ api: vi.fn(), put: vi.fn() }));
vi.mock("../lib/api", () => ({ ...mocks, patch: vi.fn(), post: vi.fn(), remove: vi.fn() }));

const settings = {
  move_size: "10GB",
  compress_size: "2GB",
  rclone_destination: "googledrive:backup",
  compress_password_configured: true,
};
const meta = [
  {
    key: "move_size",
    label: "Batas move",
    description: "Batas ukuran move.",
    format: "ukuran",
    examples: ["10GB"],
    secret: false,
  },
  {
    key: "compress_password",
    label: "Password compress",
    description: "Password archive.",
    format: "teks",
    examples: [],
    secret: true,
  },
];

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.api.mockImplementation(async (path: string) => {
      if (path === "/utility/settings") return settings;
      if (path === "/utility/settings/meta") return { items: meta };
      if (path === "/storage/settings") return { title: "Storage", channel_id: -100123 };
      if (path === "/runtime/secrets") return {
        telegram_bot_token_configured: true,
        telegram_tts_chat_configured: true,
      };
      if (path === "/auth/devices") return { items: [] };
      throw new Error(`Unexpected GET ${path}`);
    });
    mocks.put.mockResolvedValue({
      telegram_bot_token_configured: true,
      restart_required_services: ["backend", "telegram"],
    });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows configured status without exposing stored secrets", async () => {
    render(SettingsPage);
    await screen.findByText("Batas move");
    expect(screen.getByText(/Aktif · Sudah diatur/)).toBeTruthy();
    expect(screen.getByText(/Token bot: Sudah diatur/)).toBeTruthy();
    expect(screen.queryByText(/worker-token|bot-token-secret|compress-secret/i)).toBeNull();
    expect(screen.getByText("-100123")).toBeTruthy();
  });

  it("sends a new bot token only when explicitly submitted and never renders it", async () => {
    render(SettingsPage);
    await screen.findByText("Batas move");
    const secret = "new-sensitive-token";
    await fireEvent.input(screen.getByLabelText("Token bot baru"), {
      target: { value: secret },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Simpan token bot" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith("/runtime/secrets", {
      bot_token: secret,
    }));
    expect(await screen.findByText(/Restart container backend dan telegram/)).toBeTruthy();
    expect(screen.queryByText(secret)).toBeNull();
  });

  it("saves ordinary settings through their existing endpoint", async () => {
    render(SettingsPage);
    await screen.findByText("Batas move");
    await fireEvent.input(screen.getAllByLabelText("Nilai baru")[0], {
      target: { value: "12GB" },
    });
    await fireEvent.click(screen.getAllByRole("button", { name: "Simpan" })[0]);
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith(
      "/utility/settings/move_size",
      { value: "12GB" },
    ));
  });
});
