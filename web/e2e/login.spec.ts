import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("login shell works at the web domain root and has no serious accessibility violations", async ({page}) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/tme3 Control Center/);
  await expect(page.getByRole("button", {name: "Login dengan Telegram"})).toBeVisible();
  const results = await new AxeBuilder({page}).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations.filter((item) => item.impact === "critical" || item.impact === "serious")).toEqual([]);
});
