import { expect, test, type Page } from "@playwright/test";
import type { LabStatus } from "../src/lib/api";

const labs: LabStatus[] = [
  { id: "android", label: "Android Lab", summary: "Android analysis", state: "needs-setup", provider: "macos-containers", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "source", label: "Source Lab", summary: "Local source analysis", state: "ready", provider: "native-python", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "macos", label: "macOS Lab", summary: "Native Xcode Simulator", state: "ready", provider: "native-macos", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "ios", label: "iOS Lab", summary: "iOS Simulator", state: "ready", provider: "native-macos", reasons: [], requirements: [], notes: [], actions: [], installed: true },
  { id: "windows", label: "Windows Lab", summary: "Windows VM", state: "unavailable", provider: null, reasons: ["Needs Linux/KVM"], requirements: [], notes: [], actions: [], installed: true },
  { id: "winapps", label: "Windows Apps Lab", summary: "Visible desktop windows", state: "unavailable", provider: null, reasons: ["Needs Windows"], requirements: [], notes: [], actions: [], installed: true },
  { id: "linux", label: "Linux Lab", summary: "Linux VM", state: "unavailable", provider: null, reasons: ["Needs Linux/KVM"], requirements: [], notes: [], actions: [], installed: true },
  { id: "web", label: "Web Lab", summary: "In-app browser engine", state: "needs-setup", provider: "native-rust", reasons: [], requirements: [], notes: [], actions: [], installed: true }
];

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    // The host page reads deeper HostInfo fields (tools, disk, …), so mock the full shape
    const body = path === "/api/host" ? {
      host: {
        os: "macos", osPretty: "macOS", arch: "x86_64", hostname: "test-host", cpus: 8,
        memory: 16 * 1024 ** 3, disk: { free: 100 * 1024 ** 3, total: 500 * 1024 ** 3 },
        kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] },
        runtime: null, xcode: null, python: "3.12", root: "/tmp/os-lab", tools: [], providers: []
      },
      labs
    }
      : path === "/api/health" ? { status: "ok" }
      : path === "/api/jobs" ? { jobs: [] }
      : path === "/api/content/status" || path === "/api/content/check" ? { installed: false, offline: true, updateAvailable: false }
      : /^\/api\/labs\/[a-z]+\/monitor$/.test(path) ? { lab: path.split("/")[3], state: "stopped", containers: [] }
      : { logs: [] };
    await route.fulfill({ json: body });
  });
}

async function clearFocus(page: Page) {
  await page.addInitScript(() => window.localStorage.removeItem("oslab.sidebar.activeLab"));
}

test.beforeEach(async ({ page }) => {
  await clearFocus(page);
  await mockApi(page);
});

test("⌘L opens the switcher and focusing a lab narrows the sidebar to it", async ({ page }) => {
  await page.goto("/");
  // Without a focus the OS Lab group lists every lab this computer can run
  await expect(page.getByRole("button", { name: "iOS Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "macOS Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Windows Lab" })).toHaveCount(0);

  await page.keyboard.press("Meta+l");
  const switcher = page.getByRole("dialog", { name: "Switch lab" });
  await expect(switcher).toBeVisible();
  // A compact card per lab, including the ones the sidebar hides, with its live availability
  for (const label of ["iOS Lab", "macOS Lab", "Cleanup Lab", "Windows Lab"]) {
    await expect(switcher.getByRole("option", { name: new RegExp(label) })).toBeVisible();
  }
  await switcher.getByRole("option", { name: /iOS Lab/ }).click();
  await expect(page).toHaveURL(/\/labs\/ios\/$/);
  // The OS Lab group keeps only the focused lab; the rest yield to it
  await expect(page.getByRole("button", { name: "iOS Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "macOS Lab" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Android Lab" })).toHaveCount(0);
});

test("the sidebar card opens the switcher and keyboard picks a lab", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch lab" }).click();
  const switcher = page.getByRole("dialog", { name: "Switch lab" });
  await expect(switcher).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/cleanup\/$/);
  await expect(page.getByRole("button", { name: "Switch lab" })).toContainText("Cleanup Lab");
});

test("a direct link to a lab page re-focuses the sidebar and All labs restores the list", async ({ page }) => {
  await page.goto("/labs/macos/");
  await expect(page.getByRole("button", { name: "macOS Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "iOS Lab" })).toHaveCount(0);

  await page.getByRole("button", { name: "Switch lab" }).click();
  const switcher = page.getByRole("dialog", { name: "Switch lab" });
  await expect(switcher.getByRole("option", { name: /macOS Lab/ })).toHaveAttribute("aria-selected", "true");
  await switcher.getByRole("button", { name: "All labs" }).click();
  await expect(page.getByRole("button", { name: "macOS Lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "iOS Lab" })).toBeVisible();
});

test("Spotlight keeps every lab listed while the sidebar focuses on one", async ({ page }) => {
  await page.goto("/labs/ios/");
  // Wait for the shell to hydrate: an absent button is also true before the shortcut handler exists.
  await expect(page.getByRole("button", { name: "Switch lab" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Android Lab" })).toHaveCount(0);
  // Open Spotlight by its button: the keyboard shortcut attaches separately and can race the first keypress.
  await page.locator('button[aria-label="Open search"]').first().click();
  const spotlight = page.getByRole("dialog", { name: "Spotlight" });
  await expect(spotlight).toBeVisible();
  await spotlight.getByRole("combobox").fill("Android");
  await expect(spotlight.getByRole("option", { name: /Android Lab/ }).first()).toBeVisible();
});
