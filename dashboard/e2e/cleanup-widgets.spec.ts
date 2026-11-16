import { expect, test } from "@playwright/test";
import type { CleanupWidgetSnapshot } from "../src/lib/api";

/**
 * CLW-10/13: the desktop-widgets card — preview from the snapshot payload,
 * publish on demand, the overview card routes to the section, and the app's
 * deep-link/quick-clean globals work without a reload.
 */
const WIDGET: CleanupWidgetSnapshot = {
  schemaVersion: 1,
  capturedAt: 1_800_000_000,
  platform: "macos",
  capable: true,
  disk: { mountPoint: "/", totalBytes: 500_000_000_000, freeBytes: 232_800_000_000, usedPercent: 53.4 },
  lastScan: { finishedAt: 1_799_999_000, foundItems: 18, foundBytes: 4_200_000_000, unreadable: 0 },
  progress: null,
  cleanup: { totalReclaimedBytes: 32_000_000_000, lastRunAt: 1_799_000_000 },
  monitor: { enabled: true, intervalSeconds: 300, nextCheckAt: 1_800_000_300, lastWarningAt: null, warningCount: 0 },
  bookmarks: { count: 3, quickCleanCount: 2, hookCount: 1, alertCount: 0 },
  permissions: { fullDiskAccess: true },
  status: "ready-to-clean",
  publish: { published: true, path: "/Group Containers/widget-snapshot.json", reason: null },
};

async function mockConsole(page: import("@playwright/test").Page, widget: object = WIDGET) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/widget") data = widget;
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: true, running: true, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/bookmarks/quick-clean") data = { job: { id: "plan-widget", kind: "plan", state: "running", request: { entryIds: ["a"] }, progress: null, result: null, error: null, startedAt: 1, finishedAt: null }, refusals: [] };
    else if (path === "/api/cleanup/jobs/plan-widget") data = { id: "plan-widget", kind: "plan", state: "done", request: { entryIds: ["a"] }, progress: null, result: { planId: "p1", mode: "trash", totals: { ready: 1, bytes: 1024, skipped: 0 }, items: [], expiresAt: 9_000_000_000 }, error: null, startedAt: 1, finishedAt: 2 };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
}

test("the widgets card renders the snapshot preview and republishes", async ({ page }) => {
  const publishes: number[] = [];
  await mockConsole(page);
  await page.route("**/api/cleanup/widget", async (route) => {
    publishes.push(Date.now());
    await route.fulfill({ json: WIDGET });
  });
  await page.goto("/cleanup/settings/");
  await expect(page.getByRole("heading", { name: "Desktop widgets" }).first()).toBeVisible();
  // Publishing is automatic: opening the page already built and published the snapshot.
  await expect(page.getByText("Kept up to date automatically.")).toBeVisible();
  expect(publishes.length).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Publish now" })).toHaveCount(0);
  // The preview mirrors the widget's content, collapsed until asked for.
  await page.getByText("What the widget shows", { exact: true }).click();
  await expect(page.getByText("Ready to clean")).toBeVisible();
  await expect(page.getByText("18 items")).toBeVisible();
  await expect(page.getByText("3.9 GB")).toBeVisible();
  await expect(page.getByText("30 GB")).toBeVisible();
  await expect(page.getByText("FDA granted")).toBeVisible();
});

test("a not-capable machine states the honest reason", async ({ page }) => {
  await mockConsole(page, { ...WIDGET, capable: false, publish: { published: false, path: null, reason: "The widget container is not available here." } });
  await page.goto("/cleanup/settings/");
  await expect(page.getByRole("heading", { name: "Desktop widgets" }).first()).toBeVisible();
  await expect(page.getByText("Publishing is idle until the installed os-lab app creates its widget container.")).toBeVisible();
  // The absent-container case explains itself once; the engine's publish
  // refusal is redundant here and must not contradict the idle note.
  await expect(page.getByText("The widget container is not available here.")).toHaveCount(0);
});

test("an empty payload degrades instead of crashing the island", async ({ page }) => {
  await mockConsole(page, {});
  await page.goto("/cleanup/settings/");
  await expect(page.getByRole("heading", { name: "Desktop widgets" }).first()).toBeVisible();
  await expect(page.getByText("The widget snapshot appears after the first publish.")).toBeVisible();
});

test("the overview card scrolls to the widgets section", async ({ page }) => {
  await mockConsole(page);
  // The capability grid moved to the Settings tab with the cards it navigates to.
  await page.goto("/cleanup/settings/");
  await expect(page.getByRole("heading", { name: "Desktop widgets" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Desktop widgets/ }).click();
  await expect(page.locator("#cleanup-widgets")).toBeInViewport();
});

test("the app globals drive deep links and the quick-clean review", async ({ page }) => {
  await mockConsole(page);
  await page.goto("/cleanup/");
  await expect(page.getByRole("heading", { name: "Cleanup Lab" }).first()).toBeVisible();
  // Deep link to a tab: in-place navigation, real URL.
  await page.evaluate(() => (window as unknown as { __oslabNavigate?: (route: string) => void }).__oslabNavigate?.("scan/"));
  await expect(page).toHaveURL(/\/cleanup\/scan\/$/);
  // Deep link back to a section: overview page + scrolled section.
  // The widgets section moved to the Settings tab; the section id stays the deep-link target.
  await page.evaluate(() => (window as unknown as { __oslabNavigate?: (route: string) => void }).__oslabNavigate?.("cleanup-widgets"));
  await expect(page).toHaveURL(/\/cleanup\/settings\/$/);
  await expect(page.locator("#cleanup-widgets")).toBeInViewport();
  // The widget's quick-clean intent builds the plan and opens the review dialog.
  await page.evaluate(() => { (window as unknown as { __e2eMarker?: number }).__e2eMarker = 7; });
  await page.evaluate(() => (window as unknown as { __oslabQuickClean?: () => void }).__oslabQuickClean?.());
  await expect(page.getByRole("heading", { name: "Confirm cleanup" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __e2eMarker?: number }).__e2eMarker)).toBe(7);
});
