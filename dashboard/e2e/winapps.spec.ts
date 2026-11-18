import { expect, test, type Page } from "@playwright/test";
import type { LabStatus } from "../src/lib/api";

const winapps = {
  available: true,
  reason: null,
  windows: [
    {
      windowId: 100,
      pid: 100,
      app: "Notepad",
      elevated: false,
      title: "Fixture - Notepad",
      className: "Notepad",
      x: 10,
      y: 20,
      width: 320,
      height: 240
    }
  ]
};

// A real, decodable 1x1 PNG so the browser actually paints the mirror.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64"
);

const labs: LabStatus[] = [
  { id: "winapps", label: "Windows Apps Lab", summary: "Read-only mirror of visible desktop applications on this Windows host.", state: "ready", provider: "native-windows", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "windows", label: "Windows Lab", summary: "Windows VM", state: "needs-setup", provider: "wsl2", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "source", label: "Source Lab", summary: "Local source analysis", state: "ready", provider: "native-python", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "macos", label: "macOS Lab", summary: "Native Xcode Simulator", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "ios", label: "iOS Lab", summary: "iOS Simulator", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "android", label: "Android Lab", summary: "Android analysis", state: "needs-setup", provider: "wsl2", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "linux", label: "Linux Lab", summary: "Linux VM", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true }
];

async function mockApi(page: Page, os: "windows" | "linux" = "windows") {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/host") body = {
      host: {
        os, osPretty: os === "windows" ? "Windows" : "Linux", arch: "x86_64", hostname: "test-host",
        cpus: 8, memory: 16 * 1024 ** 3, disk: { free: 100 * 1024 ** 3, total: 500 * 1024 ** 3 },
        kvm: { present: os === "linux", usable: os === "linux" },
        wsl: { guest: false, distributions: os === "windows" ? ["Ubuntu"] : [] },
        runtime: null, xcode: null, python: "3.12", root: "/tmp/os-lab", tools: [], providers: []
      },
      labs
    };
    else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/labs/winapps/apps") body = winapps;
    else if (path === "/api/labs/winapps/config") body = { lab: "winapps", path: "config.env", exists: true, fields: [], profiles: [], backups: [], endpoints: [] };
    else if (path === "/api/labs/winapps/monitor") body = { lab: "winapps", state: "stopped", containers: [] };
    await route.fulfill({ json: body });
  });
}

test("the Windows Apps Lab mirrors one real window without offering control", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: PNG_1X1
  }));

  await page.goto("/labs/winapps/");
  await expect(page.getByRole("heading", { name: "Window mirror" })).toBeVisible();
  await expect(page.locator("select#winapps-window")).toContainText("Notepad");
  await expect(page.getByText("320×240")).toBeVisible();
  const mirror = page.locator("img[alt='Mirror of Notepad']");
  // Painted at the window's own 4:3 shape, not collapsed to an empty box.
  await expect(mirror).toBeVisible();
  const box = await mirror.boundingBox();
  expect(box!.height).toBeGreaterThan(100);
  expect(box!.width / box!.height).toBeCloseTo(320 / 240, 1);
  await expect(page.getByText("Elevated")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Arm control" })).toHaveCount(0);
});

test("an elevated window is marked instead of silently failing", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps", (route) => route.fulfill({
    json: { ...winapps, windows: [{ ...winapps.windows[0], elevated: true }] }
  }));
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 400,
    json: { error: "Could not capture that window; try another application window" }
  }));

  await page.goto("/labs/winapps/");
  await expect(page.getByText("Elevated")).toBeVisible();
  await expect(page.getByText("Could not capture that window; try another application window")).toBeVisible();
});

test("the panel reports an unavailable native mirror", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps", (route) => route.fulfill({
    json: { available: false, reason: "Native Windows app mirror needs a Windows host", windows: [] }
  }));
  await page.goto("/labs/winapps/");
  await expect(page.getByText("Native Windows app mirror needs a Windows host")).toBeVisible();
});

