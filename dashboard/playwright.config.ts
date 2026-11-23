import { defineConfig, devices } from "@playwright/test";

// Every setting below can be changed from the environment, so a plain `npx playwright test`
// and scripts/e2e.sh follow the same defaults. scripts/e2e.sh sets these variables from its
// arguments; see `scripts/e2e.sh --help` and lat.md/tooling.md#Parallel work.
const env = process.env;
const port = Number(env.OSLAB_E2E_PORT ?? 4322);
// Two browsers by default: Playwright otherwise starts one per CPU core, and two or three
// agents running at once overloaded the machine (plan item A).
const workers = env.OSLAB_E2E_WORKERS ? Number(env.OSLAB_E2E_WORKERS) : 2;
// Reuse a server that is already on the port only when asked. Reusing by default made one
// worktree's run test another worktree's build.
const reuse = env.OSLAB_E2E_REUSE === "1";
const pick = <T extends string>(value: string | undefined, allowed: readonly T[], fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback;
const screenshot = pick(env.OSLAB_E2E_SCREENSHOTS, ["off", "on", "only-on-failure"] as const, "only-on-failure");
const trace = pick(env.OSLAB_E2E_TRACE, ["off", "on", "retain-on-failure"] as const, "retain-on-failure");
const video = pick(env.OSLAB_E2E_VIDEO, ["off", "retain-on-failure"] as const, "off");
const out = env.OSLAB_E2E_OUT;
// The folder the web server serves: dist/ by default (CI builds it), dashboard/.e2e-dist when
// scripts/e2e.sh runs, so local test builds never rewrite the committed dist/.
const served = env.OSLAB_E2E_DIST ?? "dist";
// The crawl spec (plan item F) saves full-page screenshots; it only runs when asked.
const crawl = env.OSLAB_CRAWL === "1";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: crawl ? [] : ["**/crawl.spec.ts"],
  timeout: 30_000,
  retries: env.CI ? 1 : 0,
  workers,
  outputDir: out ? `${out}/artifacts` : undefined,
  reporter: env.CI
    ? [["list"], ["blob", { outputDir: out ? `${out}/blob-report` : "blob-report" }]]
    : [["list"], ["html", { open: "never", outputFolder: out ? `${out}/report` : "playwright-report" }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    ...devices["Desktop Chrome"],
    screenshot,
    trace,
    video
  },
  webServer: {
    // Windows names the interpreter python; POSIX toolchains commonly provide python3.
    command: `${process.platform === "win32" ? "python" : "python3"} -m http.server ${port} --bind 127.0.0.1 --directory ${JSON.stringify(served)}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: reuse,
    // http.server logs every request; OSLAB_E2E_SERVER_LOG=1 shows them.
    stderr: env.OSLAB_E2E_SERVER_LOG === "1" ? "pipe" : "ignore",
    timeout: 60_000
  }
});
