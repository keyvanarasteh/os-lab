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
      height: 240,
      dpi: 144
    }
  ]
};

// A real, decodable 1x1 PNG so the browser actually paints the mirror.
const PNG_1X1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64"
);

const labs: LabStatus[] = [
  { id: "winapps", label: "Windows Apps Lab", summary: "Local Windows app mirror with guarded UI Automation and input.", state: "ready", provider: "native-windows", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "windows", label: "Windows Lab", summary: "Windows VM", state: "needs-setup", provider: "wsl2", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "source", label: "Source Lab", summary: "Local source analysis", state: "ready", provider: "native-python", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "macos", label: "macOS Lab", summary: "Native Xcode Simulator", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "ios", label: "iOS Lab", summary: "iOS Simulator", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "android", label: "Android Lab", summary: "Android analysis", state: "needs-setup", provider: "wsl2", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "linux", label: "Linux Lab", summary: "Linux VM", state: "unavailable", provider: null, reasons: [], requirements: [], notes: [], actions: [], installed: true }
];

async function mockApi(page: Page, os: "windows" | "linux" = "windows") {
  const controlState = {
    armed: false,
    owner: null as string | null,
    expiresInSec: 0,
    recentActions: [] as { time: number; kind: string; action?: string; app?: string; ok?: boolean }[]
  };
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
    else if (path === "/api/labs/winapps/control") {
      if (route.request().method() === "POST") {
        const request = route.request().postDataJSON() as { armed: boolean; owner: string };
        Object.assign(controlState, request.armed
          ? { armed: true, owner: request.owner, expiresInSec: 600 }
          : { armed: false, owner: null, expiresInSec: 0 });
        controlState.recentActions.push({
          time: Date.now() / 1000, kind: request.armed ? "arm" : "disarm", ok: true
        });
      }
      body = controlState;
    }
    else if (path === "/api/labs/winapps/apps/100/elements") body = {
      windowId: 100, app: "Notepad", bounds: { x: 10, y: 20, width: 320, height: 240 },
      revision: "rev-1", engine: "uia", trimmed: false,
      elements: [{ elementId: "save-button", role: "Button", label: "Save", x: 40, y: 20, w: 80, h: 24, enabled: true, focused: false }],
      diff: { added: [], changed: [], removed: [] }
    };
    else if (path === "/api/labs/winapps/apps/100/search") body = {
      windowId: 100, app: "Notepad", revision: "rev-1", engine: "uia", query: "save", count: 1,
      hits: [{ elementId: "save-button", role: "Button", label: "Save", x: 40, y: 20, w: 80, h: 24, enabled: true, focused: false }]
    };
    else if (path === "/api/labs/winapps/click") body = { ok: true, actionSent: true, windowId: 100, x: 80, y: 32 };
    else if (path === "/api/labs/winapps/input") body = { ok: true, actionSent: true, windowId: 100, kind: "type", textLength: 5 };
    else if (path === "/api/labs/winapps/stop") {
      Object.assign(controlState, { armed: false, owner: null, expiresInSec: 0 });
      controlState.recentActions.push({ time: Date.now() / 1000, kind: "panic-stop", ok: true });
      body = { ok: true, disarmed: true };
    }
    else if (path === "/api/labs/winapps/config") body = { lab: "winapps", path: "config.env", exists: true, fields: [], profiles: [], backups: [], endpoints: [] };
    else if (path === "/api/labs/winapps/monitor") body = { lab: "winapps", state: "stopped", containers: [] };
    await route.fulfill({ json: body });
  });
  return controlState;
}

test("the Windows Apps Lab mirrors a real window and exposes UI Automation controls", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: PNG_1X1
  }));
  const streamBody = Buffer.concat([
    Buffer.from(`--frame\r\nContent-Type: image/png\r\nContent-Length: ${PNG_1X1.length}\r\n\r\n`),
    PNG_1X1,
    Buffer.from("\r\n")
  ]);
  await page.route("**/api/labs/winapps/apps/100/stream?fps=*", (route) => route.fulfill({
    status: 200,
    contentType: "multipart/x-mixed-replace; boundary=frame",
    body: streamBody
  }));

  await page.goto("/labs/winapps/");
  await expect(page.getByText("App mirror")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Window" })).toContainText("Notepad");
  await expect(page.getByText("320×240")).toBeVisible();
  const mirror = page.locator("img[alt='Mirror of Notepad']");
  // Painted at the window's own 4:3 shape, not collapsed to an empty box.
  await expect(mirror).toBeVisible();
  const box = await mirror.boundingBox();
  expect(box!.height).toBeGreaterThan(100);
  expect(box!.width / box!.height).toBeCloseTo(320 / 240, 1);
  await expect(page.getByText("Elevated")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Arm control" })).toBeVisible();
});

