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
