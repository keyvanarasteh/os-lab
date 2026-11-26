import { expect, test } from "@playwright/test";

test("MCP guides page shows the four tool groups and fills the repo path", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/host") {
      body = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "t", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/Volumes/Projects/iQ/os-lab", tools: [], providers: [] }, labs: [] };
    } else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    await route.fulfill({ json: body });
  });
  await page.goto("/mcp/");
  await expect(page.getByRole("main").getByRole("heading", { name: "MCP servers", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "MCP servers", exact: true })).toHaveAttribute("aria-current", "page");
  const setup = page.locator("#mcp-setup");
  await expect(setup.getByText("claude mcp add os-lab-macos -- python3 /Volumes/Projects/iQ/os-lab/console/mcp_server.py")).toBeVisible();
  await expect(page.locator("#mcp-macos")).toBeVisible();
  await expect(page.locator("#mcp-cleanup")).toBeVisible();
  await expect(page.locator("#mcp-websec")).toBeVisible();
  await expect(page.locator("#mcp-winapps")).toBeVisible();
  await expect(page.locator("#mcp-planned")).toBeVisible();
  await expect(page.getByText("macos_stop", { exact: true })).toBeVisible();
  await expect(page.getByText("macos_request_access", { exact: true })).toBeVisible();
  await expect(page.getByText("cleanup_clean", { exact: true })).toBeVisible();
  await expect(page.getByText("cleanup_app_overview", { exact: true })).toBeVisible();
  await expect(page.getByText("websec_scan", { exact: true })).toBeVisible();
  await expect(page.getByText("winapps_apps", { exact: true })).toBeVisible();
  await expect(setup.getByText("Codex", { exact: true })).toBeVisible();
  await expect(page.getByText("proof: —").first()).toBeVisible();
});
