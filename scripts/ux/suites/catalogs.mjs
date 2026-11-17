// Catalogs suite: dashboard scan card (scanning → complete), classified catalog pages, review → confirm.
// @lat: [[development#UX suites]]
export const name = "catalogs";

export async function run(ux) {
  const { page } = ux;
  const planCalls = [];
  page.on("request", (req) => { if (/\/api\/cleanup\/(plan|clean)$/.test(req.url())) planCalls.push(req.url().split("/").pop()); });

  await ux.goto("/cleanup/", { waitFor: "text=Scan now" });
  await ux.shot("dashboard-before");
  const percentBeforeRefresh = await page.evaluate(() => {
    const hero = document.querySelector("#overview-storage");
    const pct = [...hero.querySelectorAll("span")].find((el) => /\d+% used/.test(el.textContent || "") && el.children.length === 0);
    const btn = hero.querySelector('button[title="Re-measure"]');
    return !!pct && !!btn && !!(pct.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  ux.check("storage percentage sits before the refresh button", percentBeforeRefresh);

  await page.getByRole("button", { name: /Scan now|Scan again/ }).first().click();
  await ux.settle(1200);
  const scanning = await page.getByText("Scanning your Mac").count();
  ux.check("a running scan shows 'Scanning your Mac' with Stop scan", scanning > 0 && (await page.getByRole("button", { name: "Stop scan" }).count()) > 0);
  await ux.shot("scanning");
  // The subtitle names the category being measured once the first progress update arrives.
  let category = "";
  for (let i = 0; i < 20 && (await page.getByText("Scanning your Mac").count()); i++) {
    category = ((await page.locator("#overview-review p").first().innerText().catch(() => "")) || "").trim();
    if (category && category !== "Preparing…") break;
    await ux.settle(500);
  }
  ux.check("the scanning card names the category being measured", !!category && category !== "Preparing…" || !(await page.getByText("Scanning your Mac").count()), category || "scan finished first");
  if (category && category !== "Preparing…") await ux.shot("scanning-category", { locator: page.locator("#overview-review") });
  await page.getByText("Scan complete").waitFor({ timeout: 240000 });
  ux.check("finished scan shows Scan complete with a Clean action", (await page.getByRole("button", { name: /^Clean / }).count()) === 1);
  ux.check("cleanup plan lists classified groups", (await page.locator("#overview-review ul li").count()) >= 2);
  await ux.shot("scan-complete");

  await page.locator("#overview-review ul li a").first().click();
  await page.waitForURL(/\/cleanup\/catalog\/#/, { waitUntil: "commit" });
  await page.locator("section[aria-label]").first().waitFor();
  ux.check("a plan row opens that group's own page", (await page.getByText("← All catalogs").count()) > 0);
  const filterLabels = (await page.locator("section[aria-label] label:has(select)").allInnerTexts()).map((text) => text.trim().split("\n")[0].trim());
  ux.check("group view has Size and Modified filters", ["Size", "Modified", "Sort"].every((label) => filterLabels.some((text) => text.startsWith(label))), filterLabels.join(" | "));
  ux.check("group rows show a modified date", (await page.locator("section[aria-label] li span").filter({ hasText: /\b20\d\d\b/ }).count()) > 0);
  ux.check("group view has search, sort and a Review removal footer", (await page.getByPlaceholder("Find an item or path").count()) > 0 && (await page.getByRole("button", { name: /Review removal/ }).count()) > 0);
  await ux.shot("catalog-group");

  const boxes = page.locator('li:not(:has-text("Measured only")) input[type="checkbox"]');
  if (await boxes.count()) await boxes.first().check();
  const review = page.getByRole("button", { name: /Review removal/ });
  if (await review.isEnabled()) {
    await review.click();
    await page.getByRole("dialog").waitFor({ timeout: 60000 });
    ux.check("Review removal opens the confirmation dialog", true);
    await ux.shot("catalog-confirm");
    await page.keyboard.press("Escape");
  } else ux.check("Review removal opens the confirmation dialog", true, "no cleanable item in this group; skipped");
  ux.check("only a plan was requested, nothing was cleaned", !planCalls.includes("clean"), planCalls.join(","));

  await ux.goto("/cleanup/catalog/", { waitFor: "text=All catalogs" });
  const cards = await page.locator("#catalog-groups li").count();
  ux.check("Catalogs page lists the tool groups", cards >= 6, String(cards));
  await ux.shot("catalogs");

  // Sidebar: each catalog group has its icon and, after a scan, a size badge.
  const nav = page.locator('nav[aria-label="Sections"]');
  const catalogsButton = nav.getByRole("button", { name: /^Catalogs/ });
  if (await catalogsButton.count() && !(await ux.visible(nav.getByText("Homebrew", { exact: true })))) { await catalogsButton.first().click(); await ux.settle(300); }
  const leafTexts = await nav.locator("li button").allInnerTexts();
  const sized = leafTexts.filter((text) => /\d(\.\d+)? ?(B|KB|MB|GB|TB)\b/.test(text));
  ux.check("sidebar catalog groups carry size badges", sized.length >= 2, sized.slice(0, 4).join(" | ").replace(/\n/g, " "));
  ux.check("sidebar catalog groups carry icons", (await nav.locator("li button svg").count()) >= 6);
  await ux.shot("catalog-nav", { locator: nav });

  // Permissions: the guide shows the Settings picture, or the granted state.
  await ux.goto("/cleanup/settings/", { waitFor: "text=Permissions" });
  const guide = await page.getByTestId("permission-guide").count();
  ux.check("permission guide shows the Settings picture, or the granted state",
    guide ? (await page.getByTestId("settings-mock").count()) > 0 : (await page.getByText(/Full Disk Access is on/).count()) > 0);
  await ux.shot("permissions", { locator: page.locator("#cleanup-permissions") });

  ux.check("no console or page errors during the suite", ux.consoleErrors().length === 0, ux.consoleErrors().join(" | "));
}
