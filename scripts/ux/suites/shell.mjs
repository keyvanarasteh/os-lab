// Shell suite: collapsible Help, lab switcher, focused-lab navigation.
// @lat: [[development#UX suites]]
export const name = "shell";

export async function run(ux) {
  const { page } = ux;
  const nav = () => page.locator('nav[aria-label="Sections"]');
  const links = async () => (await nav().locator("a, button").allInnerTexts()).map((text) => text.trim());
  const helpVisible = () => ux.visible(nav().getByText("Health check"));

  await ux.goto("/cleanup/", { waitFor: "text=This computer's storage" });
  const help = nav().getByRole("button", { name: /^Help/ });
  ux.check("Help is a collapsible button", (await help.count()) > 0);
  ux.check("Help is closed by default", !(await helpVisible()));
  await ux.shot("help-closed");
  await help.click(); await ux.settle(300);
  ux.check("Help opens with Health check, Legal and How to use", (await helpVisible()) && (await ux.visible(nav().getByText("Legal"))) && (await ux.visible(nav().getByText("How to use"))));
  await page.reload(); await ux.settle(1500);
  ux.check("Help state is remembered after a reload", await helpVisible());
  await nav().getByRole("button", { name: /^Help/ }).click(); await ux.settle(200);
  await ux.goto("/legal/privacy/");
  ux.check("Help opens by itself on a page inside it", await ux.visible(nav().getByText("Privacy Notice")));

  await ux.goto("/cleanup/", { waitFor: "text=This computer's storage" });
  const cleanupNav = await links();
  for (const label of ["Dashboard", "Settings", "Space Explorer", "Advanced scan", "Results", "Leftovers", "History", "Relocation"])
    ux.check(`Cleanup Lab nav has ${label}`, cleanupNav.some((text) => text.startsWith(label)));
  ux.check("focused lab replaces the OS Lab group", !(await nav().getByText("OS Lab", { exact: true }).count()) && (await nav().getByText("Cleanup Lab", { exact: true }).count()) > 0);
  await ux.shot("cleanup-nav");

  // Sub-navs: Settings is last, groups start closed, and a sub-nav link lands on its card.
  const order = cleanupNav.map((text) => text.split("\n")[0].trim());
  const top = ["Dashboard", "Space Explorer", "Advanced scan", "Results", "Leftovers", "History", "Relocation", "Settings"];
  ux.check("top-level order ends with Relocation then Settings", top.every((label, i) => i === 0 || order.indexOf(label) > order.indexOf(top[i - 1])), order.filter((t) => top.includes(t)).join(" > "));
  ux.check("sub-navs of other pages start collapsed", !(await ux.visible(nav().getByText("Plan & confirm", { exact: true }))) && !(await ux.visible(nav().getByText("Bookmarks", { exact: true }))));
  await nav().getByRole("button", { name: /^Advanced scan/ }).click(); await ux.settle(300);
  const scanKids = ["Catalog entries", "Plan & confirm", "Containers", "Virtual machines"];
  ux.check("opening Advanced scan lists its cards", (await Promise.all(scanKids.map((k) => ux.visible(nav().getByText(k, { exact: true }))))).every(Boolean));
  await ux.shot("subnav-open");
  await nav().getByText("Plan & confirm", { exact: true }).click();
  await page.waitForSelector("#scan-plan", { timeout: 20000 }).catch(() => {}); await ux.settle(1500);
  ux.check("the link goes to /cleanup/scan/#scan-plan", page.url().endsWith("/cleanup/scan/#scan-plan"), page.url());
  ux.check("the related card is targeted and on screen", (await page.evaluate(() => document.querySelector("[data-landed]")?.id)) === "scan-plan" && (await page.locator("#scan-plan").evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.top < window.innerHeight; })));
  await ux.shot("subnav-target");
  await nav().getByRole("button", { name: /^Settings/ }).click(); await ux.settle(300);
  await nav().getByText("Desktop widgets", { exact: true }).click();
  await page.waitForSelector("#cleanup-widgets", { timeout: 20000 }).catch(() => {}); await ux.settle(1500);
  ux.check("Settings > Desktop widgets lands on its card", page.url().endsWith("/cleanup/settings/#cleanup-widgets") && (await page.locator("#cleanup-widgets").evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.top < window.innerHeight; })));
  await ux.shot("settings-widgets");
  await ux.goto("/cleanup/", { waitFor: "text=This computer's storage" });

  await page.getByRole("button", { name: "Switch lab" }).click(); await ux.settle(500);
  const dialog = page.getByRole("dialog", { name: "Switch lab" });
  ux.check("switcher lists Firewall Lab", await ux.visible(dialog.getByText("Firewall Lab")));
  await ux.shot("switcher");
  await dialog.getByText("Firewall Lab").first().click(); await ux.settle(1500);
  const firewallNav = await links();
  ux.check("Firewall Lab shows its own group and nav", ["Overview", "Companies", "Add your company"].every((label) => firewallNav.includes(label)) && !(await nav().getByText("OS Lab", { exact: true }).count()));
  await ux.shot("firewall-focus");
  await page.getByRole("button", { name: "Switch lab" }).click(); await ux.settle(400);
  await page.getByRole("button", { name: "All labs" }).click(); await ux.settle(1500);
  ux.check("All labs restores OS Lab with Firewall Lab", (await nav().getByText("OS Lab", { exact: true }).count()) > 0 && (await nav().getByText("Firewall Lab").count()) > 0);
  await ux.shot("all-labs");
}
