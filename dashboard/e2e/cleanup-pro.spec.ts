import { expect, test } from "@playwright/test";

/**
 * Covers the compact pro cards for capabilities that have no dedicated
 * dashboard card yet, all through mocked typed endpoints (no engine calls).
 */
const baseMocks = {
  state: "ready",
  reasons: [],
  requirements: [],
  capabilities: [],
};
const volumes = {
  platform: "macos",
  threshold: 0.9,
  homeVolume: "/",
  warnings: [],
  error: null,
  volumes: [{
    mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs",
    kind: "root", totalBytes: 500_000_000_000, freeBytes: 250_000_000_000,
    usedBytes: 250_000_000_000, usage: 0.5, purgeableBytes: null, isHome: true,
    pressure: "ok", error: null,
  }],
};
const catalog = {
  platform: "macos",
  entries: [{
    id: "system.caches", name: "Caches", category: "system", risk: "low",
    hint: "Safe cache", impact: "", defaultSelected: true, needsPrivilege: false,
    paths: [{ template: "~/Caches", path: "/tmp/caches", reason: "" }],
  }],
};

async function mockConsole(page: import("@playwright/test").Page, overrides: Record<string, unknown> = {}) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const jobs: Record<string, unknown>[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") calls.push({ path, body });
    async function handle() {
      let data: unknown = {};
      if (path === "/api/cleanup/status") data = baseMocks;
      else if (path === "/api/cleanup/volumes") data = volumes;
      else if (path === "/api/cleanup/catalog") data = catalog;
      else if (path === "/api/cleanup/monitor") data = {
        enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [],
        state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null },
        activeWarnings: [], configError: null, checkedAt: 1,
      };
      else if (path === "/api/cleanup/widget") data = {
        schemaVersion: 1, capturedAt: 1, platform: "macos", capable: false,
        disk: { mountPoint: null, totalBytes: null, freeBytes: null, usedPercent: null },
        lastScan: null, progress: null, cleanup: { totalReclaimedBytes: 0, lastRunAt: null },
        monitor: { enabled: false, intervalSeconds: null, nextCheckAt: null, lastWarningAt: null, warningCount: 0 },
        bookmarks: { count: 0, quickCleanCount: 0, hookCount: 0, alertCount: 0 },
        permissions: { fullDiskAccess: null }, status: "up-to-date",
        publish: { published: false, path: null, reason: null },
      };
      else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
      else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
      else if (path === "/api/cleanup/jobs") data = { jobs };
      else if (overrides[path]) data = overrides[path];
      else if (path.startsWith("/api/cleanup/jobs/")) {
        const kind = path.split("/")[4];
        data = { id: `job-${kind}`, kind, state: "done", request: {}, progress: {}, result: null, error: null };
        const index = jobs.findIndex((job) => job.id === `job-${kind}`);
        if (index >= 0) jobs[index] = data as Record<string, unknown>;
      } else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
      else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
      else if (path === "/api/jobs") data = { jobs: [] };
      else if (path === "/api/logs") data = { logs: [] };
      else { await route.continue(); return; }
      await route.fulfill({ json: data });
    }
    await handle();
  });
  return { calls, jobs };
}

test("all pro cards render on the dashboard", async ({ page }) => {
  await mockConsole(page, {
    "/api/cleanup/privileged": {
      platform: "macos", applicable: true, elevation: "pkexec",
      actions: [{ id: "privileged.macos.docker-clean", name: "Docker prune", risk: "medium", impact: "Reclaims Docker build cache", previewMode: "files", runArgv: ["docker", "system", "prune", "--all", "--force"] }],
      diskAccess: { applicable: true, granted: true, reason: "" },
    },
    "/api/cleanup/deep-roots": {
      roots: [{ id: "home-projects", path: "/Users/test/Projects", available: true, reason: null }],
    },
    "/api/cleanup/simulators": {
      available: true, reason: "",
      devices: [{ id: "AAAA", name: "iPhone 16", runtime: "iOS 18.0", state: "Booted", available: true, sizeBytes: 4_200_000_000 }],
    },
    "/api/cleanup/containers": {
      available: true, engine: "docker", reason: "",
      actions: [{ id: "containers.docker.dangling-volumes", risk: "high" }],
    },
  });
  await page.goto("/cleanup/");
  await expect(page.getByRole("heading", { name: "Cleanup Lab" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Privileged actions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Projects deep scan" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Simulators" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Package review" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cross-platform leftovers" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Containers & VMs" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Custom entries" })).toBeVisible();
});

