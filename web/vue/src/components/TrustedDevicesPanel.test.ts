import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TrustedDevicesPanel from "./TrustedDevicesPanel.vue";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
  remove: vi.fn(),
}));
vi.mock("../lib/api", () => mocks);

const fingerprint = "SHA256:Zmh6rfhivXdsj8GLjp+OIAiXFIVu4jOzkCpZHQ1fKSU";
const device = {
  id: "fd9f67f1-bba8-4011-9ed3-0f819ac8df10",
  name: "Agent laptop",
  algorithm: "Ed25519",
  fingerprint,
  origin: window.location.origin,
  created_at: "2026-10-04T10:00:00Z",
  last_used_at: null,
  revoked_at: null,
  status: "active" as const,
};

describe("TrustedDevicesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.api.mockResolvedValue({ items: [device] });
    mocks.patch.mockResolvedValue({ device });
    mocks.post.mockResolvedValue({ device, created: true });
    mocks.remove.mockResolvedValue({ revoked: true });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("lists only public device metadata and supports explicit refresh", async () => {
    render(TrustedDevicesPanel);
    expect(await screen.findByText("Agent laptop")).toBeTruthy();
    expect(screen.getByText(fingerprint)).toBeTruthy();
    expect(screen.queryByText(/private_key/i)).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledTimes(2));
  });

  it("approves a validated public enrollment without posting private-key fields", async () => {
    mocks.api.mockResolvedValue({ items: [] });
    const digest = Uint8Array.from(
      "66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925".match(/../g)!,
      (part) => Number.parseInt(part, 16),
    );
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn().mockResolvedValue(digest.buffer) },
    });
    const enrollment = {
      version: 1,
      device_id: device.id,
      name: device.name,
      algorithm: "Ed25519",
      public_key: btoa(String.fromCharCode(...new Uint8Array(32)))
        .replace(/=+$/, "")
        .replace(/\+/g, "-")
        .replace(/\//g, "_"),
      fingerprint,
      origin: window.location.origin,
    };
    const file = new File([JSON.stringify(enrollment)], "device-enrollment.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: async () => JSON.stringify(enrollment),
    });

    render(TrustedDevicesPanel);
    await fireEvent.change(screen.getByLabelText("Berkas public key enrollment"), {
      target: { files: [file] },
    });
    expect(await screen.findByText(fingerprint)).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: "Setujui dan tambahkan" }),
    );
    await screen.findByText("Perangkat berhasil ditambahkan.");
    expect(mocks.post).toHaveBeenCalledWith("/auth/devices", enrollment);
    expect(JSON.stringify(mocks.post.mock.calls)).not.toContain("private_key");
  });

  it("requires confirmation before revoking device access", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(TrustedDevicesPanel);
    await screen.findByText("Agent laptop");
    await fireEvent.click(screen.getByRole("button", { name: "Cabut" }));
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(
      `/auth/devices/${device.id}`,
    ));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("sesi browser"));
  });
});
