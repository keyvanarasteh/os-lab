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
