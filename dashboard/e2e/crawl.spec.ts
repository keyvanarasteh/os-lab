import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "@playwright/test";

// Plan item F: full-page screenshots of the selected routes, locales and widths, plus an
// HTML index for reviewing layout changes. Only runs with OSLAB_CRAWL=1 (scripts/e2e.sh --crawl);
// playwright.config.ts ignores this file otherwise. There is no console behind the static
// server, so every /api call fails and pages show their offline state, as on GitHub Pages.

const MAIN_ROUTES = [
  "/", "/health/", "/jobs/", "/content/", "/contribute/", "/feedback/", "/how-to-use/",
  "/android/", "/android/console/", "/cleanup/", "/cleanup/scan/", "/cleanup/settings/",
  "/firewall/", "/source/", "/source/analyzer/", "/web-lab/",
  "/labs/ios/", "/labs/macos/", "/labs/windows/", "/labs/winapps/", "/labs/linux/", "/legal/privacy/"
];
const LOCALES = ["en", "ar", "de", "es", "fa", "fr", "it", "tr"];
const WIDTHS: Record<string, { width: number; height: number }> = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844 }
};

const list = (value: string | undefined) => (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
const routes = list(process.env.OSLAB_CRAWL_ROUTES).length ? list(process.env.OSLAB_CRAWL_ROUTES) : MAIN_ROUTES;
const localeArg = list(process.env.OSLAB_CRAWL_LOCALES);
const locales = localeArg.includes("all") ? LOCALES : localeArg.length ? localeArg : ["en"];
const widths = list(process.env.OSLAB_CRAWL_WIDTHS).length ? list(process.env.OSLAB_CRAWL_WIDTHS) : ["desktop"];
const out = join(process.env.OSLAB_E2E_OUT ?? "test-results/crawl", "crawl");

for (const width of widths) {
  if (!WIDTHS[width]) throw new Error(`unknown width "${width}"; use ${Object.keys(WIDTHS).join(", ")}`);
}
for (const locale of locales) {
  if (!LOCALES.includes(locale)) throw new Error(`unknown locale "${locale}"; use ${LOCALES.join(", ")} or all`);
}

const localized = (route: string, locale: string) => (locale === "en" ? route : `/${locale}${route}`);
const fileName = (route: string, locale: string, width: string) =>
  `${locale}-${width}-${route.replace(/^\/|\/$/g, "").replace(/[^a-z0-9]+/gi, "_") || "home"}.png`;

test.describe.configure({ mode: "parallel" });

const shots: { route: string; locale: string; width: string; file: string; status: string }[] = [];

for (const width of widths) {
  for (const locale of locales) {
    for (const route of routes) {
      test(`crawl ${locale} ${width} ${route}`, async ({ page }) => {
        await page.route("**/api/**", (call) => call.abort());
        await page.setViewportSize(WIDTHS[width]);
        const response = await page.goto(localized(route, locale));
        await page.waitForLoadState("networkidle").catch(() => undefined);
        mkdirSync(out, { recursive: true });
        const file = fileName(route, locale, width);
        await page.screenshot({ path: join(out, file), fullPage: true });
        shots.push({ route, locale, width, file, status: String(response?.status() ?? "none") });
      });
    }
  }
}

test.afterAll(() => {
  if (!shots.length) return;
  mkdirSync(out, { recursive: true });
  // Each worker writes its own part; scripts/e2e.sh joins the parts into index.html.
  writeFileSync(join(out, `part-${process.pid}.json`), JSON.stringify(shots));
});
