/**
 * The stdio MCP server in console/mcp_server.py: one process, tool groups,
 * verification slots (engine / widgets / apps), and host attach snippets.
 * Names and safety notes match the shipped tools; the page fills the repo path
 * from GET /api/host. Durable proofs live in console/mcp_verification.json.
 */
export type ToolSafety = "read-only" | "armed" | "confirm" | "panic" | "windows-only" | "write";

/** none = not started; pending = scaffolded; verified = proof filled; n/a = deliberate skip. */
export type VerifyStatus = "none" | "pending" | "verified" | "n/a";

export interface VerifySlot {
  status: VerifyStatus;
  /** PR link, test name, or artifact path — contributors fill this in PRs. */
  proof: string | null;
}

export interface McpTool {
  name: string;
  safety: ToolSafety;
  summary: string;
  engineUsage?: VerifySlot;
  widget?: VerifySlot;
  app?: VerifySlot;
}

export type McpGroupId =
  | "macos"
  | "cleanup"
  | "websec"
  | "winapps"
  | "android"
  | "ios"
  | "linux"
  | "web"
  | "source"
  | "firewall";

export interface McpGroup {
  id: McpGroupId;
  title: string;
  platform: string;
  docs: string;
  rules: string[];
  tools: McpTool[];
  /** Section-level verification (defaults pending/none). */
  engineUsage: VerifySlot;
  widgets: VerifySlot;
  apps: VerifySlot;
}

const pending = (): VerifySlot => ({ status: "pending", proof: null });
const none = (): VerifySlot => ({ status: "none", proof: null });

export const MCP_SERVER_FILE = "console/mcp_server.py";
export const MCP_MAKE_TARGET = "make -C ios-lab mac-mcp";
export const MCP_PLAN = "docs/PLAN-mcp-coverage.md";
export const MCP_VERIFICATION = "console/mcp_verification.json";
export const MCP_SKILLS = "console/mcp_skills";
export const MCP_PLUGINS = "plugins/mcp";

export function serverName(os?: string): "os-lab-macos" | "os-lab-windows" {
  return os === "windows" ? "os-lab-windows" : "os-lab-macos";
}

export function snippetPath(root: string | undefined): string {
  const base = (root || "<repo>").replace(/[/\\]+$/, "");
  return `${base}/${MCP_SERVER_FILE}`;
}

export function claudeCodeSnippet(root: string | undefined, os?: string): string {
  return `claude mcp add ${serverName(os)} -- python3 ${snippetPath(root)}`;
}

export function claudeDesktopSnippet(root: string | undefined, os?: string): string {
  const name = serverName(os);
  return JSON.stringify({
    mcpServers: {
      [name]: { command: "python3", args: [snippetPath(root)] }
    }
  }, null, 2);
}

export function codexSnippet(root: string | undefined): string {
  return `[mcp_servers.os-lab]\ncommand = "python3"\nargs = ["${snippetPath(root)}"]`;
}

export function cursorSnippet(root: string | undefined): string {
  return JSON.stringify({
    mcpServers: {
      "os-lab": { command: "python3", args: [snippetPath(root)] }
    }
  }, null, 2);
}

export function openCodeSnippet(root: string | undefined): string {
  return JSON.stringify({
    mcp: {
      "os-lab": { command: "python3", args: [snippetPath(root)] }
    }
  }, null, 2);
}

export function zcodeSnippet(root: string | undefined): string {
  return JSON.stringify({
    servers: {
      "os-lab": {
        transport: "stdio",
        command: "python3",
        args: [snippetPath(root)],
        skills: [`${(root || "<repo>").replace(/[/\\]+$/, "")}/${MCP_SKILLS}`]
      }
    }
  }, null, 2);
}

export function antigravitySnippet(root: string | undefined): string {
  return JSON.stringify({
    name: "os-lab",
    transport: "stdio",
    command: "python3",
    args: [snippetPath(root)],
    capabilities: ["tools", "resources", "prompts"],
    ui: { mimeTypes: ["text/html;profile=mcp-app"] }
  }, null, 2);
}