test("UIA hotspots and keyboard input require preview, arm and explicit confirmation", async ({ page }) => {
  const actions: { path: string; body: Record<string, unknown> }[] = [];
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 200, contentType: "image/png", body: PNG_1X1
  }));
  await page.route("**/api/labs/winapps/apps/100/stream?fps=*", (route) => route.fulfill({
    status: 200,
    contentType: "multipart/x-mixed-replace; boundary=frame",
    body: Buffer.concat([
      Buffer.from(`--frame\r\nContent-Type: image/png\r\nContent-Length: ${PNG_1X1.length}\r\n\r\n`),
      PNG_1X1,
      Buffer.from("\r\n")
    ])
  }));
  await page.route("**/api/labs/winapps/click", async (route) => {
    actions.push({ path: "click", body: route.request().postDataJSON() as Record<string, unknown> });
    await route.fulfill({ json: { ok: true, actionSent: true, windowId: 100, x: 80, y: 32 } });
  });
  await page.route("**/api/labs/winapps/input", async (route) => {
    actions.push({ path: "input", body: route.request().postDataJSON() as Record<string, unknown> });
    await route.fulfill({ json: { ok: true, actionSent: true, windowId: 100, kind: "type", textLength: 5 } });
  });

  await page.goto("/labs/winapps/");
  await page.getByRole("button", { name: "Elements" }).click();
  await page.getByRole("textbox", { name: "Search elements" }).fill("save");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("1 matches")).toBeVisible();
  const hotspot = page.getByRole("button", { name: "Button: Save" });
  await expect(hotspot).toBeVisible();
  await hotspot.click();
  await expect(page.getByRole("dialog")).toContainText("Click UI element");
  await expect(page.getByRole("button", { name: "Confirm and send" })).toBeDisabled();
  await expect(page.getByText("Arm control before confirming this action.")).toBeVisible();
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Arm control" }).click();
  await expect(page.getByRole("button", { name: "Disarm control" })).toBeVisible();
  await hotspot.click();
  await page.getByRole("button", { name: "Confirm and send" }).click();
  await expect.poll(() => actions.length).toBe(1);
  expect(actions[0]).toMatchObject({ path: "click", body: { confirm: true, owner: expect.any(String), windowId: 100 } });

  await page.getByRole("textbox", { name: "Text to type" }).fill("hello");
  await page.getByRole("button", { name: "Preview text" }).click();
  await expect(page.getByRole("dialog")).toContainText("hello");
  await expect.poll(() => actions.length).toBe(1);
  await page.getByRole("button", { name: "Confirm and send" }).click();
  await expect.poll(() => actions.length).toBe(2);
  expect(actions[1]).toMatchObject({ path: "input", body: { confirm: true, kind: "type", text: "hello" } });
});

