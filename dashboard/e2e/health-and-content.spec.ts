import { expect, test, type Page } from "@playwright/test";
import type { LabStatus } from "../src/lib/api";

const labs: LabStatus[] = [
  { id: "source", label: "Source Lab", summary: "Local source analysis", state: "ready", provider: "native-python", reasons: [],
    requirements: [{ id: "python", label: "Python 3.11+", found: true, required: true, hint: "" },
                   { id: "playwright", label: "Playwright", found: false, required: false, hint: "Optional browser collector" }],
    notes: [], actions: [{ id: "doctor", label: "Doctor", description: "Check tools", privileged: false },
                         { id: "setup", label: "Setup", description: "Create storage", privileged: false }], installed: true },
  { id: "macos", label: "macOS Lab", summary: "Native Xcode Simulator", state: "ready", provider: "native-macos", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "ios", label: "iOS Lab", summary: "iOS Simulator", state: "ready", provider: "native-macos", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "android", label: "Android Lab", summary: "Android analysis", state: "needs-setup", provider: "macos-containers", reasons: ["Missing container engine"], requirements: [], notes: [], actions: [], installed: true },
  { id: "windows", label: "Windows Lab", summary: "Windows VM", state: "unavailable", provider: null, reasons: ["Needs Linux/KVM"], requirements: [], notes: [], actions: [], installed: true },
  { id: "linux", label: "Linux Lab", summary: "Linux VM", state: "unavailable", provider: null, reasons: ["Needs Linux/KVM"], requirements: [], notes: [], actions: [], installed: true }
];
const content = {
  installed: false, version: "0.2.5", sequence: 1, hooks: false, updatedAt: null, fileCount: 0,
  latest: { version: "content-149", sequence: 149, files: { data: 10, hooks: 0 } },
  checkedAt: Date.now() / 1000, offline: false, source: "bundled", updateAvailable: true
};

async function mockApi(page: Page, os: "macos" | "windows" | "linux" = "macos", labPatch: Record<string, Partial<LabStatus>> = {}) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/host") body = {
      host: {
        os, osPretty: os === "macos" ? "macOS" : os === "windows" ? "Windows" : "Linux", arch: "x86_64",
        hostname: "test-host", cpus: 8, memory: 16 * 1024 ** 3, disk: { free: 100 * 1024 ** 3, total: 500 * 1024 ** 3 },
        kvm: { present: os === "linux", usable: os === "linux" }, wsl: { guest: false, distributions: os === "windows" ? ["Ubuntu"] : [] },
        runtime: null, xcode: os === "macos" ? { installed: true, iosRuntime: true, iosDevice: true, developerDir: "/Volumes/Apps/Applications/Xcode.app/Contents/Developer", xcodeApp: "/Volumes/Apps/Applications/Xcode.app" } : null,
        python: "3.12", root: "/tmp/os-lab", tools: [], providers: []
      },
      labs: (os === "macos" ? labs : labs.map((lab) => lab.id === "source" ? lab : ({ ...lab,
        state: (lab.id === os ? "ready" : lab.id === "macos" ? "unavailable" : "needs-setup") as LabStatus["state"],
        provider: lab.id === "macos" ? null : os === "windows" ? "wsl2" : "linux-containers"
      }))).map((lab) => ({ ...lab, ...labPatch[lab.id] }))
    };
    else if (path === "/api/health") body = { status: "ok", version: "0.2.5", console: true };
    else if (path === "/api/capabilities") body = {
      platforms: ["macos", "windows", "linux"].map((id) => ({ id, label: id, installer: "test installer", engine: "test engine" })),
      groups: [{ id: "labs", title: "Labs", description: "Platform support", items: [{
        id: "lab-ios", lab: "ios", title: "iOS Lab", summary: "iOS tooling",
        support: { macos: { level: "full", note: "Native Xcode" }, windows: { level: "partial", note: "WSL2" }, linux: { level: "partial", note: "KVM" } }
      }] }]
    };
    else if (/^\/api\/labs\/[a-z]+\/config$/.test(path)) body = { lab: path.split("/")[3], path: "config.env", exists: true, fields: [], profiles: [], backups: [], endpoints: [{ label: "Appium", address: "http://127.0.0.1:4723/" }] };
    else if (/^\/api\/labs\/[a-z]+\/monitor$/.test(path)) body = { lab: path.split("/")[3], state: "stopped", containers: [] };
    else if (path === "/api/content/status" || path === "/api/content/check") body = content;
    else if (path === "/api/content/update") body = { ...content, installed: true, version: "content-149", sequence: 149, updateAvailable: false };
    else if (path === "/api/reports") body = { reports: [] };
    else if (path === "/api/apks") body = { apks: [] };
    else if (path === "/api/hooks") body = { hooks: [] };
    else if (path === "/api/devices") body = { devices: "List of devices attached\n" };
    else if (path === "/api/labs/ios/devices") body = { available: false, reason: "The device tooling is unavailable in this mock.", devices: [] };
    else if (path === "/api/cleanup/volumes") body = {
      platform: "macos", threshold: 0.9, homeVolume: "/", warnings: [], error: null,
      volumes: [{ mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs", kind: "root", totalBytes: 500 * 1024 ** 3, freeBytes: 100 * 1024 ** 3, usedBytes: 400 * 1024 ** 3, usage: 0.8, purgeableBytes: null, isHome: true, pressure: "ok", error: null }]
    };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    await route.fulfill({ json: body });
  });
}