export function genericSnippet(): string {
  return MCP_MAKE_TARGET;
}

export const MCP_GROUPS: McpGroup[] = [
  {
    id: "macos",
    title: "macOS Lab",
    platform: "macOS",
    docs: "lat.md/ios-lab.md (MIR-12)",
    engineUsage: pending(),
    widgets: pending(),
    apps: none(),
    rules: [
      "Read-only tools always work.",
      "Input tools need the dashboard's armed control mode. There is no arm tool.",
      "macos_request_access opens the privacy pane; the human still grants.",
      "Enter, Return and paste need confirm: true even while armed.",
      "macos_stop is the panic stop: always safe to call.",
      "macos_task runs a bounded step list. Cleanup and Web Sec tools are refused inside it."
    ],
    tools: [
      { name: "macos_apps", safety: "read-only", summary: "Visible app windows: id, pid, app, title, rect.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "macos_get_app_state", safety: "read-only", summary: "Accessibility tree of one window, optional PNG.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_screenshot", safety: "read-only", summary: "PNG of one visible window (Screen Recording).", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_windows", safety: "read-only", summary: "AX window list of one app.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_menubar", safety: "read-only", summary: "Menu-bar tree of one app.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_search", safety: "read-only", summary: "Find elements by label, value or placeholder.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_displays", safety: "read-only", summary: "Active displays, origin, size, scale.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_capabilities", safety: "read-only", summary: "Engine, input kinds, keys, safety limits.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_permissions", safety: "read-only", summary: "Accessibility and Screen Recording state.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_request_access", safety: "write", summary: "Open privacy pane / consent prompt for a grant.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_focused", safety: "read-only", summary: "Focused AX element of one app (pid).", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_audit", safety: "read-only", summary: "Recent macOS Lab audit rows (no thumbnails).", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_sessions", safety: "read-only", summary: "Open deep-inspect sessions and Appium reachability.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_control_state", safety: "read-only", summary: "Whether control mode is armed, owner, remaining seconds.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "macos_click", safety: "armed", summary: "One click at a point or element path.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_type", safety: "armed", summary: "Type text; newlines are refused.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_key", safety: "confirm", summary: "Allowlisted key. Enter/Return need confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_paste", safety: "confirm", summary: "Paste via clipboard. Submit-class: confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_scroll", safety: "armed", summary: "Vertical scroll at a point, 1–10 pages.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_set_value", safety: "armed", summary: "Write a value into one AX element.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_perform", safety: "armed", summary: "Run one advertised AX action.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_stop", safety: "panic", summary: "Disarm, close sessions, end streams, audit.", engineUsage: pending(), widget: none(), app: none() },
      { name: "macos_task", safety: "armed", summary: "Bounded scripted sequence of the tools above.", engineUsage: pending(), widget: none(), app: none() }
    ]
  },
  {
    id: "cleanup",
    title: "Cleanup Lab",
    platform: "all hosts",
    docs: "lat.md/cleanup-lab.md (CUX-10), docs/PLAN-mcp-coverage.md",
    engineUsage: pending(),
    widgets: pending(),
    apps: pending(),
    rules: [
      "Scan, suggest and review never move files.",
      "cleanup_clean needs confirm: true after the user approved the plan. Trash only.",
      "Tools take catalog ids, never raw paths.",
      "MCP widgets/apps under ui://os-lab/cleanup/; host resource read + structuredContent proofs in test_mcp_ui_hosts.py."
    ],
    tools: [
      { name: "cleanup_status", safety: "read-only", summary: "Readiness, requirements and capabilities.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_catalog", safety: "read-only", summary: "Detector catalog for this OS. No paths.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_volumes", safety: "read-only", summary: "Local volumes, capacity and pressure.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_monitor", safety: "read-only", summary: "Background monitor config and warnings.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_permissions", safety: "read-only", summary: "Full Disk Access and folder grants.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_bookmarks", safety: "read-only", summary: "Quick-clean bookmarks.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_history", safety: "read-only", summary: "Verified audit history.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_widget", safety: "read-only", summary: "Desktop-widget snapshot.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_preferences", safety: "read-only", summary: "Saved suggestion preferences.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_job", safety: "read-only", summary: "Poll one scan, plan or clean job.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_scan", safety: "read-only", summary: "Measure catalog entries. Removes nothing.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_suggest", safety: "read-only", summary: "What to clean from a finished scan.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_review", safety: "read-only", summary: "Scan, suggest and build the Trash plan.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_plan", safety: "read-only", summary: "Build a Trash plan for catalog ids.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_quick_clean_plan", safety: "read-only", summary: "Trash plan for quick-clean bookmarks.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_clean", safety: "confirm", summary: "Run a previewed plan to Trash. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_job_cancel", safety: "write", summary: "Cancel a running cleanup job.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_preferences_save", safety: "write", summary: "Save suggestion preferences on this computer.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_monitor_config", safety: "write", summary: "Replace the monitor config.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_monitor_evaluate", safety: "write", summary: "Run one monitor check now.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_bookmark_add", safety: "write", summary: "Bookmark a catalog entry.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_bookmark_update", safety: "write", summary: "Update bookmark flags (quick clean, alerts).", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_bookmark_remove", safety: "write", summary: "Remove a bookmark.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_reveal", safety: "write", summary: "Show a catalog folder in the file manager.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_permissions_open", safety: "write", summary: "Open System Settings for a permission id.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_permissions_reveal_app", safety: "write", summary: "Reveal the host app for FDA grants.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_permissions_reset", safety: "confirm", summary: "Reset FDA via tccutil. confirm: true.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_widget_refresh", safety: "write", summary: "Rebuild and publish the desktop widget snapshot.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "cleanup_app_overview", safety: "read-only", summary: "Overview MCP App (storage hero + readiness).", engineUsage: pending(), widget: none(), app: pending() },
      { name: "cleanup_app_review", safety: "read-only", summary: "Review MCP App (scan → plan → confirm affordance).", engineUsage: pending(), widget: none(), app: pending() },
      { name: "cleanup_app_settings", safety: "read-only", summary: "Settings MCP App (permissions, bookmarks, monitor).", engineUsage: pending(), widget: none(), app: pending() },
      { name: "cleanup_explorer_roots", safety: "read-only", summary: "Space Explorer root folders.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_explorer_scan", safety: "read-only", summary: "Measure a Space Explorer root or subtree.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_deep_roots", safety: "read-only", summary: "Deep-scan root registry.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_deep_scan", safety: "read-only", summary: "Deep-scan configured roots.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_containers", safety: "read-only", summary: "Container engine capabilities and prune actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_containers_preview", safety: "read-only", summary: "Preview a container prune. Never prunes.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_containers_prune", safety: "confirm", summary: "Run a container prune. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_simulators", safety: "read-only", summary: "iOS Simulator inventory and clean actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_simulators_preview", safety: "read-only", summary: "Preview a simulator clean.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_simulators_run", safety: "confirm", summary: "Run a simulator clean. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_emulators", safety: "read-only", summary: "Android emulator inventory and clean actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_emulators_preview", safety: "read-only", summary: "Preview an emulator clean.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_emulators_run", safety: "confirm", summary: "Run an emulator clean. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_vms_scan", safety: "read-only", summary: "Scan VM disk usage.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_packages_scan", safety: "read-only", summary: "Scan package-manager caches.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_leftovers_scan", safety: "read-only", summary: "Scan leftover app support files.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_relocation", safety: "read-only", summary: "Relocation status and destinations.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_relocation_plan", safety: "read-only", summary: "Build a relocation preview. Never moves.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_relocation_run", safety: "confirm", summary: "Run a relocation. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_privileged", safety: "read-only", summary: "Privileged cleanup capabilities.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_privileged_preview", safety: "read-only", summary: "Preview a privileged cleanup.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_privileged_run", safety: "confirm", summary: "Run a privileged cleanup. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_simulator_storage", safety: "read-only", summary: "Simulator storage relocation config.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_simulator_storage_save", safety: "write", summary: "Save simulator storage config.", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_custom_entries_add", safety: "write", summary: "Add a custom catalog folder (path once).", engineUsage: pending(), widget: none(), app: none() },
      { name: "cleanup_custom_entries_remove", safety: "confirm", summary: "Remove a custom.<slug> entry. confirm: true.", engineUsage: pending(), widget: none(), app: none() }
    ]
  },
  {
    id: "websec",
    title: "Web Sec Lab",
    platform: "all hosts",
    docs: "lat.md/web-sec.md, web-sec/README.md",
    engineUsage: pending(),
    widgets: pending(),
    apps: none(),
    rules: [
      "Every scan is scope-guarded. Targets outside the scope file are refused.",
      "Passive scans need no confirmation.",
      "Intrusive checks need active: true and confirm: true after written authorization.",
      "Widgets: status, review, report under ui://os-lab/websec/widgets/."
    ],
    tools: [
      { name: "websec_status", safety: "read-only", summary: "Readiness, scope summary and storage.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "websec_catalogue", safety: "read-only", summary: "Registered checks and whether they are intrusive.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_guides", safety: "read-only", summary: "SecOps guides for the checks.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_preferences", safety: "read-only", summary: "Saved workbench choices. Intrusive mode is never saved.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_history", safety: "read-only", summary: "Recent scans for a target.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_reports", safety: "read-only", summary: "Stored report names for a target.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_report", safety: "read-only", summary: "One stored report (markdown, json, sarif, text, html).", engineUsage: pending(), widget: pending(), app: none() },
      { name: "websec_compare", safety: "read-only", summary: "What changed between two stored runs.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_job", safety: "read-only", summary: "Poll one scan or bulk job.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_review", safety: "read-only", summary: "Normalize the target, ask the scope guard, list checks.", engineUsage: pending(), widget: pending(), app: none() },
      { name: "websec_scan", safety: "confirm", summary: "Run a scope-checked scan. Active needs confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_scan_cancel", safety: "write", summary: "Stop a running scan or bulk job.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_bulk", safety: "read-only", summary: "Validate up to 20 targets passively.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_monitor", safety: "read-only", summary: "Opt-in passive monitor state.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_monitor_config", safety: "write", summary: "Replace the monitor config. Always passive.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_monitor_run", safety: "write", summary: "Run one monitor check now.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_stats", safety: "read-only", summary: "Totals over stored runs.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_favourite", safety: "write", summary: "Mark or unmark a stored run.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_delete_runs", safety: "confirm", summary: "Delete stored runs. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_clear_history", safety: "confirm", summary: "Delete stored runs of one or all targets. confirm: true.", engineUsage: pending(), widget: none(), app: none() },
      { name: "websec_preferences_save", safety: "write", summary: "Save workbench choices on this computer.", engineUsage: pending(), widget: none(), app: none() }
    ]
  },
  {
    id: "winapps",
    title: "Windows Apps Lab",
    platform: "Windows only",
    docs: "lat.md/win-lab.md, win-lab/winapps-policy.json",
    engineUsage: pending(),
    widgets: none(),
    apps: none(),
    rules: [
      "Offered only when the server runs on Windows (os-lab-windows).",
      "Read-only. The allowlist in win-lab/winapps-policy.json is empty by default (no apps).",
      "Restricted windows are never captured. There is no arm tool and no input tool."
    ],
    tools: [
      { name: "winapps_apps", safety: "windows-only", summary: "Allowlisted desktop windows. withheld counts the rest.", engineUsage: pending(), widget: none(), app: none() },
      { name: "winapps_screenshot", safety: "windows-only", summary: "PNG of one allowlisted, unrestricted window.", engineUsage: pending(), widget: none(), app: none() },
      { name: "winapps_capabilities", safety: "windows-only", summary: "Allowlist counts, policy errors, no input.", engineUsage: pending(), widget: none(), app: none() },
      { name: "winapps_doctor", safety: "windows-only", summary: "Desktop session, elevation, one capture probe.", engineUsage: pending(), widget: none(), app: none() },
      { name: "winapps_audit", safety: "windows-only", summary: "Newest agent calls and refusals, without titles.", engineUsage: pending(), widget: none(), app: none() }
    ]
  },
  {
    id: "android",
    title: "Android Lab",
    platform: "all hosts",
    docs: "lat.md/android-lab.md, console/mcp_android.py",
    engineUsage: pending(),
    widgets: none(),
    apps: pending(),
    rules: [
      "Status, Frida inventory and plan preview only.",
      "Frida inventory never attaches or injects.",
      "Scripted lab actions still go through labctl plan/start — not macos_task."
    ],
    tools: [
      { name: "android_status", safety: "read-only", summary: "Lab readiness, provider, reasons, actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "android_frida_inventory", safety: "read-only", summary: "Frida devices/processes (list only).", engineUsage: pending(), widget: none(), app: none() },
      { name: "android_plan", safety: "read-only", summary: "Guarded labctl plan preview.", engineUsage: pending(), widget: none(), app: none() },
      { name: "android_app_overview", safety: "read-only", summary: "Overview MCP App (readiness + actions).", engineUsage: pending(), widget: none(), app: pending() }
    ]
  },
  {
    id: "ios",
    title: "iOS Lab",
    platform: "macOS",
    docs: "lat.md/ios-lab.md, console/mcp_ios.py",
    engineUsage: pending(),
    widgets: none(),
    apps: pending(),
    rules: [
      "Observe only: devices, simulator, resources, screenshot.",
      "No agent arm or WebDriverAgent start — drive devices from the dashboard."
    ],
    tools: [
      { name: "ios_status", safety: "read-only", summary: "Lab readiness and actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_simulator", safety: "read-only", summary: "Installed simulators and runtimes.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_devices", safety: "read-only", summary: "Paired/connected real devices.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_device_check", safety: "read-only", summary: "Reachability probe for one UDID.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_resources", safety: "read-only", summary: "Resource tips for this Mac.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_screenshot", safety: "read-only", summary: "PNG of a booted simulator or real device.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_plan", safety: "read-only", summary: "Guarded labctl plan preview.", engineUsage: pending(), widget: none(), app: none() },
      { name: "ios_app_overview", safety: "read-only", summary: "Overview MCP App (readiness + actions).", engineUsage: pending(), widget: none(), app: pending() }
    ]
  },
  {
    id: "linux",
    title: "Linux Lab",
    platform: "all hosts",
    docs: "lat.md/linux-lab.md, console/mcp_linux.py",
    engineUsage: pending(),
    widgets: none(),
    apps: none(),
    rules: [
      "Status and plan preview first.",
      "Scripted actions only through existing plan/start — not from MCP mutate tools."
    ],
    tools: [
      { name: "linux_status", safety: "read-only", summary: "Lab readiness, KVM/WSL hints, actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "linux_plan", safety: "read-only", summary: "Guarded labctl plan preview.", engineUsage: pending(), widget: none(), app: none() }
    ]
  },
  {
    id: "web",
    title: "Web Lab",
    platform: "all hosts",
    docs: "lat.md/web-lab.md, console/mcp_web.py",
    engineUsage: pending(),
    widgets: none(),
    apps: pending(),
    rules: [
      "Status/overview/windows are read-only.",
      "Engine start/stop talk to the local loopback engine only."
    ],
    tools: [
      { name: "web_status", safety: "read-only", summary: "Lab readiness and engine health.", engineUsage: pending(), widget: none(), app: none() },
      { name: "web_overview", safety: "read-only", summary: "Engine overview when running.", engineUsage: pending(), widget: none(), app: none() },
      { name: "web_windows", safety: "read-only", summary: "Open Web Lab browser windows.", engineUsage: pending(), widget: none(), app: none() },
      { name: "web_engine_start", safety: "write", summary: "Start the local Web Lab engine.", engineUsage: pending(), widget: none(), app: none() },
      { name: "web_engine_stop", safety: "write", summary: "Stop the local Web Lab engine.", engineUsage: pending(), widget: none(), app: none() },
      { name: "web_app_overview", safety: "read-only", summary: "Overview MCP App (readiness + engine).", engineUsage: pending(), widget: none(), app: pending() }
    ]
  },
  {
    id: "source",
    title: "Source Lab",
    platform: "all hosts",
    docs: "lat.md/source-lab.md, console/mcp_source.py",
    engineUsage: pending(),
    widgets: none(),
    apps: pending(),
    rules: [
      "Readiness, candidates and plan preview only.",
      "Detection/crawl jobs still start from the dashboard or labctl."
    ],
    tools: [
      { name: "source_status", safety: "read-only", summary: "Lab readiness and actions.", engineUsage: pending(), widget: none(), app: none() },
      { name: "source_readiness", safety: "read-only", summary: "Raw engine readiness JSON.", engineUsage: pending(), widget: none(), app: none() },
      { name: "source_candidates", safety: "read-only", summary: "Local detection candidates.", engineUsage: pending(), widget: none(), app: none() },
      { name: "source_runtime", safety: "read-only", summary: "Saved runtime settings.", engineUsage: pending(), widget: none(), app: none() },
      { name: "source_plan", safety: "read-only", summary: "Guarded plan preview.", engineUsage: pending(), widget: none(), app: none() },
      { name: "source_app_overview", safety: "read-only", summary: "Overview MCP App (readiness + actions).", engineUsage: pending(), widget: none(), app: pending() }
    ]
  },
  {
    id: "firewall",
    title: "Firewall Lab",
    platform: "all hosts",
    docs: "lat.md/firewall-lab.md, console/mcp_firewall.py",
    engineUsage: pending(),
    widgets: none(),
    apps: none(),
    rules: [
      "Content browse only — catalog, company packs, guides.",
      "No live firewall control and no network mutation."
    ],
    tools: [
      { name: "firewall_status", safety: "read-only", summary: "Catalog presence and company count.", engineUsage: pending(), widget: none(), app: none() },
      { name: "firewall_catalog", safety: "read-only", summary: "Firewall Lab catalog.", engineUsage: pending(), widget: none(), app: none() },
      { name: "firewall_company", safety: "read-only", summary: "One company pack by slug.", engineUsage: pending(), widget: none(), app: none() },
      { name: "firewall_guides", safety: "read-only", summary: "Knowledge guide filenames.", engineUsage: pending(), widget: none(), app: none() }
    ]
  }
];

/** Remaining gaps after the first widget/app batches. See docs/PLAN-mcp-coverage.md. */
export const MCP_PLANNED_SECTIONS: { id: string; title: string; engineUsage: VerifySlot; widgets: VerifySlot; apps: VerifySlot; note: string }[] = [
  { id: "websec-apps", title: "Web Sec MCP Apps", engineUsage: pending(), widgets: pending(), apps: none(), note: "status/review/report widgets shipped; fuller workbench app still open." },
  { id: "macos-apps", title: "macOS MCP Apps", engineUsage: pending(), widgets: pending(), apps: none(), note: "apps/control widgets shipped. No arm tool (n/a)." },
  { id: "lab-widgets", title: "Lab MCP widgets", engineUsage: pending(), widgets: none(), apps: pending(), note: "android/ios/web/source overview apps shipped; per-tool widgets still open." }
];
