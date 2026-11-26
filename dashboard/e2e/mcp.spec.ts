import { expect, test } from "@playwright/test";

/** The app shell reads the host fields, so every mocked console reports them. */
const HOST = { host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "t", cpus: 8, memory: 0, disk: null, kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null, python: "3.12", root: "/Volumes/Projects/iQ/os-lab", tools: [], providers: [] }, labs: [] };

test("MCP guides page shows the four tool groups and fills the repo path", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/api/host") {
      body = HOST;
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
  await expect(page.locator("#mcp-claude-plugin").getByText("python3 /Volumes/Projects/iQ/os-lab/scripts/claude-plugin.py install")).toBeVisible();
  await expect(page.locator("#mcp-codex-cards").getByText("python3 /Volumes/Projects/iQ/os-lab/scripts/codex-plugin.py install")).toBeVisible();
  await expect(page.locator("#mcp-cursor-cards").getByText("python3 /Volumes/Projects/iQ/os-lab/scripts/cursor-plugin.py install")).toBeVisible();
  await expect(page.locator("#mcp-zcode-cards").getByText("python3 /Volumes/Projects/iQ/os-lab/scripts/zcode-plugin.py install")).toBeVisible();
  await expect(page.locator("#mcp-grok-cards").getByText("python3 /Volumes/Projects/iQ/os-lab/scripts/grok-plugin.py install")).toBeVisible();
  await expect(page.locator("#mcp-plugin").getByText("plugin_apply", { exact: true })).toBeVisible();
  await expect(page.locator("#mcp-codex-plugin").getByText("codex_plugin_apply", { exact: true })).toBeVisible();
  await expect(page.locator("#mcp-cursor-plugin").getByText("cursor_plugin_apply", { exact: true })).toBeVisible();
  await expect(page.getByText("macos_stop", { exact: true })).toBeVisible();
  await expect(page.getByText("macos_request_access", { exact: true })).toBeVisible();
  await expect(page.getByText("cleanup_clean", { exact: true })).toBeVisible();
  await expect(page.getByText("cleanup_app_overview", { exact: true })).toBeVisible();
  await expect(page.getByText("websec_scan", { exact: true })).toBeVisible();
  await expect(page.getByText("winapps_apps", { exact: true })).toBeVisible();
  await expect(setup.getByText("Codex", { exact: true })).toBeVisible();
  await expect(page.getByText("proof: —").first()).toBeVisible();
});

test("MCP plugin cards preview a change and run it only after Confirm", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  let installed: { scope: string; version: string; enabled: boolean }[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") posts.push({ path, body: route.request().postDataJSON() });
    let body: unknown = {};
    if (path === "/api/host") body = HOST;
    else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    else if (path === "/api/claude-plugin") body = {
      checkoutVersion: "0.2.0",
      doctor: { ready: true, checks: [] },
      code: { cli: "2.1.332", installed, duplicates: [] },
      desktop: { app: { installed: true }, extension: { installed: true, version: "0.1.0", updateAvailable: true, duplicates: [] } }
    };
    else if (path === "/api/claude-plugin/preview") body = { token: "t1", action: "install", commands: ["claude plugin install os-lab@os-lab"], manual: [], warnings: [] };
    else if (path === "/api/claude-plugin/apply") {
      installed = [{ scope: "user", version: "0.2.0", enabled: true }];
      body = { ok: true, next: "Restart Claude Code or run /reload-plugins, then verify.", steps: [] };
    } else if (path === "/api/claude-plugin/check") body = { updatesAvailable: ["claude-desktop"], published: { version: "0.2.0", updateAvailable: false } };
    await route.fulfill({ json: body });
  });
  await page.goto("/mcp/");
  const code = page.locator("#mcp-card-code");
  await expect(code.getByText("Not installed")).toBeVisible();
  await expect(page.locator("#mcp-card-desktop").getByRole("button", { name: "Update extension" })).toBeEnabled();
  await code.getByRole("button", { name: "Install plugin" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("claude plugin install os-lab@os-lab")).toBeVisible();
  expect(posts.map((post) => post.path)).not.toContain("/api/claude-plugin/apply");
  await dialog.getByRole("button", { name: "Confirm and run" }).click();
  await expect(code.getByText("Installed", { exact: true })).toBeVisible();
  expect(posts.find((post) => post.path === "/api/claude-plugin/apply")?.body).toEqual({ token: "t1", confirm: true });
  await page.locator("#mcp-card-updates").getByRole("button", { name: "Check for updates" }).click();
  await expect(page.locator("#mcp-card-updates").getByText("claude-desktop")).toBeVisible();
});

