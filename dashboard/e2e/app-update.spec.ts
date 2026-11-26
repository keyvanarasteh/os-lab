import { expect, test, type Page } from "@playwright/test";

/**
 * The update center lives in the layout: it opens on any page, the top bar reopens it, the
 * download shows progress, and after the installer opens os-lab waits for running work, then asks
 * the desktop app to quit (here observed through the `oslab:quit-for-update` event).
 */
type Update = Record<string, unknown>;

async function mock(page: Page, state: { app: Update }) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/app/update" || path === "/api/app/update/check") body = state.app;
    else if (path === "/api/app/update/install") {
      state.app = { ...state.app, installing: true, install: { phase: "downloading", error: null, path: null, received: 40, total: 100 } };
      body = state.app;
    } else if (path === "/api/content/status" || path === "/api/content/check") body = { installed: false, offline: true, updateAvailable: false, sequence: 0, latest: null };
    else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/host") body = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "t", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    await route.fulfill({ json: body });
  });
}

const BASE = { installed: "0.4.8", latest: "0.4.9", updateAvailable: true, checkedAt: Date.now() / 1000, platform: "darwin-aarch64", kind: "dmg",
  releaseUrl: "https://github.com/keyvanarasteh/os-lab/releases/tag/app-v0.4.9", asset: { name: "os-lab_0.4.9_macos_universal.dmg", url: "x" },
  supported: true, offline: false, installing: false, install: null, busy: [] };

test("the update center opens on any page, downloads with progress and waits for running work before closing", async ({ page }) => {
  const state = { app: { ...BASE } as Update };
  await mock(page, state);
  await page.goto("/jobs/");
  await page.evaluate(() => {
    (window as unknown as { __quit: unknown[] }).__quit = [];
    window.addEventListener("oslab:quit-for-update", (e) => (window as unknown as { __quit: unknown[] }).__quit.push((e as CustomEvent).detail));
  });
  const dialog = page.getByRole("dialog", { name: "Updates available" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Later", exact: true }).click();
  await expect(dialog).toHaveCount(0);

  // The top bar reopens it on every page.
  await page.getByRole("button", { name: "Update available" }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Install update" }).click();
  await expect(dialog.getByText("40%", { exact: false })).toBeVisible();

  // The installer opens while a Cleanup Lab clean is still running: wait and show it.
  state.app = { ...BASE, installing: false, install: { phase: "done", error: null, path: "/tmp/os-lab.dmg", received: 100, total: 100, openedAt: 1 },
    busy: [{ id: "c1", kind: "cleanup", label: "Cleanup Lab: clean", lab: "cleanup", startedAt: 1, progress: 0.5 }] };
  await expect(dialog.getByText("Waiting for running work to finish before closing")).toBeVisible();
  await expect(dialog.getByText("Cleanup Lab: clean")).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __quit: unknown[] }).__quit)).toEqual([]);

  // The work ends: a short countdown, then the app is asked to quit (not forced).
  state.app = { ...state.app, busy: [] };
  await expect(dialog.getByText("os-lab closes so the update can finish in")).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __quit: unknown[] }).__quit), { timeout: 10_000 }).toEqual([{ force: false }]);
});

test("Don't close keeps the app open and Close now forces it", async ({ page }) => {
  const state = { app: { ...BASE, install: { phase: "downloading", error: null, path: null, received: 0, total: null }, installing: true } as Update };
  await mock(page, state);
  await page.goto("/jobs/");
  await page.evaluate(() => {
    (window as unknown as { __quit: unknown[] }).__quit = [];
    window.addEventListener("oslab:quit-for-update", (e) => (window as unknown as { __quit: unknown[] }).__quit.push((e as CustomEvent).detail));
  });
  const dialog = page.getByRole("dialog", { name: "Updates available" });
  await expect(dialog).toBeVisible();
  state.app = { ...BASE, install: { phase: "done", error: null, path: "/tmp/os-lab.dmg", received: 1, total: 1, openedAt: 1 }, busy: [] };
  await expect(dialog.getByText("os-lab closes so the update can finish in")).toBeVisible();
  await dialog.getByRole("button", { name: "Don't close" }).click();
  await expect(dialog.getByText("Quit os-lab when you are ready", { exact: false })).toBeVisible();
  await page.waitForTimeout(6000);
  expect(await page.evaluate(() => (window as unknown as { __quit: unknown[] }).__quit)).toEqual([]);
  await dialog.getByRole("button", { name: "Close now" }).click();
  expect(await page.evaluate(() => (window as unknown as { __quit: unknown[] }).__quit)).toEqual([{ force: true }]);
});
