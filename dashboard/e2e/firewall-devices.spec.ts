import { expect, test } from "@playwright/test";
import catalog from "../../firewall-lab/catalog.json" with { type: "json" };

const total = catalog.firewalls.length;
const detail = "acme-academy--istanbul-hq--perimeter";

test.beforeEach(async ({ page }) => {
  // No console here: the pages fall back to the companies built into them.
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { error: "Not found" } }));
});

test("search, filter, open a firewall and come back to the same list", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/firewall/devices/");
  const main = page.getByRole("main");
  const rows = main.locator("ul > li > a");
  await expect(rows).toHaveCount(total);

  await main.getByRole("searchbox").fill("acme fortigate 100f");
  await main.getByLabel("Segment").selectOption("perimeter");
  await expect(page).toHaveURL(/q=acme\+fortigate\+100f&segment=perimeter/);
  const link = main.locator(`a[href*="id=${detail}"]`);
  await link.click();

  await expect(main.getByRole("heading", { level: 1, name: "FortiGate 100F" })).toBeVisible();
  await expect(main.getByRole("heading", { name: "Compared alternatives" })).toBeVisible();
  await expect(main.getByText("Palo Alto PA-440")).toBeVisible();
  await expect(main.getByRole("link", { name: "ACME Academy" })).toHaveAttribute("href", "/firewall/acme-academy/");

  await main.getByRole("link", { name: "All firewalls" }).click();
  await expect(main.getByRole("searchbox")).toHaveValue("acme fortigate 100f");
  await main.getByRole("button", { name: "Clear filters" }).click();
  await expect(rows).toHaveCount(total);
  expect(errors).toEqual([]);
});

test("no match, unknown id and the overview entry point", async ({ page }) => {
  await page.goto("/firewall/devices/?q=zzzz-nothing");
  await expect(page.getByRole("main").getByText("No firewall matches these filters.")).toBeVisible();
  await page.goto("/firewall/device/?id=missing");
  await expect(page.getByRole("main").getByText("This firewall was not found.")).toBeVisible();
  await page.goto("/firewall/");
  await page.getByRole("main").getByRole("link", { name: "Search all firewalls" }).click();
  await expect(page).toHaveURL(/\/firewall\/devices\/$/);
});

test("the Turkish pages work on a phone without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  for (const path of ["/tr/firewall/devices/", `/tr/firewall/device/?id=${detail}`]) {
    await page.goto(path);
    await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), path).toBeLessThanOrEqual(2);
  }
  await expect(page.getByRole("main").getByRole("link", { name: "Tüm güvenlik duvarları" })).toBeVisible();
});