test("MCP plugin cards fall back to the terminal command without the console", async ({ page }) => {
  await page.route("**/api/**", (route) => route.fulfill({ status: 503, json: { error: "Console offline" } }));
  await page.goto("/mcp/");
  const section = page.locator("#mcp-claude-plugin");
  await expect(section.getByText("scripts/claude-plugin.py install")).toBeVisible();
  await expect(section.getByRole("button", { name: "Try again" })).toBeVisible();
  const codex = page.locator("#mcp-codex-cards");
  await expect(codex.getByText("scripts/codex-plugin.py install")).toBeVisible();
  await expect(codex.getByRole("button", { name: "Try again" })).toBeVisible();
  const cursor = page.locator("#mcp-cursor-cards");
  await expect(cursor.getByText("scripts/cursor-plugin.py install")).toBeVisible();
  await expect(cursor.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("MCP Codex plugin cards preview install commands without applying", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") posts.push({ path, body: route.request().postDataJSON() });
    let body: unknown = {};
    if (path === "/api/host") body = HOST;
    else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    else if (path === "/api/claude-plugin") body = {
      checkoutVersion: "0.2.0",
      doctor: { ready: true, checks: [] },
      code: { cli: "2.1.332", installed: [], duplicates: [] },
      desktop: { app: { installed: true }, extension: { installed: false, version: null, updateAvailable: false, duplicates: [] } }
    };
    else if (path === "/api/codex-plugin") body = {
      checkoutVersion: "0.2.0",
      terminalCommand: "python3 scripts/codex-plugin.py install",
      doctor: { ready: true, checks: [] },
      codex: { cli: "/usr/bin/codex", installed: false, duplicates: [] }
    };
    else if (path === "/api/codex-plugin/preview") body = {
      token: "c1", action: "install", commands: ["codex plugin marketplace add /repo"],
      warnings: [], terminalCommand: "python3 scripts/codex-plugin.py install"
    };
    else if (path === "/api/cursor-plugin" || path === "/api/zcode-plugin" || path === "/api/grok-plugin") {
      const host = path.split("/")[2].replace("-plugin", "");
      body = {
        host,
        checkoutVersion: "0.1.0",
        terminalCommand: `python3 scripts/${host}-plugin.py install`,
        doctor: { ready: true, checks: [] },
        install: { cli: null, installed: false, duplicates: [] }
      };
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/mcp/");
  const card = page.locator("#mcp-card-codex");
  await expect(card.getByText("Not installed")).toBeVisible();
  await card.getByRole("button", { name: "Preview install" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("codex plugin marketplace add /repo")).toBeVisible();
  await expect(dialog.getByText("scripts/codex-plugin.py install")).toBeVisible();
  expect(posts.map((post) => post.path)).not.toContain("/api/codex-plugin/apply");
  await dialog.getByRole("button", { name: "Close" }).click();
});

test("MCP host plugin cards preview Cursor install without applying", async ({ page }) => {
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") posts.push({ path, body: route.request().postDataJSON() });
    let body: unknown = {};
    if (path === "/api/host") body = HOST;
    else if (path === "/api/health") body = { status: "ok", version: "test", console: true };
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/logs") body = { logs: [] };
    else if (path === "/api/claude-plugin") body = {
      checkoutVersion: "0.2.0",
      doctor: { ready: true, checks: [] },
      code: { cli: "2.1.332", installed: [], duplicates: [] },
      desktop: { app: { installed: true }, extension: { installed: false, version: null, updateAvailable: false, duplicates: [] } }
    };
    else if (path === "/api/codex-plugin") body = {
      checkoutVersion: "0.2.0",
      terminalCommand: "python3 scripts/codex-plugin.py install",
      doctor: { ready: true, checks: [] },
      codex: { cli: "/usr/bin/codex", installed: false, duplicates: [] }
    };
    else if (path === "/api/cursor-plugin") body = {
      host: "cursor",
      checkoutVersion: "0.1.0",
      terminalCommand: "python3 scripts/cursor-plugin.py install",
      doctor: { ready: true, checks: [] },
      install: { cli: null, installed: false, duplicates: [] }
    };
    else if (path === "/api/cursor-plugin/preview") body = {
      token: "h1", action: "install",
      commands: ["python3 scripts/cursor-plugin.py install  # writes .cursor/mcp.json"],
      warnings: [], terminalCommand: "python3 scripts/cursor-plugin.py install"
    };
    else if (path === "/api/zcode-plugin" || path === "/api/grok-plugin") {
      const host = path.includes("zcode") ? "zcode" : "grok";
      body = {
        host,
        checkoutVersion: "0.1.0",
        terminalCommand: `python3 scripts/${host}-plugin.py install`,
        doctor: { ready: true, checks: [] },
        install: { cli: null, installed: false, duplicates: [] }
      };
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/mcp/");
  const card = page.locator("#mcp-card-cursor");
  await expect(card.getByText("Not installed")).toBeVisible();
  await card.getByRole("button", { name: "Preview install" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("scripts/cursor-plugin.py install")).toBeVisible();
  expect(posts.map((post) => post.path)).not.toContain("/api/cursor-plugin/apply");
  await dialog.getByRole("button", { name: "Close" }).click();
});
