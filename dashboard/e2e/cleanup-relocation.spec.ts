import { expect, test } from "@playwright/test";

/**
 * CLN-27 dashboard layer: the Relocation tab lists relocatable entries and
 * destination volumes, then move → plan preview → confirm dialog → run, all
 * against a mocked console. Nothing runs until the dialog's Run is clicked.
 */
const STATUS = {
  platform: "macos",
  entries: [
    { entryId: "developers.gradle", name: "Gradle caches", path: "/Users/test/.gradle/caches", relocatable: true, interrupted: false },
    { entryId: "developers.go-build", name: "Go build cache", path: "/Users/test/Library/Caches/go-build", relocatable: false, interrupted: false }
  ],
  destinations: [
    { mountPoint: "/", freeBytes: 10 * 1024 ** 3, totalBytes: 500 * 1024 ** 3, kind: "root" },
    { mountPoint: "/Volumes/Ext", freeBytes: 900 * 1024 ** 3, totalBytes: 1000 * 1024 ** 3, kind: "internal" }
  ]
};
const PLAN = {
  action: "move", entryId: "developers.gradle", entryName: "Gradle caches",
  homePath: "/Users/test/.gradle/caches", storePath: "/Volumes/Ext/oslab-caches/developers.gradle",
  destination: "/Volumes/Ext", files: 3, sizeBytes: 50, freeBytes: 900 * 1024 ** 3,
  state: "local_only", fingerprint: { files: 3, bytes: 50 },
  steps: [
    { op: "copy", src: "/Users/test/.gradle/caches", dst: "/Volumes/Ext/oslab-caches/developers.gradle" },
    { op: "symlink", src: "/Users/test/.gradle/caches", dst: "/Volumes/Ext/oslab-caches/developers.gradle" }
  ],
  previewId: "prev-1"
};
const RUN = {
  entryId: "developers.gradle", action: "move", status: "completed",
  homePath: "/Users/test/.gradle/caches", storePath: "/Volumes/Ext/oslab-caches/developers.gradle",
  bytesRelocated: 50, bytesRemoved: null, cancelled: false, stepsDone: 6, stepsTotal: 6
};
const runningJob = (id: string, kind: string) => ({ id, kind, state: "running", progress: null, result: null, error: null });
const doneJob = (id: string, kind: string, result: unknown) => ({ id, kind, state: "done", progress: null, result, error: null });

test("relocation tab lists entries, then plans, confirms and runs a move", async ({ page }) => {
  const jobPolls: Record<string, number> = { p1: 0, r1: 0 };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data: unknown = {};
    if (path === "/api/cleanup/relocation") data = STATUS;
    else if (path === "/api/cleanup/relocation/plan") {
      data = runningJob("p1", "relocation-plan");
    } else if (path === "/api/cleanup/relocation/run") {
      data = runningJob("r1", "relocation-run");
    } else if (path === "/api/cleanup/jobs/p1") {
      jobPolls.p1 += 1;
      data = jobPolls.p1 === 1 ? runningJob("p1", "relocation-plan") : doneJob("p1", "relocation-plan", PLAN);
    } else if (path === "/api/cleanup/jobs/r1") {
      jobPolls.r1 += 1;
      data = jobPolls.r1 === 1 ? runningJob("r1", "relocation-run") : doneJob("r1", "relocation-run", RUN);
    } else if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });

  await page.goto("/cleanup/relocation/");
  await expect(page.getByRole("heading", { name: "Cleanup Lab" }).first()).toBeVisible();
  await expect(page.getByText("Gradle caches")).toBeVisible();
  await expect(page.getByText("Go build cache")).toBeVisible();
  await expect(page.getByText("A previous move was interrupted; resume it before starting a new one.")).toHaveCount(0);
  await expect(page.getByLabel("Destination")).toHaveValue("/");

  // Plan the move: the destination select defaults to the first volume; switch to the second.
  await page.getByLabel("Destination").selectOption("/Volumes/Ext");
  await page.getByRole("button", { name: "Move", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Confirm relocation")).toBeVisible();
  await expect(dialog.getByText("Gradle caches")).toBeVisible();
  await expect(dialog.getByText("This replaces the folder with a link to the copy on the destination volume.")).toBeVisible();

  // Nothing runs until the dialog's Run is clicked; Back closes without running.
  await dialog.getByRole("button", { name: "Back" }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Run relocation" }).click();
  await expect(page.getByText("Relocated")).toBeVisible();
  await expect(page.getByText("/Volumes/Ext/oslab-caches/developers.gradle").first()).toBeVisible();
});

test("an interrupted move shows the resume-first banner", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = {};
    if (path === "/api/cleanup/relocation") data = {
      ...STATUS,
      entries: [{ ...STATUS.entries[0], interrupted: true }]
    };
    else if (path === "/api/cleanup/status") data = { state: "ready", reasons: [], requirements: [], capabilities: [] };
    else if (path === "/api/cleanup/catalog") data = { platform: "macos", entries: [] };
    else if (path === "/api/cleanup/jobs") data = { jobs: [] };
    else if (path === "/api/cleanup/permissions") data = { platform: "macos", permissions: [] };
    else if (path === "/api/cleanup/history") data = { entries: [], total: 0, verified: true };
    else if (path === "/api/host") data = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/tmp", tools: [], providers: [] }, labs: [] };
    else if (path === "/api/health") data = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") data = { jobs: [] };
    else if (path === "/api/logs") data = { logs: [] };
    await route.fulfill({ json: data });
  });
  await page.goto("/cleanup/relocation/");
  await expect(page.getByText("A previous move was interrupted; resume it before starting a new one.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Resume interrupted move" })).toBeVisible();
});