test("content card checks and installs while keeping advanced options available", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const card = page.locator("#content");
  await expect(card).toBeVisible();
  await expect(card.getByText("A newer content pack is available.").first()).toBeVisible();
  await card.getByRole("button", { name: "Install update" }).click();
  await expect(card.getByText("Content updated.")).toBeVisible();
  await card.getByText("Advanced options").click();
  await expect(card.getByText("Include Frida hooks")).toBeVisible();
});

test("Turkish page renders the content card without layout overflow", async ({ page }) => {
  await mockApi(page);
  await page.goto("/tr/");
  await expect(page.locator("html")).toHaveAttribute("lang", "tr");
  await expect(page.locator("#content")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(2);
});

for (const locale of ["ar", "fa"] as const) {
  test(`${locale} content page keeps its right-to-left layout inside the viewport`, async ({ page }) => {
    await mockApi(page);
    await page.goto(`/${locale}/`);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("#content")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(2);
  });
}

for (const os of ["macos", "windows", "linux"] as const) {
  test(`Health shows ${os} live checks and API capability tree`, async ({ page }) => {
    await mockApi(page, os);
    await page.goto("/health/");
    await expect(page.getByRole("heading", { name: "Health check" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What os-lab supports" })).toBeVisible();
    await expect(page.getByRole("tab", { name: new RegExp(os, "i") })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("iOS tooling")).toBeVisible();
    await expect(page.getByRole("link", { name: /setup guide/i })).toBeVisible();
  });
}

for (const [os, hidden, shown] of [
  ["macos", ["windows", "linux"], ["macos", "ios", "android"]],
  ["windows", ["macos"], ["windows", "linux", "android"]],
  ["linux", ["macos"], ["linux", "windows", "android"]]
] as const) {
  test(`${os} host leaves out labs it cannot run`, async ({ page }) => {
    await mockApi(page, os);
    await page.goto("/");
    for (const id of shown) await expect(page.locator(`a[href$="/labs/${id}/"]`).first()).toBeVisible();
    for (const id of hidden) await expect(page.locator(`a[href$="/labs/${id}/"]`)).toHaveCount(0);
    await expect(page.getByText("Labs that do not run on this computer:")).toBeVisible();
    await expect(page.getByRole("link", { name: "See what each platform supports" })).toBeVisible();
  });
}

test("a lab that is missing requirements hides its runtime sections until they are met", async ({ page }) => {
  await mockApi(page);
  await page.goto("/labs/android/");
  await expect(page.getByText("Start, stop and the other actions appear once the missing dependencies are installed.")).toBeVisible();
  await expect(page.getByText("Live monitor")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Endpoints" })).toHaveCount(0);
  await page.goto("/labs/ios/");
  await expect(page.getByRole("heading", { name: "Actions" })).toBeVisible();
  await expect(page.getByText("Start, stop and the other actions appear once the missing dependencies are installed.")).toHaveCount(0);
  await expect(page.getByText("Live monitor")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Endpoints" })).not.toBeVisible();
  // Advanced settings opens from the header icon as a modal and closes on Escape.
  await page.getByRole("button", { name: "Advanced settings" }).click();
  await expect(page.getByRole("heading", { name: "Endpoints" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Endpoints" })).toHaveCount(0);
  // The simulator mirror lives in a side panel behind its own header icon.
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"],
    devices: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Shutdown" }], booted: []
  } }));
  await expect(page.getByRole("button", { name: "Attach simulator" })).toHaveCount(0);
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  await expect(page.getByRole("button", { name: "Attach simulator" })).toBeVisible();
});

test("the iOS actions card checks real devices and the frame captures a selected phone", async ({ page }) => {
  await mockApi(page, "macos");
  const udid = "C2AC1E99-DB20-5F29-BC57-4EE540DCFEBA";
  let checked = 0;
  let captured = 0;
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"],
    devices: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Shutdown" }], booted: []
  } }));
  await page.route("**/api/labs/ios/devices", (route) => route.fulfill({ json: {
    available: true, reason: null,
    devices: [{ udid, name: "iPhone 15", osVersion: "17.4", state: "connected",
                paired: true, transport: "localNetwork", lastSeen: "2026-11-15T09:26:00.000Z" }]
  } }));
  await page.route("**/api/labs/ios/devices/check?udid=*", (route) => {
    checked += 1;
    return route.fulfill({ json: { reachable: true, state: "connected", name: "iPhone 15", osVersion: "17.4", developerMode: true } });
  });
  await page.route("**/api/labs/ios/screenshot?udid=*", (route) => {
    captured += 1;
    return route.fulfill({ body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aXcAAAAASUVORK5CYII=", "base64"), contentType: "image/png" });
  });
  await page.goto("/labs/ios/");
  const actions = page.getByRole("heading", { name: "Actions" }).locator("xpath=ancestor::section[1]");
  await expect(actions.getByRole("heading", { name: "Real devices" })).toBeVisible();
  await expect(actions.getByText("iPhone 15")).toBeVisible();
  await expect(actions.getByText("Connected", { exact: true })).toBeVisible();
  await expect(actions.getByText("Real-device control needs Developer Mode and a signed WebDriverAgent.")).toHaveCount(0);
  expect(checked).toBeGreaterThan(0);
  await actions.getByRole("button", { name: "Open iPhone 15 in simulator frame" }).click();
  await expect(page.getByRole("complementary", { name: "Simulator" })).toBeVisible();
  // The Xcode line names the real install location, not an assumed path.
  await expect(page.getByText("/Volumes/Apps/Applications/Xcode.app", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Host details" }).click();
  await expect(page.getByText("/Volumes/Apps/Applications/Xcode.app", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Device" })).toHaveValue(`real:${udid}`);
  await expect(page.getByRole("img", { name: "Real device screen" })).toBeVisible();
  expect(captured).toBeGreaterThan(0);
  await expect(page.getByText("System disk is running low. Simulator device data can move to another volume from the Cleanup Lab.")).toHaveCount(0);
});

test("running simulator cards open the chosen simulator frame", async ({ page }) => {
  await mockApi(page, "macos");
  const booted = [
    { udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Booted" },
    { udid: "UDID-2", name: "iPhone 18", runtime: "iOS 27.2", state: "Booted" }
  ];
  let capturedDevice = "";
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"], devices: booted, booted
  } }));
  await page.route("**/api/labs/ios/screenshot?device=*", (route) => {
    capturedDevice = new URL(route.request().url()).searchParams.get("device") ?? "";
    return route.fulfill({ body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aXcAAAAASUVORK5CYII=", "base64"), contentType: "image/png" });
  });
  await page.goto("/labs/ios/");
  const actions = page.getByRole("heading", { name: "Actions" }).locator("xpath=ancestor::section[1]");
  await expect(actions.getByRole("heading", { name: "Running simulators" })).toBeVisible();
  await actions.getByRole("button", { name: "Open iPhone 18 in simulator frame" }).click();
  await expect(page.getByRole("combobox", { name: "Device" })).toHaveValue("sim:UDID-2");
  await expect(page.getByRole("img", { name: "Simulator screen" })).toBeVisible();
  expect(capturedDevice).toBe("UDID-2");
});

test("the real-device setup warning appears when Developer Mode is off", async ({ page }) => {
  await mockApi(page, "macos");
  const udid = "C2AC1E99-DB20-5F29-BC57-4EE540DCFEBA";
  await page.route("**/api/labs/ios/devices", (route) => route.fulfill({ json: {
    available: true, reason: null, devices: [{ udid, name: "iPhone 15", osVersion: "17.4", state: "connected" }]
  } }));
  await page.route("**/api/labs/ios/devices/check?udid=*", (route) => route.fulfill({ json: {
    reachable: true, state: "connected", developerMode: false
  } }));
  await page.goto("/labs/ios/");
  await expect(page.getByText("Real-device control needs Developer Mode and a signed WebDriverAgent.")).toBeVisible();
});

test("the simulator panel docks on desktop and overlays a phone", async ({ page }) => {
  await mockApi(page, "macos", { ios: { actions: [
    { id: "appium-start", label: "Start Appium", description: "Start Appium", privileged: false },
    { id: "appium-stop", label: "Stop Appium", description: "Stop Appium", privileged: false }
  ] } });
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"], devices: [], booted: []
  } }));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/labs/ios/");
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  const appiumActions = page.getByRole("group", { name: "Appium" });
  const actionCard = appiumActions.locator("xpath=parent::div");
  const stopButton = appiumActions.getByRole("button", { name: "Stop" });
  await expect(stopButton).toBeVisible();
  const cardBounds = await actionCard.boundingBox();
  const stopBounds = await stopButton.boundingBox();
  expect({ cardBounds, stopBounds, fits: !!cardBounds && !!stopBounds && stopBounds.x + stopBounds.width <= cardBounds.x + cardBounds.width }).toMatchObject({ fits: true });
  const panel = page.getByRole("complementary", { name: "Simulator" });
  const desktop = await page.evaluate(() => {
    const main = document.querySelector("main")!.getBoundingClientRect();
    const aside = document.querySelector('aside[aria-label="Simulator"]')!.getBoundingClientRect();
    return { mainRight: main.right, panelLeft: aside.left, position: getComputedStyle(document.querySelector('aside[aria-label="Simulator"]')!).position };
  });
  expect(desktop.position).toBe("sticky");
  expect(desktop.mainRight).toBeLessThanOrEqual(desktop.panelLeft + 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toBeVisible();
  await expect(panel).toHaveCSS("position", "fixed");
  await expect(panel).toHaveCSS("width", "390px");
});

test("an unreachable real device stays faded and has an offline frame", async ({ page }) => {
  await mockApi(page, "macos");
  const udid = "C2AC1E99-DB20-5F29-BC57-4EE540DCFEBA";
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"], devices: [], booted: []
  } }));
  await page.route("**/api/labs/ios/devices", (route) => route.fulfill({ json: {
    available: true, reason: null, devices: [{ udid, name: "iPhone 15", osVersion: "17.4", state: "unavailable" }]
  } }));
  await page.route("**/api/labs/ios/devices/check?udid=*", (route) => route.fulfill({ json: {
    reachable: false, reason: "Device did not answer"
  } }));
  let captured = 0;
  await page.route("**/api/labs/ios/screenshot?udid=*", (route) => { captured += 1; return route.fulfill({ status: 503 }); });
  await page.goto("/labs/ios/");
  await expect(page.getByText("Offline", { exact: true })).toBeVisible();
  await expect(page.getByText("Device did not answer", { exact: true })).not.toBeVisible();
  await page.getByText("Device details").click();
  await expect(page.getByText("Device did not answer", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  await page.getByRole("combobox", { name: "Device" }).selectOption(`real:${udid}`);
  await expect(page.getByTestId("ios-device-screen").getByText("Offline", { exact: true })).toBeVisible();
  expect(captured).toBe(0);
});

test("host pressure without a running simulator does not open the watchdog alert", async ({ page }) => {
  await mockApi(page, "macos");
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"], devices: [], booted: []
  } }));
  await page.route("**/api/labs/ios/resources", (route) => route.fulfill({ json: {
    available: true, reason: null,
    cpu: { percent: 100, warn: 85, critical: 95 },
    memory: { totalBytes: 16 * 1024 ** 3, usedBytes: 15 * 1024 ** 3, percent: 96, warn: 85, critical: 92 },
    simulator: { running: false, cpuPercent: 0, rssBytes: null }
  } }));
  await page.goto("/labs/ios/");
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  await page.getByRole("button", { name: "Host details" }).click();
  await expect(page.getByText("100%", { exact: true })).toBeVisible();
  await page.waitForTimeout(11000);
  await expect(page.getByText("System resources are running low")).toHaveCount(0);
});

