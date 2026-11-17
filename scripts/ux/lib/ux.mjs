// Reusable UX-check library: one headless Chromium, one page, named checks, screenshots and an
// exit code. Suites in scripts/ux/suites use it; any other UX test can import it too.
// @lat: [[development#UX check library]]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(HERE, "../../..");

/** Load Playwright from the dashboard's node_modules (or OSLAB_PLAYWRIGHT) and point it at the shared browser cache. */
export async function loadPlaywright() {
  const entry = process.env.OSLAB_PLAYWRIGHT ?? path.join(REPO, "dashboard/node_modules/playwright/index.mjs");
  if (!fs.existsSync(entry)) throw new Error(`Playwright not found at ${entry}; run scripts/worktree.sh doctor`);
  if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
    const cache = process.env.OSLAB_CACHE_ROOT ?? path.join(process.env.HOME ?? "", ".cache/os-lab");
    process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(cache, "playwright");
  }
  return import(pathToFileURL(entry).href);
}

/** True when a bounding box lies fully inside the viewport. */
export function boxInViewport(box, viewport) {
  return !!box && box.y >= 0 && box.x >= 0 && box.y + box.height <= viewport.height && box.x + box.width <= viewport.width;
}

/** Collects named pass/fail checks and prints them as it goes. */
export class CheckLog {
  constructor(print = console.log) { this.items = []; this.print = print; }
  ok(name, pass, info = "") {
    this.items.push({ name, pass: !!pass, info: String(info) });
    this.print(`${pass ? "PASS" : "FAIL"} ${name}${info ? " " + info : ""}`);
    return !!pass;
  }
  get failed() { return this.items.filter((item) => !item.pass); }
  summary() { return `${this.items.length - this.failed.length}/${this.items.length} passed`; }
  toJSON() { return this.items; }
}

/**
 * One browser session against a running dashboard.
 *   const ux = await UxSession.open({ base: "http://localhost:4321", out: "test-results/ux" });
 *   await ux.goto("/cleanup/", { waitFor: "text=This computer's storage" });
 *   ux.check("page hydrates", await ux.visible(ux.page.getByText("Cleanup Lab")));
 *   await ux.shot("cleanup");
 *   process.exit(await ux.close());
 */
export class UxSession {
  static async open({ base = "http://localhost:4321", out = path.join(REPO, "test-results/ux"), viewport = { width: 1400, height: 900 }, headless = true } = {}) {
    const { chromium } = await loadPlaywright();
    const browser = await chromium.launch({ headless });
    const context = await browser.newContext({ viewport });
    const session = new UxSession(browser, context, await context.newPage(), { base, out, viewport });
    fs.rmSync(path.join(out, "shots"), { recursive: true, force: true }); // stale shots of an earlier run would be misleading
    fs.mkdirSync(path.join(out, "shots"), { recursive: true });
    return session;
  }

  constructor(browser, context, page, { base, out, viewport }) {
    Object.assign(this, { browser, context, page, base, out, viewport });
    this.log = new CheckLog();
    this.errors = [];
    this.requests = [];
    this.shots = [];
    page.on("console", (message) => { if (message.type() === "error") this.errors.push(message.text()); });
    page.on("pageerror", (error) => this.errors.push(`pageerror ${error.message}`));
    page.on("request", (request) => {
      if (request.method() !== "GET") this.requests.push({ method: request.method(), url: request.url(), body: request.postData() ?? "" });
    });
  }

  check(name, pass, info = "") { return this.log.ok(name, pass, info); }

  /** Navigate and optionally wait for a selector (the app hydrates after load) plus a short settle. */
  async goto(route, { waitFor, timeout = 20000, settle = 800 } = {}) {
    await this.page.goto(route.startsWith("http") ? route : this.base + route);
    if (waitFor) await this.page.waitForSelector(waitFor, { timeout }).catch(() => {});
    await this.page.waitForTimeout(settle);
  }

  settle(ms = 800) { return this.page.waitForTimeout(ms); }
  async visible(locator) { return locator.first().isVisible().catch(() => false); }
  async setViewport(width, height) { this.viewport = { width, height }; await this.page.setViewportSize(this.viewport); await this.settle(400); }

  /** Is the locator fully inside the current viewport (for sticky/pinned controls after scrolling)? */
  async inViewport(locator) { return boxInViewport(await locator.first().boundingBox(), this.viewport); }
  async scrollToBottom() { await this.page.mouse.wheel(0, 100000); await this.settle(500); }

  /** How many elements share the first element's row (grid column count). */
  async columnsInRow(selector) {
    return this.page.locator(selector).evaluateAll((els) => {
      if (!els.length) return 0;
      const top = els[0].getBoundingClientRect().top;
      return els.filter((el) => Math.abs(el.getBoundingClientRect().top - top) < 4).length;
    });
  }

  /** Non-GET requests whose URL contains `fragment`, with their JSON bodies. */
  requestsTo(fragment) { return this.requests.filter((request) => request.url.includes(fragment)); }

  /** Console/page errors, minus noise that is not a regression. */
  consoleErrors(ignore = [/favicon/, /status of 404/]) { return this.errors.filter((text) => !ignore.some((re) => re.test(text))); }

  /** Save a PNG under <out>/shots (a locator crops to that element). Returns the file path. */
  async shot(name, { locator, fullPage = false } = {}) {
    const file = path.join(this.out, "shots", `${String(this.shots.length + 1).padStart(2, "0")}-${name}.png`);
    if (locator) await locator.first().screenshot({ path: file }); else await this.page.screenshot({ path: file, fullPage });
    this.shots.push(file);
    return file;
  }

  /** Close the browser, write <out>/report.json and return the process exit code (0 when every check passed). */
  async close() {
    await this.browser.close();
    fs.writeFileSync(path.join(this.out, "report.json"), JSON.stringify({ base: this.base, checks: this.log, shots: this.shots, errors: this.errors }, null, 2));
    this.log.print(this.log.summary());
    return this.log.failed.length ? 1 : 0;
  }
}