test("privileged actions preview shows the command and run finishes", async ({ page }) => {
  const preview = {
    previewId: "prev-1", actionId: "privileged.macos.docker-clean", engine: "pkexec", elevation: "pkexec",
    risk: "medium", candidateCount: 1, candidates: ["/private/var/folders"], totalBytes: 1024,
    command: ["pkexec", "docker", "system", "prune", "--all", "--force"], expiresAt: Date.now() / 1000 + 600,
  };
  const runResult = { actionId: "privileged.macos.docker-clean", engine: "pkexec", status: "completed" as const, bytesRemoved: 1024 };
  await mockConsole(page, {
    "/api/cleanup/privileged": {
      platform: "macos", applicable: true, elevation: "pkexec",
      actions: [{ id: "privileged.macos.docker-clean", name: "Docker prune", risk: "medium", impact: "Reclaims cache", previewMode: "files", runArgv: ["docker", "system", "prune"] }],
      diskAccess: { applicable: true, granted: true, reason: "" },
    },
    "/api/cleanup/privileged/preview": preview,
    "/api/cleanup/privileged/run": { id: "job-privileged", kind: "privileged-run", state: "running", request: { previewId: "prev-1" }, progress: {}, result: null, error: null },
    "/api/cleanup/jobs/job-privileged": { id: "job-privileged", kind: "privileged-run", state: "done", request: { previewId: "prev-1" }, progress: {}, result: runResult, error: null },
  });
  await page.goto("/cleanup/");
  await page.getByRole("button", { name: "Preview Docker prune" }).click();
  await expect(page.getByText("pkexec docker system prune --all --force", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByText("Finished: completed", { exact: false })).toBeVisible();
});

test("deep scan lists available roots and runs a sweep", async ({ page }) => {
  const scanResult = [{
    id: "node-modules", rootId: "home-projects", path: "/Users/test/Projects/demo/node_modules",
    project: "/Users/test/Projects/demo", ecosystem: "npm", regenerate: "npm install",
    idleDays: 45, sizeBytes: 2_100_000_000, sizeOnDiskBytes: 2_100_000_000, files: 1200, folders: 300,
  }];
  await mockConsole(page, {
    "/api/cleanup/deep-roots": {
      roots: [{ id: "home-projects", path: "/Users/test/Projects", available: true, reason: null }],
    },
    "/api/cleanup/deep-scan": { id: "job-deep", kind: "deep-scan", state: "running", request: { entryIds: ["home-projects"] }, progress: {}, result: null, error: null },
    "/api/cleanup/jobs/job-deep": { id: "job-deep", kind: "deep-scan", state: "done", request: { entryIds: ["home-projects"] }, progress: {}, result: scanResult, error: null },
  });
  await page.goto("/cleanup/");
  await expect(page.getByRole("button", { name: "home-projects" })).toBeVisible();
  await page.getByRole("button", { name: "home-projects" }).click();
  await page.getByRole("button", { name: "Scan", exact: true }).click();
  await expect(page.getByText("npm", { exact: false })).toBeVisible();
  await expect(page.getByText("/Users/test/Projects/demo", { exact: false })).toBeVisible();
});

test("simulators lists devices with size", async ({ page }) => {
  await mockConsole(page, {
    "/api/cleanup/simulators": {
      available: true, reason: "",
      devices: [{ id: "AAAA", name: "iPhone 16", runtime: "iOS 18.0", state: "Booted", available: true, sizeBytes: 4_200_000_000 }],
    },
  });
  await page.goto("/cleanup/");
  await expect(page.getByText("iPhone 16", { exact: false })).toBeVisible();
  await expect(page.locator("#pro-simulators").getByText("iOS 18.0", { exact: false })).toBeVisible();
});

test("package review lists candidates", async ({ page }) => {
  const scanResult = [{
    id: "brew:old", name: "old-tool", tool: "brew", version: "1.0.0",
    command: ["brew", "uninstall", "old-tool"], sizeBytes: 50_000_000, reportOnly: true,
  }];
  await mockConsole(page, {
    "/api/cleanup/packages/scan": { id: "job-pkg", kind: "packages", state: "done", request: {}, progress: {}, result: scanResult, error: null },
  });
  await page.goto("/cleanup/");
  await page.getByRole("button", { name: "Scan packages", exact: true }).click();
  await expect(page.getByText("old-tool", { exact: true })).toBeVisible();
  await expect(page.getByText("brew uninstall old-tool", { exact: false })).toBeVisible();
});

test("leftovers scan lists items with confidence", async ({ page }) => {
  const scanResult = {
    available: true, cancelled: false,
    items: [{ id: "left.1", name: "Acme Helper", path: "/Users/test/Library/Helper", status: "unknown", confidence: 0.9, rule: "orphan-app", sizeBytes: 100_000_000, reportOnly: true }],
    inventorySources: ["dpkg"], inventoryErrors: [], unreadable: [],
  };
  await mockConsole(page, {
    "/api/cleanup/leftovers/scan": { id: "job-left", kind: "leftovers", state: "done", request: {}, progress: {}, result: scanResult, error: null },
  });
  await page.goto("/cleanup/");
  await page.getByRole("button", { name: "Scan leftovers", exact: true }).click();
  await expect(page.getByText("Acme Helper", { exact: false })).toBeVisible();
  await expect(page.getByText("Likely leftover", { exact: false })).toBeVisible();
  await expect(page.locator("#pro-leftovers").getByText("95 MB", { exact: false }).first()).toBeVisible();
});

test("containers & VMs shows the engine and prune preview", async ({ page }) => {
  const preview = {
    previewId: "prev-c", actionId: "containers.docker.dangling-volumes", engine: "docker", risk: "high",
    candidateCount: 2, candidates: [{ Name: "cache-volume" }], totalBytes: 500_000_000,
    command: ["docker", "volume", "prune", "--all", "--force"], expiresAt: Date.now() / 1000 + 600,
  };
  await mockConsole(page, {
    "/api/cleanup/containers": {
      available: true, engine: "docker", reason: "",
      actions: [{ id: "containers.docker.dangling-volumes", risk: "high" }],
    },
    "/api/cleanup/containers/preview": preview,
    "/api/cleanup/containers/prune": { id: "job-prune", kind: "container-prune", state: "running", request: { previewId: "prev-c" }, progress: {}, result: null, error: null },
    "/api/cleanup/jobs/job-prune": { id: "job-prune", kind: "container-prune", state: "done", request: { previewId: "prev-c" }, progress: {}, result: { ...preview, status: "completed", bytesRemoved: 500_000_000 }, error: null },
  });
  await page.goto("/cleanup/");
  await expect(page.getByText("DOCKER", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Preview containers.docker.dangling-volumes" }).click();
  await expect(page.getByText("docker volume prune --all --force", { exact: false })).toBeVisible();
});

test("custom entries shows empty state and an add link", async ({ page }) => {
  await mockConsole(page);
  await page.goto("/cleanup/");
  await expect(page.getByText("No custom folders yet.", { exact: false })).toBeVisible();
  await expect(page.getByText("Add a user folder in", { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: "Settings → Bookmarks" })).toBeVisible();
});