test("the resource watchdog opens the alert and can stop all simulators", async ({ page }) => {
  await mockApi(page, "macos");
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"],
    devices: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Booted" }],
    booted: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Booted" }]
  } }));
  await page.route("**/api/labs/ios/resources", (route) => route.fulfill({ json: {
    available: true, reason: null,
    cpu: { percent: 40.0, warn: 85, critical: 95 },
    memory: { totalBytes: 16 * 1024 ** 3, usedBytes: Math.round(15.5 * 1024 ** 3), percent: 96.9, warn: 85, critical: 92 },
    simulator: { running: true, cpuPercent: 55.0, rssBytes: 3 * 1024 ** 3 }
  } }));
  await page.route("**/api/labs/plan", (route) => route.fulfill({ json: {
    plan: { id: "p1", lab: "ios", action: "stop", display: "bash stop", effects: [], privileged: false, provider: "native-macos", timeoutSec: 300, runnable: true },
    token: "tok-1"
  } }));
  await page.route("**/api/labs/start", (route) => route.fulfill({ json: { id: "j1", kind: "run", state: "running", request: {}, progress: null, result: null, error: null } }));
  await page.goto("/labs/ios/");
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  await page.getByRole("button", { name: "Host details" }).click();
  // Two critical polls open the alert; the meters show the pressure first.
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("System resources are running low")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("15.5 GiB / 16.0 GiB")).toBeVisible();
  await dialog.getByRole("button", { name: "Stop all simulators" }).click();
  await expect(page.getByText("Simulators stopped.")).toBeVisible();
  // The drawer itself is role=dialog; assert the alert's own content is gone.
  await expect(page.getByText("System resources are running low")).toHaveCount(0);
});

