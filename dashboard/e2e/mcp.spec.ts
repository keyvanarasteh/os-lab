import { expect, test, type Page } from "@playwright/test";
import type { McpPlan, McpStatus } from "../src/lib/api";

// MCP-01: the MCP servers page shows which clients have os-lab's servers, and
// Connect previews the exact change before it is applied with the preview token.

const status = (registered = false): McpStatus => ({
  servers: [{ id: "macos", name: "os-lab-macos", label: "macOS Lab", description: "Observe, act, verify and stop on this Mac's app windows. Input tools need armed control mode.", command: ["/usr/bin/python3", "/repo/console/mcp_server.py"] }],
  clients: [
    { id: "claude-code", label: "Claude Code", kind: "cli", installed: true, binary: "/usr/local/bin/claude", registered: { macos: false } },
    { id: "codex", label: "Codex CLI", kind: "cli", installed: false, binary: null, registered: { macos: false } },
    { id: "claude-desktop", label: "Claude Desktop", kind: "json", installed: false, config: null, registered: { macos: false } },
    { id: "cursor", label: "Cursor", kind: "json", installed: true, config: "/home/me/.cursor/mcp.json", registered: { macos: registered } }
  ]
});

const plans: Record<string, McpPlan> = {
  "claude-code": { server: "macos", client: "claude-code", name: "os-lab-macos", kind: "cli", replaces: false,
    argv: ["/usr/local/bin/claude", "mcp", "add", "--scope", "user", "os-lab-macos", "--", "/usr/bin/python3", "/repo/console/mcp_server.py"] },
  cursor: { server: "macos", client: "cursor", name: "os-lab-macos", kind: "json", replaces: false, file: "/home/me/.cursor/mcp.json",
    entry: { type: "stdio", command: "/usr/bin/python3", args: ["/repo/console/mcp_server.py"] } }
};

async function mockApi(page: Page) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  let connected = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.method() === "POST" ? (request.postDataJSON() ?? {}) as Record<string, unknown> : {};
    // Only the page's own requests: the shell posts its content check too.
    if (request.method() === "POST" && path.startsWith("/api/mcp/")) calls.push({ path, body });
    if (path === "/api/mcp") return route.fulfill({ json: status(connected) });
    if (path === "/api/mcp/preview") return route.fulfill({ json: { plan: plans[String(body.client)], token: `token-${body.client}` } });
    if (path === "/api/mcp/connect") {
      if (body.token !== `token-${body.client}`) return route.fulfill({ status: 409, json: { error: "The client configuration changed since the preview; preview again" } });
      connected = true;
      return route.fulfill({ json: { ok: true, file: "/home/me/.cursor/mcp.json" } });
    }
    if (path === "/api/jobs") return route.fulfill({ json: { jobs: [] } });
    if (path === "/api/host") return route.fulfill({ json: {
      host: { os: "macos", osPretty: "macOS", arch: "arm64", hostname: "test-host", cpus: 8, memory: null, disk: null,
        kvm: { present: false, usable: false }, wsl: { guest: false, distributions: [] }, runtime: null, xcode: null,
        python: "3.12", root: "/repo", tools: [], providers: [] },
      labs: []
    } });
    return route.fulfill({ json: {} });
  });
  return calls;
}

test("the MCP page lists clients and connects only after the preview is confirmed", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/mcp/");
  const card = page.locator("#mcp-macos");
  await expect(card.locator('[data-mcp-client="codex"]')).toContainText("Not installed");
  await expect(card.locator('[data-mcp-client="codex"] button')).toBeDisabled();
  await card.locator('[data-mcp-client="cursor"]').getByRole("button", { name: "Connect" }).click();

  const dialog = page.getByRole("dialog", { name: "Connect macOS Lab" });
  await expect(dialog.locator('[data-mcp-plan="json"]')).toContainText("/home/me/.cursor/mcp.json");
  await expect(dialog.locator('[data-mcp-plan="json"]')).toContainText('"os-lab-macos"');
  expect(calls.map((c) => c.path)).toEqual(["/api/mcp/preview"]);

  await dialog.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("macOS Lab is connected to Cursor.", { exact: false })).toBeVisible();
  expect(calls.at(-1)).toEqual({ path: "/api/mcp/connect", body: { server: "macos", client: "cursor", token: "token-cursor" } });
  await expect(card.locator('[data-mcp-client="cursor"]')).toContainText("Connected");
});

test("an oslab://mcp/connect URL opens the dialog with the client preselected, and applies nothing", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/mcp/?connect=macos&client=claude-code");
  const dialog = page.getByRole("dialog", { name: "Connect macOS Lab" });
  await expect(dialog.locator('[data-mcp-plan="cli"]')).toContainText("mcp add --scope user os-lab-macos --");
  await expect(dialog.getByLabel("MCP client")).toHaveValue("claude-code");
  expect(calls.map((c) => c.path)).toEqual(["/api/mcp/preview"]);
  // The request is consumed: a reload does not reopen the dialog.
  await expect(page).toHaveURL(/\/mcp\/$/);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(calls.some((c) => c.path === "/api/mcp/connect")).toBe(false);
});

test("an unknown server or client in the URL is reported, not guessed at", async ({ page }) => {
  await mockApi(page);
  await page.goto("/mcp/?connect=macos&client=evil");
  await expect(page.getByRole("alert")).toContainText("That MCP server or client is not available");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
