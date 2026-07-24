import { describe, expect, it } from "vitest";
import { formatBytes } from "./api";

describe("formatBytes", () => {
  it("does not turn unknown expected media size into zero", () => {
    expect(formatBytes(undefined)).toBe("Tidak diketahui");
  });

  it("formats known binary sizes for artifact tables", () => {
    expect(formatBytes(1024 * 1024)).toBe("1.00 MB");
  });
});