test("the armed auto-stop fires without the alert", async ({ page }) => {
  await mockApi(page, "macos");
  await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
    available: true, configuredDevice: "", runtimes: ["iOS 27.2"],
    devices: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Booted" }],
    booted: [{ udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: "Booted" }]
  } }));
  await page.route("**/api/labs/ios/resources", (route) => route.fulfill({ json: {
    available: true, reason: null,
    cpu: { percent: 30.0, warn: 85, critical: 95 },
    memory: { totalBytes: 16 * 1024 ** 3, usedBytes: Math.round(15.6 * 1024 ** 3), percent: 97.5, warn: 85, critical: 92 },
    simulator: { running: true, cpuPercent: 70.0, rssBytes: 3 * 1024 ** 3 }
  } }));
  await page.route("**/api/labs/plan", (route) => route.fulfill({ json: {
    plan: { id: "p1", lab: "ios", action: "stop", display: "bash stop", effects: [], privileged: false, provider: "native-macos", timeoutSec: 300, runnable: true },
    token: "tok-1"
  } }));
  await page.route("**/api/labs/start", (route) => route.fulfill({ json: { id: "j1", kind: "run", state: "running", request: {}, progress: null, result: null, error: null } }));
  await page.goto("/labs/ios/");
  await page.evaluate(() => window.localStorage.setItem("oslab.ios.autostop", "1"));
  await page.reload();
  await page.getByRole("button", { name: "Simulator", exact: true }).click();
  await expect(page.getByText("Simulators were stopped automatically to free memory and CPU.")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("System resources are running low")).toHaveCount(0);
});