test("non-Windows hosts never query the Windows app mirror", async ({ page }) => {
  const requests: string[] = [];
  await mockApi(page, "linux");
  await page.route("**/api/labs/winapps/apps", (route) => {
    requests.push(new URL(route.request().url()).pathname);
    return route.fulfill({ json: { available: false, reason: "Windows only", windows: [] } });
  });

  await page.goto("/labs/winapps/");
  await expect(page.getByRole("heading", { name: "Window mirror" })).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("a restricted window is listed but disabled and never captured", async ({ page }) => {
  await mockApi(page);
  const captured: string[] = [];
  await page.route("**/api/labs/winapps/apps", (route) => route.fulfill({
    json: {
      ...winapps,
      windows: [
        { ...winapps.windows[0], windowId: 200, app: "1Password", title: "(restricted)", restricted: true, reason: "password-manager" },
        { ...winapps.windows[0], restricted: false, reason: null }
      ]
    }
  }));
  await page.route("**/api/labs/winapps/apps/*/screenshot", (route) => {
    captured.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 });
  });

  await page.goto("/labs/winapps/");
  await expect(page.locator("select#winapps-window option", { hasText: "1Password" })).toBeDisabled();
  await expect(page.getByText("Some windows are restricted and cannot be mirrored.")).toBeVisible();
  await expect(page.locator("img[alt='Mirror of Notepad']")).toBeVisible();
  expect(captured.length).toBeGreaterThan(0);
  expect(captured.every((path) => path.includes("/100/"))).toBe(true);
});

test("when every window is restricted the panel explains it instead of spinning", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps", (route) => route.fulfill({
    json: {
      ...winapps,
      windows: [{ ...winapps.windows[0], windowId: 200, app: "1Password", title: "(restricted)", restricted: true, reason: "password-manager" }]
    }
  }));
  await page.goto("/labs/winapps/");
  await expect(page.getByText("Some windows are restricted and cannot be mirrored.")).toBeVisible();
  await expect(page.locator("[aria-busy='true']")).toHaveCount(0);
  await expect(page.locator("img[alt^='Mirror of']")).toHaveCount(0);
});

test("a window that turns restricted stops being shown and captured", async ({ page }) => {
  await mockApi(page);
  let inventoryCalls = 0;
  const captured: string[] = [];
  await page.route("**/api/labs/winapps/apps", (route) => {
    inventoryCalls += 1;
    const restricted = inventoryCalls > 1;
    return route.fulfill({
      json: { ...winapps, windows: [{ ...winapps.windows[0], restricted, reason: restricted ? "private-window" : null, title: restricted ? "(restricted)" : "Fixture - Notepad" }] }
    });
  });
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => {
    captured.push("hit");
    return route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 });
  });
  await page.goto("/labs/winapps/");
  await expect(page.locator("img[alt='Mirror of Notepad']")).toBeVisible();
  await expect(page.locator("img[alt^='Mirror of']")).toHaveCount(0, { timeout: 10000 });
  const settled = captured.length;
  await page.waitForTimeout(4000);
  expect(captured.length).toBe(settled);
});

test("switching away from a restricted window clears its image before the next capture arrives", async ({ page }) => {
  await mockApi(page);
  let inventoryCalls = 0;
  await page.route("**/api/labs/winapps/apps", (route) => {
    inventoryCalls += 1;
    const flipped = inventoryCalls > 1;
    return route.fulfill({
      json: {
        ...winapps,
        windows: [
          { ...winapps.windows[0], restricted: flipped, reason: flipped ? "private-window" : null, title: flipped ? "(restricted)" : "Fixture - Notepad" },
          { ...winapps.windows[0], windowId: 101, app: "Calc", title: "Calculator" }
        ]
      }
    });
  });
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 }));
  await page.route("**/api/labs/winapps/apps/101/screenshot", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 6000));
    await route.fulfill({ status: 200, contentType: "image/png", body: PNG_1X1 }).catch(() => undefined);
  });
  await page.goto("/labs/winapps/");
  await expect(page.locator("img[alt='Mirror of Notepad']")).toBeVisible();
  await expect(page.locator("img[alt^='Mirror of']")).toHaveCount(0, { timeout: 10000 });
  await expect(page.locator("img[alt='Mirror of Calc']")).toBeVisible({ timeout: 15000 });
});