test("double-click and scroll use confirmed input actions and refresh UIA plus audit state", async ({ page }) => {
  const controlState = await mockApi(page);
  const actions: Record<string, unknown>[] = [];
  let elementsReads = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/labs/winapps/apps/100/elements") elementsReads++;
  });
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 200, contentType: "image/png", body: PNG_1X1
  }));
  await page.route("**/api/labs/winapps/apps/100/stream?fps=*", (route) => route.fulfill({
    status: 200,
    contentType: "multipart/x-mixed-replace; boundary=frame",
    body: Buffer.concat([
      Buffer.from(`--frame\r\nContent-Type: image/png\r\nContent-Length: ${PNG_1X1.length}\r\n\r\n`),
      PNG_1X1,
      Buffer.from("\r\n")
    ])
  }));
  await page.route("**/api/labs/winapps/input", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    actions.push(body);
    controlState.recentActions.push({
      time: Date.now() / 1000, kind: "input", action: String(body.kind), app: "Notepad", ok: true
    });
    await route.fulfill({ json: { ok: true, actionSent: true, ...body, textLength: 0 } });
  });

  await page.goto("/labs/winapps/");
  await page.getByRole("button", { name: "Elements" }).click();
  await expect(page.getByRole("button", { name: "Button: Save" })).toBeVisible();
  await page.getByRole("button", { name: "Arm control" }).click();
  await expect(page.getByRole("button", { name: "Disarm control" })).toBeVisible();
  await page.getByRole("combobox", { name: "Mouse action" }).selectOption("double_click");
  await page.getByRole("button", { name: "Button: Save" }).click();
  await expect(page.getByRole("dialog")).toContainText("Double-click UI element");
  const firstElementsRead = elementsReads;
  await page.getByRole("button", { name: "Confirm and send" }).click();
  await expect.poll(() => actions.length).toBe(1);
  expect(actions[0]).toMatchObject({
    kind: "double_click", x: 80, y: 32, confirm: true, owner: expect.any(String), windowId: 100
  });
  await expect.poll(() => elementsReads).toBeGreaterThan(firstElementsRead);
  await expect(page.getByText("Double-click · Notepad")).toBeVisible();

  await page.getByRole("combobox", { name: "Mouse action" }).selectOption("scroll_up");
  await page.locator(".cursor-crosshair").click({ position: { x: 50, y: 50 } });
  await expect(page.getByRole("dialog")).toContainText("Scroll at");
  await page.getByRole("button", { name: "Confirm and send" }).click();
  await expect.poll(() => actions.length).toBe(2);
  expect(actions[1]).toMatchObject({ kind: "scroll", deltaX: 0, deltaY: 120, confirm: true });
  await expect(page.getByText("Scroll · Notepad")).toBeVisible();
});

test("the mirror can be dragged, resized, docked, hidden and reopened", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/labs/winapps/apps/100/screenshot", (route) => route.fulfill({
    status: 200,
    contentType: "image/png",
    body: PNG_1X1
  }));
  await page.route("**/api/labs/winapps/apps/100/stream?fps=*", (route) => route.fulfill({
    status: 200,
    contentType: "multipart/x-mixed-replace; boundary=frame",
    body: Buffer.concat([
      Buffer.from(`--frame\r\nContent-Type: image/png\r\nContent-Length: ${PNG_1X1.length}\r\n\r\n`),
      PNG_1X1,
      Buffer.from("\r\n")
    ])
  }));

  await page.goto("/labs/winapps/");
  const panel = page.locator(".iux-card.fixed");
  await expect(panel).toBeVisible();
  const beforeDrag = await panel.boundingBox();
  const header = panel.locator(":scope > div").first();
  const headerBox = await header.boundingBox();
  await page.mouse.move(headerBox!.x + 100, headerBox!.y + 10);
  await page.mouse.down();
  await page.mouse.move(headerBox!.x + 60, headerBox!.y - 10);
  await page.mouse.up();
  const afterDrag = await panel.boundingBox();
  expect(afterDrag!.x).toBeLessThan(beforeDrag!.x - 30);
  expect(afterDrag!.y).toBeLessThan(beforeDrag!.y - 15);

  const beforeResize = await panel.boundingBox();
  const resizeHandle = panel.locator(".cursor-nwse-resize");
  const handleBox = await resizeHandle.boundingBox();
  await page.mouse.move(handleBox!.x + 4, handleBox!.y + 4);
  await page.mouse.down();
  await page.mouse.move(handleBox!.x + 44, handleBox!.y + 34);
  await page.mouse.up();
  const afterResize = await panel.boundingBox();
  expect(afterResize!.width).toBeGreaterThan(beforeResize!.width + 20);
  expect(afterResize!.height).toBeGreaterThan(beforeResize!.height + 15);

  await page.getByRole("button", { name: "Dock the panel" }).click();
  await expect(page.getByRole("button", { name: "Float the panel" })).toBeVisible();
  await page.getByRole("button", { name: "Hide the app mirror" }).click();
  await page.getByRole("button", { name: "Show the app mirror" }).click();
  await expect(page.getByText("App mirror")).toBeVisible();
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