for (const booted of [false, true]) {
  test(`the low-disk nudge ${booted ? "appears for a booted simulator" : "stays hidden without a booted simulator"}`, async ({ page }) => {
    await mockApi(page, "macos");
    const device = { udid: "UDID-1", name: "iPhone 17", runtime: "iOS 27.2", state: booted ? "Booted" : "Shutdown" };
    await page.route("**/api/labs/ios/simulator", (route) => route.fulfill({ json: {
      available: true, configuredDevice: "", runtimes: ["iOS 27.2"],
      devices: [device], booted: booted ? [device] : []
    } }));
    await page.route("**/api/cleanup/volumes", (route) => route.fulfill({ json: {
      platform: "macos", threshold: 0.9, homeVolume: "/", warnings: ["Volume / is running low on free space."], error: null,
      volumes: [{ mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs", kind: "root", totalBytes: 500 * 1024 ** 3, freeBytes: 8 * 1024 ** 3, usedBytes: 492 * 1024 ** 3, usage: 0.98, purgeableBytes: null, isHome: true, pressure: "warning", error: null }]
    } }));
    await page.goto("/labs/ios/");
    await page.getByRole("button", { name: "Simulator", exact: true }).click();
    const nudge = page.getByText("System disk is running low. Simulator device data can move to another volume from the Cleanup Lab.");
    if (booted) {
      await expect(nudge).toBeVisible();
      await expect(page.getByRole("link", { name: "Open Relocation" })).toBeVisible();
    } else {
      await expect(nudge).toHaveCount(0);
    }
  });
}

test("setup is offered only when a required dependency is missing", async ({ page }) => {
  const setup = { id: "setup", label: "Setup", description: "Install prerequisites", privileged: false };
  const found = { id: "runtime", label: "Container runtime", found: true, required: true, hint: "" };
  await mockApi(page, "macos", { ios: { actions: [setup], requirements: [found] } });
  await page.goto("/labs/ios/");
  await expect(page.getByRole("button", { name: "Install dependencies" })).toHaveCount(0);
  // Every requirement is found: the card would only repeat success badges, so it stays hidden.
  await expect(page.getByRole("heading", { name: "Dependencies" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Actions" })).toBeVisible();
});

test("a missing required dependency offers setup", async ({ page }) => {
  const setup = { id: "setup", label: "Setup", description: "Install prerequisites", privileged: false };
  const missing = { id: "runtime", label: "Container runtime", found: false, required: true, hint: "Install it" };
  await mockApi(page, "macos", { ios: { state: "needs-setup", actions: [setup], requirements: [missing] } });
  await page.goto("/labs/ios/");
  await expect(page.getByRole("button", { name: "Install dependencies" })).toBeVisible();
});

test("dependencies that are already found stay out of the card", async ({ page }) => {
  const setup = { id: "setup", label: "Setup", description: "Install prerequisites", privileged: false };
  const found = { id: "runtime", label: "Container runtime", found: true, required: true, hint: "" };
  const missing = { id: "python", label: "Python 3.11+", found: false, required: true, hint: "Install it" };
  await mockApi(page, "macos", { ios: { state: "needs-setup", actions: [setup], requirements: [found, missing] } });
  await page.goto("/labs/ios/");
  await expect(page.getByText("Container runtime")).toHaveCount(0);
  await expect(page.getByText("Python 3.11+")).toBeVisible();
  await expect(page.getByText("1 of 2 found")).toBeVisible();
  await expect(page.getByRole("button", { name: "Install dependencies" })).toBeVisible();
});

test("start and stop actions render as segmented icon controls under one title", async ({ page }) => {
  const action = (id: string, label: string) => ({ id, label, description: `Preview ${id}`, privileged: false });
  await mockApi(page, "linux", {
    android: {
      state: "ready", provider: "linux-containers",
      actions: [action("start", "Start"), action("stop", "Stop"), action("restart", "Restart"),
                action("appium-start", "Start Appium"), action("appium-stop", "Stop Appium")]
    }
  });
  await page.goto("/labs/android/");
  const stack = page.getByRole("group", { name: "Stack" });
  await expect(stack).toBeVisible();
  await expect(stack.getByRole("button")).toHaveCount(3);
  await expect(stack.getByRole("button", { name: "Start", exact: true })).toBeVisible();
  await expect(stack.getByRole("button", { name: "Stop" })).toBeVisible();
  await expect(stack.getByRole("button", { name: "Restart" })).toBeVisible();
  const appium = page.getByRole("group", { name: "Appium" });
  await expect(appium).toBeVisible();
  await expect(appium.getByRole("button", { name: "Start Appium" })).toBeVisible();
  await expect(appium.getByRole("button", { name: "Stop Appium" })).toBeVisible();
});

test("Android run failures are shown next to the action", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/run", (route) => route.fulfill({ status: 400, json: { error: "Target APK is missing" } }));
  await page.goto("/android/workflows/");
  await page.getByRole("button", { name: "Execute Pipeline" }).click();
  await expect(page.getByRole("alert")).toContainText("Target APK is missing");
});

test("every local page type hydrates without a browser error", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const route of [
    "/", "/jobs/", "/contribute/", "/feedback/", "/content/", "/health/", "/legal/",
    "/legal/terms/", "/legal/acceptable-use/", "/legal/privacy/", "/legal/third-party/",
    "/labs/android/", "/labs/ios/", "/labs/windows/", "/labs/linux/", "/labs/macos/",
    "/labs/web/", "/web-lab/",
    "/android/", "/android/providers/", "/android/workflows/", "/android/console/",
    "/android/analytics/", "/android/sitemap/", "/firewall/"
  ]) {
    errors.length = 0;
    const response = await page.goto(route);
    expect(response?.status(), route).toBe(200);
    await expect(page.locator('button[aria-label="Open search"]').first(), route).toBeVisible();
    expect(errors, route).toEqual([]);
  }
});

for (const locale of ["", "/tr"]) {
  test(`legal document links preserve ${locale || "English"} routing`, async ({ page }) => {
    await mockApi(page);
    await page.goto(`${locale}/legal/privacy/`);
    const article = page.locator("article.legal-doc");
    await expect(article.getByRole("link", { name: "Third-Party Notices" })).toHaveAttribute("href", `${locale}/legal/third-party/`);
    await expect(article.getByRole("link", { name: "Terms of Use" })).toHaveAttribute("href", `${locale}/legal/terms/`);
    await expect(page.locator("main nav a[aria-current=page]")).toHaveAttribute("href", `${locale}/legal/privacy/`);
    await article.getByRole("link", { name: "Terms of Use" }).click();
    await expect(page).toHaveURL(new RegExp(`${locale}/legal/terms/$`));
  });
}


test("Source readiness keeps optional browser tooling separate from core setup", async ({ page }) => {
  await mockApi(page, "linux");
  await page.goto("/labs/source/");
  await expect(page.getByRole("heading", { name: "Source Lab", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading", { name: "Source Lab", exact: true })).toHaveCount(0);
  // Found requirements stay out of the card: the summary badge reports them, Playwright is still listed.
  await expect(page.getByText("Python 3.11+", { exact: true })).toHaveCount(0);
  await expect(page.getByText("1 of 2 found")).toBeVisible();
  await expect(page.locator("li").filter({ hasText: "Playwright" }).getByText("optional", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Install dependencies" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Doctor", exact: true })).toBeVisible();
});

test("Source jobs show interrupted recovery without a success badge", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/jobs", route => route.fulfill({ json: { jobs: [{
    id: "source-interrupted", label: "Source Lab · Detect", lab: "source", action: "detect", command: "owned fixture",
    state: "interrupted", startedAt: Date.now() / 1000, finishedAt: Date.now() / 1000,
    exitCode: null, error: "Console stopped before completion", truncated: false, lines: 0
  }] } }));
  await page.route("**/api/jobs/source-interrupted", route => route.fulfill({ json: { logs: [], state: "interrupted" } }));
  await page.goto("/jobs/");
  await expect(page.getByText("interrupted", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Console stopped before completion")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
});

