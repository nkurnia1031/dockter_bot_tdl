import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";
import DevelopmentPage from "./DevelopmentPage.vue";

describe("DevelopmentPage", () => {
  afterEach(() => cleanup());

  it("preserves the development report and production testing boundary", () => {
    render(DevelopmentPage);
    expect(screen.getByRole("heading", { name: "Pengembangan" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Tes otomatis" })).toBeTruthy();
    expect(screen.getByText(/Tes production hanya dijalankan dari mesin\/workspace ini/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Query status job" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ide berikutnya" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Kerja ulang pada metrik monitor" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Setup koneksi SQLite" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Buka GitHub Actions/ }).getAttribute("href"))
      .toBe("https://github.com/nkurnia1031/dockter_bot_tdl/actions");
  });
});
