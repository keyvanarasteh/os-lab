/**
 * CLN-30: the notification outbox surfaces as a toast stack and a Settings
 * card. The console is mocked with typed fixture payloads, exactly like the
 * other cleanup specs; the 5 s outbox poll is waited out with generous
 * expect timeouts instead of poking store internals.
 */
import { expect, test, type Page } from "@playwright/test";

const EVENT = {
  id: 7,
  at: Date.now() / 1000 - 2,
  category: "monitor-warning",
  title: "Free space is running low",
  body: "/Volumes/Backup is below its free-space floor (8.2 GB free).",
  route: "scan",
  actions: [{ id: "scan", label: "Run a scan", route: "scan" }, { id: "open", label: "Open monitor", route: "cleanup-monitor" }]
};

const CATEGORIES = { "job-done": true, "job-failed": true, "auto-clean": true, "monitor-warning": true, "monitor-recovered": true, "monitor-error": true };

type NotificationsPayload = Record<string, unknown> & { events: Record<string, unknown>[] };

/** Mock every endpoint the cleanup pages and the shell fetch, notifications by reference. */
function mockConsole(page: Page, notifications: NotificationsPayload) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  void page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") calls.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/notifications") data = notifications;
    else if (path === "/api/cleanup/notifications/config") Object.assign(notifications, body);
    else if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [{ mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs", kind: "root", totalBytes: 500_000_000_000, freeBytes: 250_000_000_000, usedBytes: 250_000_000_000, usage: 0.5, purgeableBytes: null, isHome: true, pressure: "ok", error: null }], homeVolume: "/", warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/explorer/roots") data = { roots: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/widget") data = { schemaVersion: 1, capable: false, publish: { published: false, path: null, reason: "no container" } };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  return calls;
}

test("settings card edits the config, toasts arrive and their actions navigate", async ({ page }) => {
  const notifications: NotificationsPayload = { enabled: true, categories: { ...CATEGORIES }, events: [], configError: null, runtime: null };
  const calls = mockConsole(page, notifications);

  await page.goto("/cleanup/settings/");
  await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
  await expect(page.getByText("Notifications enabled")).toBeVisible();
  await expect(page.getByText("Desktop app not detected — in-app notifications only.")).toBeVisible();

  // The card sends the whole config; unchecking one category turns exactly
  // that flag off. The checkbox is controlled by the polled store, so the
  // state lands after the POST → refresh round trip.
  const monitorWarnings = page.getByRole("checkbox", { name: "Monitor warnings" });
  await monitorWarnings.click();
  await expect(monitorWarnings).not.toBeChecked();
  const saved = calls.find((call) => call.path === "/api/cleanup/notifications/config");
  expect(saved?.body.enabled).toBe(true);
  expect(saved?.body.categories).toMatchObject({ "monitor-warning": false, "job-done": true });

  // A new outbox event lands as a toast with its actions (the 5 s poll picks it up).
  notifications.events = [EVENT];
  const toast = page.getByRole("status").filter({ hasText: "Free space is running low" }).first();
  await expect(toast).toBeVisible({ timeout: 10000 });
  await expect(toast.getByRole("link", { name: "Run a scan" })).toBeVisible();

  // The action navigates in place to the matching cleanup tab; the toast
  // (the shell's, outside the island) stays and is swiped away there.
  await toast.getByRole("link", { name: "Run a scan" }).click();
  await expect(page).toHaveURL(/\/cleanup\/scan\/$/);
  const swiped = page.getByRole("status").filter({ hasText: "Free space is running low" }).first();
  await expect(swiped).toBeVisible();
  const box = await swiped.boundingBox();
  if (!box) throw new Error("toast box not found");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByRole("status").filter({ hasText: "Free space is running low" })).toHaveCount(0);
});

test("the stack caps at three visible toasts and the overflow chip clears the rest", async ({ page }) => {
  const notifications: NotificationsPayload = { enabled: true, categories: { ...CATEGORIES }, events: [], configError: null, runtime: null };
  mockConsole(page, notifications);

  await page.goto("/cleanup/");
  // A burst of events after load (the outbox fills while the page is open).
  notifications.events = [5, 6, 7, 8, 9].map((id) => ({
    ...EVENT,
    id,
    title: `Job finished ${id}`,
    category: "job-done",
    route: "results",
    actions: [{ id: "open", label: "View results", route: "results" }]
  }));
  await expect(page.getByText("Job finished 9")).toBeVisible({ timeout: 10000 });
  // Only the newest three render; the rest collapse into the overflow chip.
  await expect(page.getByText("Job finished 8")).toBeVisible();
  await expect(page.getByText("Job finished 7")).toBeVisible();
  await expect(page.getByText("Job finished 6")).toHaveCount(0);
  await expect(page.getByText("+2")).toBeVisible();
  await page.getByText("+2").click();
  await expect(page.getByText("Job finished 9")).toHaveCount(0);
  await expect(page.getByText("Job finished 7")).toHaveCount(0);
});