test("Jobs cancellation reports failure and permits retry", async ({ page }) => {
  await mockApi(page);
  let fail = true;
  let cancelled = false;
  const job = { id: "job-ux", label: "Android · Scan", lab: "android", action: "scan", command: "owned fixture",
    state: "running", startedAt: Date.now() / 1000, finishedAt: null, exitCode: null, error: null,
    truncated: false, lines: 1, logs: ["fixture log"] };
  await page.route("**/api/jobs", route => route.fulfill({ json: { jobs: [{ ...job, state: cancelled ? "cancelled" : "running" }] } }));
  await page.route("**/api/jobs/job-ux", route => route.fulfill({ json: { ...job, state: cancelled ? "cancelled" : "running" } }));
  await page.route("**/api/jobs/job-ux/cancel", route => {
    if (fail) return route.fulfill({ status: 500, json: { error: "Cancellation unavailable" } });
    cancelled = true;
    return route.fulfill({ json: { ...job, state: "cancelled" } });
  });
  await page.goto("/jobs/");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Cancellation unavailable");
  await expect(page.getByText("fixture log")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("button", { name: "Cancel", exact: true })).toHaveCount(0);
  await expect(page.getByText("cancelled", { exact: true }).first()).toBeVisible();
});

test("Android Clear keeps logs and reports failed requests", async ({ page }) => {
  await mockApi(page);
  let fail = true;
  let cleared = false;
  await page.route("**/api/logs", route => route.fulfill({ json: { logs: cleared ? [] : ["fixture output"], running: false } }));
  await page.route("**/api/logs/clear", route => {
    if (fail) return route.fulfill({ status: 500, json: { error: "Clear refused" } });
    cleared = true;
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/android/console/");
  await expect(page.getByText("fixture output")).toBeVisible();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Clear refused");
  await expect(page.getByText("fixture output")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByText("Logs cleared.")).toBeVisible();
});

test("Health platform tabs support arrow keys and panel linkage", async ({ page }) => {
  await mockApi(page);
  await page.goto("/health/");
  const mac = page.getByRole("tab", { name: /macos/i });
  await mac.focus();
  await page.keyboard.press("ArrowRight");
  const windows = page.getByRole("tab", { name: /windows/i });
  await expect(windows).toBeFocused();
  await expect(windows).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel").first()).toHaveAttribute("aria-labelledby", "health-platform-windows");
});

test("Firewall dialogs keep focus inside and return it on Escape", async ({ page }) => {
  await mockApi(page);
  await page.goto("/firewall/");
  const trigger = page.locator("button.fw-cta-lg");
  await trigger.click();
  const contribute = page.locator("dialog.cm");
  await expect(contribute).toBeVisible();
  expect(await contribute.evaluate(element => element.matches(":modal"))).toBe(true);
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest("dialog.cm")))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest("dialog.cm")))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(contribute).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.goto("/firewall/acme-academy/");
  const gaps = page.getByRole("tab", { name: /gaps/i });
  await gaps.focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: /network/i })).toBeFocused();
  await gaps.click();
  await expect(gaps).toHaveAttribute("aria-selected", "true");
  const impact = page.locator("button.fwg-impact").first();
  await impact.click();
  const gapDialog = page.locator("dialog.gm");
  expect(await gapDialog.evaluate(element => element.matches(":modal"))).toBe(true);
  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest("dialog.gm")))).toBe(true);
  await page.mouse.click(2, 2);
  await expect(gapDialog).toHaveCount(0);
  await expect(impact).toBeFocused();
});

