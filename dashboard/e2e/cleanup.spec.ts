import { expect, test } from "@playwright/test";

test("quick cleanup dashboard: scan all, suggested plan, confirm, report and history", async ({ page }) => {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const scan = { cancelled: false, entries: [{ id: "system.caches", name: "Caches", category: "system", risk: "low", sizeBytes: 42, files: 1, folders: 1, unreadable: [], paths: [{ path: "/tmp/caches", reason: "", source: "env:XDG_CACHE_HOME", sizeBytes: 42, error: null }] }, { id: "browser.private", name: "Private data", category: "browser", risk: "privacy", sizeBytes: 100, files: 1, folders: 0, unreadable: [], paths: [{ path: "/tmp/private", reason: "", sizeBytes: 100, error: null }] }], totals: { sizeBytes: 142, files: 2, folders: 1, unreadable: 0 } };
  const plan = { planId: "plan-1", mode: "trash", expiresAt: Date.now() / 1000 + 600, items: [{ entryId: "system.caches", entryName: "Caches", path: "/tmp/caches", status: "ready", code: "", reason: "", source: "env:XDG_CACHE_HOME", sizeBytes: 42, files: 1, folders: 1 }], totals: { ready: 1, skipped: 0, bytes: 42 } };
  const result = { planId: "plan-1", mode: "trash", cancelled: false, results: [{ entryId: "system.caches", entryName: "Caches", path: "/tmp/caches", status: "trashed", code: "", reason: "", source: "env:XDG_CACHE_HOME", error: null, bytes: 42, trashPath: "/tmp/Trash/caches" }], totals: { items: 1, trashed: 1, deleted: 0, skipped: 0, failed: 0, bytes: 42 } };
  const jobs: Record<string, unknown>[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") calls.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [{ mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs", kind: "root", totalBytes: 500_000_000_000, freeBytes: 250_000_000_000, usedBytes: 250_000_000_000, usage: 0.5, purgeableBytes: null, isHome: true, pressure: "ok", error: null }], homeVolume: "/", warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/explorer/roots") data = { roots: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [{ id: "system.caches", name: "Caches", category: "system", risk: "low", hint: "Safe cache", impact: "", defaultSelected: true, needsPrivilege: false, paths: [{ template: "~/Caches", path: "/tmp/caches", reason: "" }] }, { id: "browser.private", name: "Private data", category: "browser", risk: "privacy", hint: "Sensitive", impact: "", defaultSelected: false, needsPrivilege: false, paths: [{ template: "~/Private", path: "/tmp/private", reason: "" }] }] };
    else if (path === "/api/cleanup/jobs") data = { jobs };
    else if (path === "/api/cleanup/history") data = { entries: [{ id: 1, result, hmac: "abc" }], total: 1, verified: true };
    else if (path === "/api/cleanup/preferences" && route.request().method() === "GET") data = { suggestion: { mode: "auto", include: [], exclude: [], minEntryBytes: 1048576, targetFreeBytes: null }, configError: null };
    else if (path === "/api/cleanup/preferences") data = { suggestion: (body as { suggestion: unknown }).suggestion, configError: null };
    else if (path === "/api/cleanup/suggest") data = { mode: "auto", items: [{ id: "system.caches", name: "Caches", bytes: 42, risk: "low", reason: "recommended" }], totalBytes: 42, pressure: { underPressure: false, freeBytes: null, targetFreeBytes: null, shortfallBytes: 0, covers: true, remainingBytes: 0 }, skipped: [], ignoredIds: [], configError: null };
    else if (path === "/api/cleanup/scan" || path === "/api/cleanup/plan" || path === "/api/cleanup/clean") {
      const kind = path.split("/").at(-1);
      const job = { id: `job-${kind}`, kind, state: "running", request: body, progress: {}, result: null, error: null };
      jobs.unshift(job); data = job;
    } else if (path.startsWith("/api/cleanup/jobs/")) {
      const kind = path.split("/")[4].replace("job-", "");
      const lastPlan = [...calls].reverse().find((call) => call.path === "/api/cleanup/plan")?.body as { mode?: string } | undefined;
      const planned = { ...plan, mode: lastPlan?.mode === "delete" ? "delete" : "trash", planId: lastPlan?.mode === "delete" ? "plan-delete" : plan.planId };
      data = { id: `job-${kind}`, kind, state: "done", request: calls.find((call) => call.path === `/api/cleanup/${kind}`)?.body ?? {}, progress: {}, result: kind === "scan" ? scan : kind === "plan" ? planned : result, error: null };
      const index = jobs.findIndex((job) => job.id === `job-${kind}`);
      if (index >= 0) jobs[index] = data as Record<string, unknown>;
    } else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/");
  await expect(page.getByRole("heading", { name: "Cleanup Lab" }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "iOS Simulator setup" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Android emulator setup" })).toHaveCount(0);
  // CLNP-21/22: the overview — storage hero first, then the renamed review section.
  await expect(page.getByRole("heading", { name: "This computer's storage" })).toBeVisible();
  await expect(page.getByText("50% used", { exact: false })).toBeVisible();
  await expect(page.getByText("232.8 GB", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Purgeable space is managed by macOS", { exact: false })).toBeVisible();
  // CUX-09: the options are collapsed rows with live one-line summaries; one primary action stays visible.
  const options = page.getByRole("region", { name: "Cleanup options" });
  await expect(options.locator("summary", { hasText: "Quick clean" })).toContainText("0 bookmarked");
  await expect(options.locator("summary", { hasText: "Suggestions" })).toContainText("auto · saved on this computer");
  // CUX-02: no bookmarks in this fixture, so Quick clean offers the recommended set instead of staying disabled.
  await options.locator("summary", { hasText: "Quick clean" }).click();
  await expect(options.getByRole("button", { name: "Quick clean", exact: true })).toBeEnabled();
  await expect(page.getByText("scans and reviews the recommended safe set", { exact: false })).toBeVisible();
  // CUX-08: preferences are edited in place and stored through the console.
  await options.locator("summary", { hasText: "Suggestions" }).click();
  await options.getByRole("button", { name: "Extended" }).click();
  await options.getByRole("button", { name: "Save", exact: true }).click();
  await expect(options.getByRole("status").filter({ hasText: "Saved on this computer" })).toBeVisible();
  expect(calls.find((call) => call.path === "/api/cleanup/preferences")?.body).toMatchObject({ suggestion: { mode: "extended" } });
  // Every ability stays one click away: the All tools row lists them all.
  await options.locator("summary", { hasText: "All tools" }).click();
  for (const tool of ["Quick cleanup", "Advanced scan", "Results", "Leftovers", "History", "Bookmarks", "Space Explorer", "Background monitor", "Desktop widgets", "Permissions", "Containers & VMs", "Package review", "Privileged actions", "Projects deep scan", "Simulators", "Android emulators", "Relocation", "Volumes"]) {
    await expect(options.getByRole("button", { name: new RegExp(`^${tool}`) })).toHaveCount(1);
  }
  await expect(page.getByRole("heading", { name: "Clean", exact: true })).toBeVisible();
  // CUX-01: one click scans every entry, builds the recommended Trash plan and opens its confirmation.
  await page.getByRole("button", { name: "Scan & review" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(calls.find((call) => call.path === "/api/cleanup/scan")?.body).toEqual({ entryIds: ["system.caches", "browser.private"] });
  expect(calls.find((call) => call.path === "/api/cleanup/suggest")?.body).toEqual({ jobId: "job-scan" });
  expect(calls.find((call) => call.path === "/api/cleanup/plan")?.body).toEqual({ entryIds: ["system.caches"], mode: "trash" });
  await expect(page.getByRole("dialog")).toContainText("1 items");
  await expect(page.getByRole("dialog")).toContainText("Move to Trash");
  await page.getByRole("button", { name: "Delete permanently instead" }).click();
  await expect(page.getByRole("dialog")).toContainText("Delete permanently");
  expect([...calls].reverse().find((call) => call.path === "/api/cleanup/plan")?.body).toEqual({ entryIds: ["system.caches"], mode: "delete" });
  await page.getByRole("button", { name: "Use Trash instead" }).click();
  await expect(page.getByRole("dialog")).toContainText("Move to Trash");
  await page.getByRole("button", { name: "Run clean" }).click();
  await expect(page.getByRole("dialog")).toContainText("moved to Trash, not yet freed.");
  await page.getByRole("dialog").locator("footer").getByRole("button", { name: "Close" }).click();
  await expect(page.getByText("moved to Trash, not yet freed.", { exact: false })).toBeVisible();
  expect(calls.filter((call) => call.path === "/api/cleanup/clean")[0].body).toEqual({ planId: "plan-1" });
  // CLNP-21: the Space Explorer capability card moved to Settings and still navigates its tab in place.
  await page.goto("/cleanup/settings/");
  await page.getByRole("main").getByRole("button", { name: "Space Explorer" }).click();
  await expect(page).toHaveURL(/\/cleanup\/space\/$/);
  await expect(page.getByRole("heading", { name: "Space Explorer" })).toBeVisible();
  await expect(page.getByText("Pick a root and measure it to see its folders by size.")).toBeVisible();
  await page.goto("/cleanup/results/");
  await expect(page.getByRole("heading", { name: "System" })).toBeVisible();
  await expect(page.getByText("Caches", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.getByText("env:XDG_CACHE_HOME").first()).toBeVisible();
  await page.goto("/cleanup/leftovers/");
  await expect(page.getByText("No leftovers were reported.")).toBeVisible();
  await page.goto("/cleanup/history/");
  await expect(page.getByText("Run #1")).toBeVisible();
  await expect(page.getByText("Trash", { exact: true })).toBeVisible();
});

test("advanced scan sorts by size, reviews a plan and cleans typed", async ({ page }) => {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  const scan = { cancelled: false, entries: [{ id: "system.caches", name: "Caches", category: "system", risk: "low", sizeBytes: 42, files: 1, folders: 1, unreadable: [], paths: [{ path: "/tmp/caches", reason: "", source: "env:XDG_CACHE_HOME", sizeBytes: 42, error: null }] }], totals: { sizeBytes: 42, files: 1, folders: 1, unreadable: 0 } };
  const plan = { planId: "plan-1", mode: "trash", expiresAt: Date.now() / 1000 + 600, items: [{ entryId: "system.caches", entryName: "Caches", path: "/tmp/caches", status: "ready", code: "", reason: "", source: "env:XDG_CACHE_HOME", sizeBytes: 42, files: 1, folders: 1 }], totals: { ready: 1, skipped: 0, bytes: 42 } };
  const result = { planId: "plan-1", mode: "trash", cancelled: false, results: [{ entryId: "system.caches", entryName: "Caches", path: "/tmp/caches", status: "trashed", code: "", reason: "", source: "env:XDG_CACHE_HOME", error: null, bytes: 42, trashPath: "/tmp/Trash/caches" }], totals: { items: 1, trashed: 1, deleted: 0, skipped: 0, failed: 0, bytes: 42 } };
  const jobs: Record<string, unknown>[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") calls.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [{ id: "system.caches", name: "Caches", category: "system", risk: "low", hint: "Safe cache", impact: "", defaultSelected: true, needsPrivilege: false, paths: [{ template: "~/Caches", path: "/tmp/caches", reason: "" }] }] };
    else if (path === "/api/cleanup/jobs") data = { jobs };
    else if (path === "/api/cleanup/scan" || path === "/api/cleanup/plan" || path === "/api/cleanup/clean") {
      const kind = path.split("/").at(-1);
      const job = { id: `job-${kind}`, kind, state: "running", request: body, progress: {}, result: null, error: null };
      jobs.unshift(job); data = job;
    } else if (path.startsWith("/api/cleanup/jobs/")) {
      const kind = path.split("/")[4].replace("job-", "");
      const lastPlan = [...calls].reverse().find((call) => call.path === "/api/cleanup/plan")?.body as { mode?: string } | undefined;
      const planned = { ...plan, mode: lastPlan?.mode === "delete" ? "delete" : "trash", planId: lastPlan?.mode === "delete" ? "plan-delete" : plan.planId };
      data = { id: `job-${kind}`, kind, state: "done", request: calls.find((call) => call.path === `/api/cleanup/${kind}`)?.body ?? {}, progress: {}, result: kind === "scan" ? scan : kind === "plan" ? planned : result, error: null };
      const index = jobs.findIndex((job) => job.id === `job-${kind}`);
      if (index >= 0) jobs[index] = data as Record<string, unknown>;
    } else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/scan/");
  await expect(page.getByRole("heading", { name: "Scan" })).toBeVisible();
  // CUX-03: the filter bar narrows the grid, reports hidden selections and selects only what is visible.
  await page.getByRole("searchbox", { name: "Find an entry or path" }).fill("no-such-entry");
  await expect(page.getByText("No entries match these filters.")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "hidden by filters" })).toContainText("0 / 1");
  await expect(page.getByRole("button", { name: "Select visible" })).toBeDisabled();
  await page.getByRole("searchbox", { name: "Find an entry or path" }).fill("caches");
  await expect(page.getByText("No entries match these filters.")).toHaveCount(0);
  await page.getByRole("button", { name: "Deselect visible" }).click();
  await expect(page.getByRole("button", { name: "Select visible" })).toBeVisible();
  await page.getByRole("button", { name: "Select visible" }).click();
  await expect(page.getByRole("button", { name: "Deselect visible" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Find an entry or path" }).fill("");
  // CUX-04: the row menu reveals the folder by entry id; the page never sends a path.
  await page.getByRole("button", { name: "Actions for Caches" }).click();
  await page.getByRole("menuitem", { name: "Reveal in file manager" }).click();
  await expect.poll(() => calls.find((call) => call.path === "/api/cleanup/entries/reveal")?.body).toEqual({ entryId: "system.caches" });
  await page.getByRole("button", { name: "Scan selected" }).click();
  await expect(page.getByText("42 B across 1 entries")).toBeVisible();
  await page.getByRole("button", { name: "Review & clean" }).click();
  await expect(page.getByRole("dialog")).toContainText("1 items");
  await expect(page.getByRole("dialog")).toContainText("Move to Trash");
  await page.getByRole("button", { name: "Run clean" }).click();
  await expect(page.getByRole("dialog")).toContainText("moved to Trash, not yet freed.");
  await page.getByRole("dialog").locator("footer").getByRole("button", { name: "Close" }).click();
  expect(calls.filter((call) => call.path === "/api/cleanup/clean")[0].body).toEqual({ planId: "plan-1" });
  await expect(page.getByText("Trashed 1")).toBeVisible();
});

test("container pruning needs a preview and VM inventory stays report only", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "linux", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/containers") data = { available: true, engine: "docker", reason: "", actions: [{ id: "containers.docker.dangling-volumes", risk: "high", defaultSelected: false, pruneArgv: ["docker", "volume", "prune", "--all", "--force"] }] };
    else if (path === "/api/cleanup/containers/preview") data = { previewId: "preview-1", actionId: body.actionId, engine: "docker", risk: "high", candidateCount: 1, candidates: [{ Name: "cache-volume" }], command: ["docker", "volume", "prune", "--all", "--force"], expiresAt: Date.now() / 1000 + 600 };
    else if (path === "/api/cleanup/containers/prune") data = { id: "job-prune", kind: "container-prune", state: "running", result: null, error: null };
    else if (path === "/api/cleanup/vms/scan") data = { id: "job-vms", kind: "vm-scan", state: "running", result: null, error: null };
    else if (path === "/api/cleanup/jobs/job-prune") data = { id: "job-prune", kind: "container-prune", state: "done", result: { actionId: "containers.docker.dangling-volumes", engine: "docker", status: "completed", output: "pruned", bytesRemoved: null }, error: null };
    else if (path === "/api/cleanup/jobs/job-vms") data = { id: "job-vms", kind: "vm-scan", state: "done", result: { cancelled: false, items: [{ id: "vms.virtualbox", name: "fixture", path: "/tmp/fixture.vbox", sizeBytes: 42, sizeOnDiskBytes: 42, files: 1, reportOnly: true }], unavailable: [] }, error: null };
    else if (path === "/api/host") data = { host: { os: "linux", osPretty: "Linux", arch: "amd64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/scan/");
  await expect(page.getByText("Container engine:")).toBeVisible();
  expect(posts.filter((call) => call.path === "/api/cleanup/containers/prune")).toHaveLength(0);
  await page.getByRole("button", { name: "Preview Dangling volumes" }).click();
  await page.getByText("Candidates", { exact: true }).click();
  await expect(page.getByText("cache-volume")).toBeVisible();
  await expect(page.getByText("High risk").first()).toBeVisible();
  await page.getByRole("button", { name: "Confirm prune" }).click();
  await expect(page.getByText("Prune completed.", { exact: false })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/containers/prune")?.body).toEqual({ previewId: "preview-1" });
  await page.getByRole("button", { name: "Scan virtual machines" }).click();
  await expect(page.getByText("/tmp/fixture.vbox")).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/vms/scan")?.body).toEqual({});
});

test("Linux app leftovers show inventory uncertainty without a delete action", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", platform: { id: "linux", label: "Linux", supported: true }, reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "linux", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/leftovers/scan") data = { id: "job-leftovers", kind: "leftovers", state: "running", result: null, error: null };
    else if (path === "/api/cleanup/jobs/job-leftovers") data = { id: "job-leftovers", kind: "leftovers", state: "done", result: { available: true, cancelled: false, inventorySources: ["dpkg"], inventoryErrors: ["flatpak: inventory command failed"], unreadable: [], items: [{ id: "leftovers.linux.cache", name: "Acme", path: "/tmp/acme", status: "unknown", confidence: 0, rule: "inventory-incomplete", sizeBytes: 42, sizeOnDiskBytes: 42, reportOnly: true }] }, error: null };
    else if (path === "/api/host") data = { host: { os: "linux", osPretty: "Linux", arch: "amd64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/leftovers/");
  await page.getByRole("button", { name: "Scan", exact: true }).click();
  await expect(page.getByText("flatpak: inventory command failed")).toBeVisible();
  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.getByText("/tmp/acme")).toBeVisible();
  await expect(page.getByText("unknown", { exact: true })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/leftovers/scan")?.body).toEqual({});
  await expect(page.locator("section").filter({ hasText: "Report only. No files are deleted here." }).getByRole("button", { name: /delete|clean/i })).toHaveCount(0);
});

test("public cleanup route has no engine controls", async ({ page }) => {
  test.skip(!process.env.OSLAB_PAGES_TEST, "run against a Pages build");
  let apiCalls = 0;
  await page.route("**/api/**", async (route) => { apiCalls++; await route.abort(); });
  await page.goto("/os-lab/tr/cleanup/");
  await expect(page.getByText("Temizleme Laboratuvarı yerel uygulamada çalışır.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Scan & review" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Sonuçlar" })).toHaveAttribute("href", "/os-lab/tr/cleanup/results/");
  expect(apiCalls).toBe(0);
});

test("catalogs: report-only agent homes cannot be ticked, cleanable children enable Review removal", async ({ page }) => {
  const entry = (id: string, name: string, risk: string, cleanable: boolean, path: string) => ({
    id, name, category: "developer", risk, hint: "Agent data", impact: "", defaultSelected: false, needsPrivilege: false, cleanable,
    paths: [{ template: path, path, reason: "" }],
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [
      entry("agents.codex", "Codex data", "credentials", false, "/Users/demo/.codex"),
      entry("agents.codex-bulk", "Codex packages and caches", "medium", true, "/Users/demo/.codex/packages"),
    ] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/host") data = { host: { os: "linux", osPretty: "Linux", arch: "amd64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/catalog/#agents");
  const parent = page.getByRole("checkbox", { name: "Select Codex data" });
  const child = page.getByRole("checkbox", { name: "Select Codex packages and caches" });
  const review = page.getByRole("button", { name: "Review removal" });
  await expect(parent).toBeDisabled();
  await expect(parent).toHaveAttribute("title", "Measured only. It cannot be removed here.");
  await expect(review).toBeDisabled();
  await expect(child).toBeEnabled();
  await child.check();
  await expect(review).toBeEnabled();
});

test("CLS-01 simulators: preview a fixed simctl action, confirm once, running devices locked", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const devices = [
    { id: "B1B2C3D4-1111-2222-3333-444455556666", name: "iPhone 8", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-15-0", state: "Shutdown", available: false, sizeBytes: 3_000_000_000 },
    { id: "A1B2C3D4-1111-2222-3333-444455556666", name: "iPhone 16", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-18-0", state: "Shutdown", available: true, sizeBytes: 2_000_000_000 },
    { id: "C1B2C3D4-1111-2222-3333-444455556666", name: "iPad Air", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-18-0", state: "Booted", available: true, sizeBytes: 1_000_000_000 }
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/containers") data = { available: false, engine: null, reason: "Neither Docker nor Podman is responding.", actions: [] };
    else if (path === "/api/cleanup/simulators") data = { available: true, reason: "", devices, actions: [] };
    else if (path === "/api/cleanup/simulators/preview") data = { previewId: "sim-1", actionId: body.actionId, risk: "low", candidateCount: 1, bytes: 3_000_000_000, devices: [devices[0]], command: ["xcrun", "simctl", "delete", "unavailable"], expiresAt: Date.now() / 1000 + 600 };
    else if (path === "/api/cleanup/simulators/run") data = { id: "job-sim", kind: "simulator-run", state: "running", progress: null, result: null, error: null };
    else if (path === "/api/cleanup/jobs/job-sim") data = { id: "job-sim", kind: "simulator-run", state: "done", progress: null, result: { kind: "simulators", actionId: "simulators.delete-unavailable", status: "completed", candidateCount: 1, devices: [devices[0]], command: ["xcrun", "simctl", "delete", "unavailable"], bytesFreed: 3_000_000_000 }, error: null };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/scan/");
  const card = page.locator("#scan-simulators");
  await expect(card.getByText("iPhone 16")).toBeVisible();
  await expect(card.getByText("iOS 18.0").first()).toBeVisible();
  // A running simulator cannot be selected; nothing runs before a confirmed preview.
  await expect(card.getByRole("checkbox", { name: "iPad Air" })).toBeDisabled();
  await expect(card.getByRole("button", { name: "Delete selected" })).toBeDisabled();
  await card.getByRole("button", { name: /Delete unavailable simulators/ }).click();
  await expect(card.getByText("xcrun simctl delete unavailable")).toBeVisible();
  expect(posts.filter((call) => call.path === "/api/cleanup/simulators/run")).toHaveLength(0);
  expect(posts.find((call) => call.path === "/api/cleanup/simulators/preview")?.body).toEqual({ actionId: "simulators.delete-unavailable" });
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Done.", { exact: false })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/simulators/run")?.body).toEqual({ previewId: "sim-1" });
  // Selecting a shut-down device previews the typed device action with its id.
  await card.getByRole("checkbox", { name: "iPhone 16" }).check();
  await card.getByRole("button", { name: "Erase selected" }).click();
  await expect.poll(() => posts.filter((call) => call.path === "/api/cleanup/simulators/preview").at(-1)?.body)
    .toEqual({ actionId: "simulators.erase-devices", deviceIds: ["A1B2C3D4-1111-2222-3333-444455556666"] });
});

test("CLS-03 simulator runtimes: Xcode-managed ones locked, one runtime per preview", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const runtimes = [
    { id: "D1D2D3D4-1111-2222-3333-444455556666", name: "iOS 15.0", version: "15.0", build: "19A339", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-15-0", state: "Ready", deletable: true, lastUsedAt: null, kind: "Disk Image", sizeBytes: 6_000_000_000 },
    { id: "E1E2E3E4-1111-2222-3333-444455556666", name: "iOS 18.0", version: "18.0", build: "22A3351", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-18-0", state: "Ready", deletable: false, lastUsedAt: null, kind: "Bundled with Xcode", sizeBytes: 8_000_000_000 }
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/containers") data = { available: false, engine: null, reason: "Neither Docker nor Podman is responding.", actions: [] };
    else if (path === "/api/cleanup/simulators") data = { available: true, reason: "", devices: [], actions: [], runtimes, runtimeReason: "" };
    else if (path === "/api/cleanup/simulators/preview") data = { previewId: "rt-1", actionId: body.actionId, risk: "high", candidateCount: 1, bytes: 6_000_000_000, devices: [{ id: runtimes[0].id, name: "iOS 15.0", runtime: runtimes[0].runtime, state: "Ready", available: true, sizeBytes: 6_000_000_000 }], command: ["xcrun", "simctl", "runtime", "delete", runtimes[0].id], expiresAt: Date.now() / 1000 + 600 };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/scan/");
  const card = page.locator("#scan-simulators");
  const xcodeRow = card.locator("li", { hasText: "iOS 18.0" });
  await expect(xcodeRow.getByText("Managed by Xcode")).toBeVisible();
  await expect(xcodeRow.getByRole("button", { name: "Delete" })).toBeDisabled();
  await card.locator("li", { hasText: "iOS 15.0" }).getByRole("button", { name: "Delete" }).click();
  await expect(card.getByText(`xcrun simctl runtime delete ${runtimes[0].id}`)).toBeVisible();
  await expect(card.getByText("Simulators that use this runtime become unavailable.", { exact: false })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/simulators/preview")?.body).toEqual({ actionId: "simulators.delete-runtime", deviceIds: [runtimes[0].id] });
  expect(posts.filter((call) => call.path === "/api/cleanup/simulators/run")).toHaveLength(0);
});

for (const os of ["linux", "macos", "windows"] as const) {
  test(`CLA-03 unused system images uninstall on ${os} previews and does not run`, async ({ page }) => {
    const posts: { path: string; body: Record<string, unknown> }[] = [];
    const unused = "system-images;android-28;default;x86";
    const used = "system-images;android-34;google_apis;arm64-v8a";
    const images = [
      { id: unused, name: "Intel x86 Atom System Image", version: "1", path: "/sdk/system-images/android-28/default/x86", sizeBytes: 800_000_000, avds: [], unused: true },
      { id: used, name: "Google APIs ARM 64 v8a System Image", version: "2", path: "/sdk/system-images/android-34/google_apis/arm64-v8a", sizeBytes: 1_200_000_000, avds: ["Pixel_7"], unused: false }
    ];
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const body = route.request().postDataJSON?.() ?? {};
      if (route.request().method() === "POST") posts.push({ path, body });
      let data: unknown = {};
      if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
      else if (path === "/api/cleanup/catalog") data = { platform: os, entries: [] };
      else if (path === "/api/cleanup/jobs") data = { jobs: [] };
      else if (path === "/api/cleanup/simulators") data = { available: false, reason: "Xcode simulators require macOS", devices: [], actions: [], runtimes: [] };
      else if (path === "/api/cleanup/emulator-storage") data = { available: false, reason: "No Android SDK or AVD folder on this computer" };
      else if (path === "/api/cleanup/emulators") data = {
        available: true, reason: "", folder: "/tmp/avd", source: "default", sdkRoot: "/sdk",
        devices: [{ id: "Pixel_7", name: "Pixel_7", runtime: "android-34", path: "/tmp/avd/Pixel_7.avd", state: "Shutdown", available: true, sizeBytes: 4 }],
        actions: [{ id: "emulators.uninstall-images", risk: "medium", needsSelection: true, defaultSelected: false, target: "images", command: ["sdkmanager", "--uninstall", "<package>"] }],
        images, imageReason: ""
      };
      else if (path === "/api/cleanup/emulators/preview") data = {
        previewId: "img-1", actionId: body.actionId, risk: "medium", candidateCount: 1, bytes: 800_000_000,
        devices: [{ id: unused, name: "Intel x86 Atom System Image", runtime: unused, state: "Unused", available: true, sizeBytes: 800_000_000 }],
        command: ["sdkmanager", "--uninstall", unused], expiresAt: Date.now() / 1000 + 600
      };
      else if (path === "/api/host") data = { host: { os, osPretty: os, arch: "x64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: true, usable: true }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
      else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
      else if (path === "/api/jobs") data = { jobs: [] };
      else if (path === "/api/logs") data = { logs: [] };
      await route.fulfill({ json: data });
    });
    await page.goto("/cleanup/scan/");
    const card = page.locator("#scan-emulators");
    await expect(card.getByRole("heading", { name: "System images" })).toBeVisible();
    const usedRow = card.locator("li", { hasText: "Google APIs ARM 64 v8a System Image" });
    await expect(usedRow.getByText("In use")).toBeVisible();
    await expect(usedRow.getByRole("button", { name: "Uninstall unused image" })).toBeDisabled();
    await card.locator("li", { hasText: "Intel x86 Atom System Image" }).getByRole("button", { name: "Uninstall unused image" }).click();
    await expect(card.getByText(`sdkmanager --uninstall ${unused}`)).toBeVisible();
    await expect(card.getByText("sdkmanager will uninstall this package.", { exact: false })).toBeVisible();
    expect(posts.find((call) => call.path === "/api/cleanup/emulators/preview")?.body).toEqual({ actionId: "emulators.uninstall-images", deviceIds: [unused] });
    expect(posts.filter((call) => call.path === "/api/cleanup/emulators/run")).toHaveLength(0);
  });
}

test("macOS dashboard shows the iOS Simulator setup card with move and delete actions", async ({ page }) => {
  const GIB = 1024 ** 3;
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const jobPolls: Record<string, number> = { p1: 0, r1: 0 };
  const devices = [
    { id: "B1B2C3D4-1111-2222-3333-444455556666", name: "iPhone 8", runtime: "com.apple.CoreSimulator.SimRuntime.iOS-15-0", state: "Shutdown", available: false, sizeBytes: 3_000_000_000 }
  ];
  const storage = {
    available: true, reason: "", entryId: "simulators.coresimulator-devices",
    folder: "/Users/test/Library/Developer/CoreSimulator/Devices", state: "local",
    target: "/Users/test/Library/Developer/CoreSimulator/Devices",
    volume: { mountPoint: "/", kind: "root" }, home: { mountPoint: "/", freeBytes: 40 * GIB, totalBytes: 500 * GIB },
    config: { destination: null, suggest: true, floorBytes: 20 * GIB }, configError: null,
    destinations: [{ mountPoint: "/Volumes/Ext", name: "Ext", kind: "internal", freeBytes: 900 * GIB, totalBytes: 1000 * GIB }],
    suggestion: { action: "setup", reason: "Simulator devices are still on the system disk." }
  };
  const plan = {
    action: "move", entryId: "simulators.coresimulator-devices", entryName: "iOS Simulator devices",
    homePath: "/Users/test/Library/Developer/CoreSimulator/Devices",
    storePath: "/Volumes/Ext/oslab-caches/simulators.coresimulator-devices",
    destination: "/Volumes/Ext", files: 3, sizeBytes: 50, freeBytes: 900 * GIB,
    state: "local_only", fingerprint: { files: 3, bytes: 50 },
    steps: [], previewId: "prev-sim"
  };
  const run = {
    entryId: "simulators.coresimulator-devices", action: "move", status: "completed",
    homePath: plan.homePath, storePath: plan.storePath, bytesRelocated: 50, bytesRemoved: null,
    cancelled: false, stepsDone: 6, stepsTotal: 6
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "macos", threshold: 0.9, volumes: [{ mountPoint: "/", name: "Macintosh HD", device: "/dev/disk1", filesystem: "apfs", kind: "root", totalBytes: 500_000_000_000, freeBytes: 250_000_000_000, usedBytes: 250_000_000_000, usage: 0.5, purgeableBytes: null, isHome: true, pressure: "ok", error: null }], homeVolume: "/", warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/cleanup/preferences") data = { suggestion: { mode: "auto", include: [], exclude: [], minEntryBytes: 1048576, targetFreeBytes: null }, configError: null };
    else if (path === "/api/cleanup/simulator-storage") data = storage;
    else if (path === "/api/cleanup/simulators") data = { available: true, reason: "", devices, actions: [] };
    else if (path === "/api/cleanup/simulators/preview") data = { previewId: "sim-1", actionId: body.actionId, risk: "low", candidateCount: 1, bytes: 3_000_000_000, devices, command: ["xcrun", "simctl", "delete", "unavailable"], expiresAt: Date.now() / 1000 + 600 };
    else if (path === "/api/cleanup/simulators/run") data = { id: "job-sim", kind: "simulator-run", state: "running", progress: null, result: null, error: null };
    else if (path === "/api/cleanup/jobs/job-sim") data = { id: "job-sim", kind: "simulator-run", state: "done", progress: null, result: { kind: "simulators", actionId: "simulators.delete-unavailable", status: "completed", candidateCount: 1, devices, command: ["xcrun", "simctl", "delete", "unavailable"], bytesFreed: 3_000_000_000 }, error: null };
    else if (path === "/api/cleanup/relocation") data = { platform: "macos", entries: [{ entryId: "simulators.coresimulator-devices", name: "iOS Simulator devices", path: "/Users/test/Library/Developer/CoreSimulator/Devices", relocatable: true, interrupted: false }], destinations: [] };
    else if (path === "/api/cleanup/relocation/plan") data = { id: "p1", kind: "relocation-plan", state: "running", progress: null, result: null, error: null };
    else if (path === "/api/cleanup/relocation/run") data = { id: "r1", kind: "relocation-run", state: "running", progress: { step: "copy", stepsDone: 1, stepsTotal: 6 }, result: null, error: null };
    else if (path === "/api/cleanup/jobs/p1") {
      jobPolls.p1 += 1;
      data = jobPolls.p1 === 1
        ? { id: "p1", kind: "relocation-plan", state: "running", progress: null, result: null, error: null }
        : { id: "p1", kind: "relocation-plan", state: "done", progress: null, result: plan, error: null };
    } else if (path === "/api/cleanup/jobs/r1") {
      jobPolls.r1 += 1;
      data = jobPolls.r1 === 1
        ? { id: "r1", kind: "relocation-run", state: "running", progress: { step: "copy", stepsDone: 1, stepsTotal: 6 }, result: null, error: null }
        : { id: "r1", kind: "relocation-run", state: "done", progress: null, result: run, error: null };
    } else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/");
  const card = page.locator("#simulator-setup");
  await expect(card.getByRole("heading", { name: "iOS Simulator setup" })).toBeVisible();
  await expect(card.getByText("On the system disk", { exact: true })).toBeVisible();
  await expect(card.getByText("Simulator devices are still on the system disk.", { exact: false })).toBeVisible();
  await expect(card.getByText("1 unavailable simulators", { exact: false })).toBeVisible();
  await card.getByRole("button", { name: "Move simulators off the system disk" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Confirm relocation")).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/simulator-storage")?.body).toMatchObject({ destination: "/Volumes/Ext" });
  expect(posts.find((call) => call.path === "/api/cleanup/relocation/plan")?.body).toEqual({ action: "move", entryId: "simulators.coresimulator-devices", destination: "/Volumes/Ext" });
  expect(posts.filter((call) => call.path === "/api/cleanup/relocation/run")).toHaveLength(0);
  await dialog.getByRole("button", { name: "Run relocation" }).click();
  await expect(card.getByText("Moved", { exact: false })).toBeVisible();
  await expect(card.getByText("50 B", { exact: false }).first()).toBeVisible();
  await card.getByRole("button", { name: "Delete unavailable simulators" }).click();
  await expect(card.getByText("Deleted simulators and their apps and data cannot be restored.")).toBeVisible();
  expect(posts.filter((call) => call.path === "/api/cleanup/simulators/run")).toHaveLength(0);
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Done.", { exact: false })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/simulators/run")?.body).toEqual({ previewId: "sim-1" });
});

test("dashboard shows the Android emulator setup card with delete unavailable", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  const devices = [
    { id: "Pixel_7", name: "Pixel_7", runtime: "android-34", path: "/tmp/avd/Pixel_7.avd", state: "Shutdown", available: true, sizeBytes: 4_000_000_000 },
    { id: "Old_8", name: "Old_8", runtime: "android-28", path: "/tmp/avd/Old_8.avd", state: "Shutdown", available: false, sizeBytes: null }
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON?.() ?? {};
    if (route.request().method() === "POST") posts.push({ path, body });
    let data: unknown = {};
    if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/monitor") data = { enabled: false, running: false, intervalSeconds: 300, cooldownSeconds: 3600, volumes: [], state: { volumes: {}, events: [], lastEvaluationAt: null, lastError: null }, activeWarnings: [], configError: null, checkedAt: 1 };
    else if (path === "/api/cleanup/volumes") data = { platform: "linux", threshold: 0.9, volumes: [], homeVolume: null, warnings: [], error: null };
    else if (path === "/api/cleanup/bookmarks") data = { bookmarks: [], error: null };
    else if (path === "/api/cleanup/permissions") data = { platform: "linux", permissions: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "linux", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/cleanup/preferences") data = { suggestion: { mode: "auto", include: [], exclude: [], minEntryBytes: 1048576, targetFreeBytes: null }, configError: null };
    else if (path === "/api/cleanup/simulator-storage") data = { available: false, reason: "iOS Simulator storage is macOS only" };
    else if (path === "/api/cleanup/simulators") data = { available: false, reason: "Xcode simulators require macOS", devices: [], actions: [] };
    else if (path === "/api/cleanup/emulator-storage") data = { available: false, reason: "No Android SDK or AVD folder on this computer" };
    else if (path === "/api/cleanup/relocation") data = { platform: "linux", entries: [], destinations: [] };
    else if (path === "/api/cleanup/emulators") data = { available: true, reason: "", folder: "/tmp/avd", source: "default", devices, actions: [] };
    else if (path === "/api/cleanup/emulators/preview") data = { previewId: "emu-1", actionId: body.actionId, risk: "low", candidateCount: 1, bytes: 0, devices: [devices[1]], command: ["avdmanager", "delete", "avd", "-n", "Old_8"], expiresAt: Date.now() / 1000 + 600 };
    else if (path === "/api/cleanup/emulators/run") data = { id: "job-emu", kind: "emulator-run", state: "running", progress: null, result: null, error: null };
    else if (path === "/api/cleanup/jobs/job-emu") data = { id: "job-emu", kind: "emulator-run", state: "done", progress: null, result: { kind: "emulators", actionId: "emulators.delete-unavailable", status: "completed", candidateCount: 1, devices: [devices[1]], command: ["avdmanager", "delete", "avd", "-n", "Old_8"], bytesFreed: 0 }, error: null };
    else if (path === "/api/host") data = { host: { os: "linux", osPretty: "Linux", arch: "x64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: true, usable: true }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/");
  const card = page.locator("#emulator-setup");
  await expect(card.getByRole("heading", { name: "Android emulator setup" })).toBeVisible();
  await expect(card.getByText("1 unavailable emulators", { exact: false })).toBeVisible();
  await card.getByRole("button", { name: "Delete unavailable emulators" }).click();
  await expect(card.getByText("Deleted emulators and their apps and data cannot be restored.")).toBeVisible();
  expect(posts.filter((call) => call.path === "/api/cleanup/emulators/run")).toHaveLength(0);
  await card.getByRole("button", { name: "Confirm" }).click();
  await expect(card.getByText("Done.", { exact: false })).toBeVisible();
  expect(posts.find((call) => call.path === "/api/cleanup/emulators/run")?.body).toEqual({ previewId: "emu-1" });
});
