// Cleanup Lab suite: storage volume cards, sticky Advanced scan toolbar, per-entry context menu.
// @lat: [[development#UX suites]]
export const name = "cleanup";

export async function run(ux) {
  const { page } = ux;

  // Storage card: grouped volume cards; APFS volumes of one container merge into one card.
  await ux.goto("/cleanup/", { waitFor: "summary:has-text('Other volumes')" });
  const others = page.locator("summary", { hasText: /Other volumes/ }).first();
  ux.check("Other volumes summary is present", (await others.count()) > 0);
  if (await others.count()) await others.click();
  await ux.settle(400);
  ux.check("volumes are grouped (Disks, System)", (await page.getByText(/^Disks/).count()) > 0 && (await page.getByText(/^System/).count()) > 0);
  ux.check("one APFS container is one card with its mount points", (await page.getByText(/\d+ mount points/).count()) > 0);
  await ux.shot("volumes", { locator: page.locator("#overview-storage") });

  // Advanced scan: one Scan selected button that stays reachable.
  await ux.goto("/cleanup/scan/", { waitFor: "text=User caches" });
  const scan = page.getByRole("button", { name: "Scan selected" });
  ux.check("exactly one Scan selected button", (await scan.count()) === 1, String(await scan.count()));
  await ux.scrollToBottom();
  ux.check("Scan selected stays in the viewport after scrolling to the bottom", await ux.inViewport(scan));
  await ux.shot("scan-scrolled");
  await ux.setViewport(390, 800);
  await page.mouse.wheel(0, 4000); await ux.settle(400);
  ux.check("Scan selected stays visible at phone width", await ux.inViewport(scan));
  await ux.shot("scan-phone");
  await ux.setViewport(1400, 900);

  // Entry grid and context menu.
  await ux.goto("/cleanup/scan/", { waitFor: "text=User caches" });
  const cards = 'label:has(input[type="checkbox"])';
  ux.check("catalog renders at least 80 entries", (await page.locator(cards).count()) >= 80, String(await page.locator(cards).count()));
  const columns = await ux.columnsInRow(cards);
  ux.check("compact grid shows at least 4 cards per row", columns >= 4, `columns=${columns}`);
  await ux.shot("compact-grid");

  const uv = page.locator("label:has-text('uv cache')").first();
  ux.check("new catalog entry 'uv cache' is listed", (await uv.count()) > 0);
  await uv.scrollIntoViewIfNeeded();
  await uv.click({ button: "right" });
  const menu = page.getByRole("menu");
  ux.check("right-click opens the entry menu", await menu.isVisible());
  const items = await menu.getByRole("menuitem").allInnerTexts();
  ux.check("menu offers scan, review & clean and select", ["Scan this entry", "Review & clean…", "Select only this"].every((text) => items.includes(text)), items.join(" | "));
  await ux.shot("context-menu");
  await page.keyboard.press("Escape");
  ux.check("Escape closes the menu", !(await menu.isVisible().catch(() => false)));
  await uv.getByRole("button", { name: /Actions for/ }).click();
  ux.check("the ⋯ button opens the same menu", await menu.isVisible());
  await menu.getByRole("menuitem", { name: "Scan this entry" }).click();
  await ux.settle(2500);
  ux.check("Scan this entry requests a scan of that one id", ux.requestsTo("/api/cleanup/scan").some((r) => r.body.includes("developers.uv") && !r.body.includes(",")));

  const agent = page.locator("label:has-text('Claude Code data')").first();
  await agent.scrollIntoViewIfNeeded();
  await agent.click({ button: "right" });
  const clean = menu.getByRole("menuitem", { name: /Review & clean/ });
  ux.check("measured-only entry: Review & clean is disabled with a reason", (await clean.isDisabled()) && /Measured only/.test((await clean.getAttribute("title")) ?? ""));
  await ux.shot("menu-disabled");
  await page.keyboard.press("Escape");

  const rembg = page.locator("label:has-text('rembg models')").first();
  await rembg.scrollIntoViewIfNeeded();
  await rembg.click({ button: "right" });
  await menu.getByRole("menuitem", { name: /Review & clean/ }).click();
  await page.waitForSelector("dialog[open]", { timeout: 15000 }).catch(() => {});
  ux.check("Review & clean opens the confirmation dialog", (await page.locator("dialog[open]").count()) > 0);
  await ux.shot("confirm-dialog");
  ux.check("only a plan was requested, nothing was cleaned", ux.requestsTo("/api/cleanup/plan").length > 0 && ux.requestsTo("/api/cleanup/clean").length === 0);
  const back = page.locator("dialog[open]").getByRole("button", { name: /Back|Cancel|Close/ }).first();
  if (await back.count()) await back.click(); else await page.keyboard.press("Escape");

  ux.check("no console or page errors during the suite", ux.consoleErrors().length === 0, ux.consoleErrors().slice(0, 2).join(" | ").slice(0, 200));

  // Permissions guide: the app tile, Settings and Finder actions, or the granted state.
  await ux.goto("/cleanup/settings/", { waitFor: "#cleanup-permissions" });
  const guide = page.locator("#cleanup-permissions");
  const granted = (await guide.getByText("Full Disk Access is on").count()) > 0;
  ux.check("permission guide shows its tile and actions, or the granted state",
    granted || ((await guide.getByTestId("permission-guide").getByRole("button", { name: "Open System Settings" }).count()) === 1 && (await guide.getByRole("button", { name: "Reveal app again" }).count()) === 1));
  await ux.shot("permission-guide", { locator: guide });
}