test("Contribute copy does not claim success when clipboard fails", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => { throw new Error("denied"); } } });
  });
  await page.goto("/contribute/#todos");
  const copy = page.getByTitle("Copy task reference").first();
  await copy.click();
  await expect(page.getByRole("alert")).toContainText("Clipboard unavailable");
  await expect(copy).not.toContainText("Copied");
  await page.evaluate(() => Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => {} } }));
  await copy.click();
  await expect(copy).toContainText("Copied");
});

test("coarse-pointer shell buttons have 44px targets", async ({ browser }) => {
  test.setTimeout(60_000);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  try {
    const page = await context.newPage();
    await mockApi(page);
    await page.goto("/");
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const menu = page.getByRole("button", { name: "Open navigation" });
    const box = await menu.boundingBox();
    expect(box?.width).toBeGreaterThanOrEqual(44);
    expect(box?.height).toBeGreaterThanOrEqual(44);
    const target = async (selector: string) => {
      const rect = await page.locator(selector).first().boundingBox();
      expect(rect?.width, selector).toBeGreaterThanOrEqual(44);
      expect(rect?.height, selector).toBeGreaterThanOrEqual(44);
    };
    await page.goto("/health/");
    await page.getByText("Technical details", { exact: true }).click();
    await target('button[aria-label="Copy details"]');
    await page.goto("/firewall/");
    await target("button.iux-touch-target");
    await page.locator("button.fw-cta-lg").click();
    await target("dialog.cm .cm-x");
    await page.keyboard.press("Escape");
    await page.goto("/legal/terms/");
    await target("main nav a.iux-touch-target");
    await page.goto("/android/console/");
    await target("a.iux-touch-target");
    await page.goto("/ar/firewall/");
    await target("button.iux-touch-target");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(2);
  } finally {
    await context.close();
  }
});

test("shared CopyButton reports clipboard failure without a success icon", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => Object.defineProperty(navigator, "clipboard", {
    configurable: true, value: { writeText: async () => { throw new Error("denied"); } }
  }));
  await page.goto("/health/");
  await page.getByText("Technical details", { exact: true }).click();
  const button = page.getByRole("button", { name: "Copy details" });
  await button.click();
  await expect(page.getByRole("status").filter({ hasText: "Clipboard unavailable" })).toBeVisible();
  await expect(page.getByText("Copied", { exact: true })).toHaveCount(0);
});

const MIRROR_PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

test("the app mirror previews mirror clicks and runs them directly while armed", async ({ page }) => {
  const action = { id: "macos-click", label: "Click in app", description: "Preview macos-click", privileged: false };
  await mockApi(page, "macos", { macos: { state: "ready", provider: "native-macos", actions: [action] } });
  let armed = false;
  let clicks = 0;
  await page.route("**/api/labs/macos/apps", (route) => route.fulfill({ json: {
    available: true, reason: null, screenRecording: true,
    windows: [{ windowId: 42, pid: 100, app: "Finder", title: "Demo", x: 0, y: 0, width: 800, height: 600 }]
  } }));
  await page.route("**/api/labs/macos/apps/42/screenshot", (route) => route.fulfill({ body: MIRROR_PNG, headers: { "Content-Type": "image/png" } }));
  await page.route("**/api/labs/macos/apps/42/elements", (route) => route.fulfill({ json: {
    windowId: 42, app: "Finder", bounds: { x: 0, y: 0, width: 800, height: 600 },
    elements: [{ role: "Button", label: "OK", x: 100, y: 100, w: 80, h: 24 }]
  } }));
  await page.route("**/api/labs/macos/control", (route) => {
    if (route.request().method() === "POST") {
      armed = (route.request().postDataJSON() as { armed?: boolean }).armed === true;
    }
    return route.fulfill({ json: { armed, expiresInSec: armed ? 600 : 0 } });
  });
  await page.route("**/api/labs/macos/click", (route) => {
    clicks++;
    return route.fulfill({ json: { ok: true, pid: 100, x: 140, y: 112 } });
  });
  await page.route("**/api/labs/plan", (route) => route.fulfill({ json: {
    plan: { lab: "macos", action: "macos-click", provider: "native-macos", workspace: "", program: "bash",
            args: [], effects: ["One click on this Mac."], timeoutSec: 120, privileged: false, runnable: true,
            manualCommand: null, setup: null, display: "bash mac/macos-app.sh click 100 140 112" },
    token: "test-token"
  } }));

  await page.goto("/labs/macos/");
  await expect(page.getByLabel("Window")).toBeVisible();
  await page.getByRole("button", { name: "Elements" }).click();
  const hotspot = page.getByRole("button", { name: "1: OK" });
  await expect(hotspot).toBeVisible();

  // Without control mode the hotspot only previews the click action.
  await hotspot.click();
  await expect(page.getByRole("heading", { name: /Click in app/ })).toBeVisible();
  await expect.poll(() => clicks).toBe(0);
  await expect(page.getByText("Clicks on the mirror preview a macos-click action first.")).toBeVisible();

  // Armed, the same click lands immediately and never opens a preview.
  await page.getByRole("button", { name: "Arm control" }).click();
  await expect(page.getByText("Armed — mirror clicks run immediately on this Mac.")).toBeVisible();
  await hotspot.click();
  await expect.poll(() => clicks).toBe(1);
});
