/**
 * The stdio MCP server in console/mcp_server.py: one process, four tool groups.
 * Names and safety notes match the shipped tools; the page fills the repo path
 * from GET /api/host.
 */
export type ToolSafety = "read-only" | "armed" | "confirm" | "panic" | "windows-only";

export interface McpTool {
  name: string;
  safety: ToolSafety;
  summary: string;
}

export interface McpGroup {
  id: "macos" | "cleanup" | "websec" | "winapps";
  title: string;
  platform: string;
  docs: string;
  rules: string[];
  tools: McpTool[];
}

export const MCP_SERVER_FILE = "console/mcp_server.py";
export const MCP_MAKE_TARGET = "make -C ios-lab mac-mcp";

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

export function genericSnippet(): string {
  return MCP_MAKE_TARGET;
}

export const MCP_GROUPS: McpGroup[] = [
  {
    id: "macos",
    title: "macOS Lab",
    platform: "macOS",
    docs: "lat.md/ios-lab.md (MIR-12)",
    rules: [
      "Read-only tools always work.",
      "Input tools need the dashboard's armed control mode. There is no arm tool.",
      "Enter, Return and paste need confirm: true even while armed.",
      "macos_stop is the panic stop: always safe to call.",
      "macos_task runs a bounded step list. Cleanup and Web Sec tools are refused inside it."
    ],
    tools: [
      { name: "macos_apps", safety: "read-only", summary: "Visible app windows: id, pid, app, title, rect." },
      { name: "macos_get_app_state", safety: "read-only", summary: "Accessibility tree of one window, optional PNG." },
      { name: "macos_screenshot", safety: "read-only", summary: "PNG of one visible window (Screen Recording)." },
      { name: "macos_windows", safety: "read-only", summary: "AX window list of one app." },
      { name: "macos_menubar", safety: "read-only", summary: "Menu-bar tree of one app." },
      { name: "macos_search", safety: "read-only", summary: "Find elements by label, value or placeholder." },
      { name: "macos_displays", safety: "read-only", summary: "Active displays, origin, size, scale." },
      { name: "macos_capabilities", safety: "read-only", summary: "Engine, input kinds, keys, safety limits." },
      { name: "macos_permissions", safety: "read-only", summary: "Accessibility and Screen Recording state." },
      { name: "macos_control_state", safety: "read-only", summary: "Whether control mode is armed, owner, remaining seconds." },
      { name: "macos_click", safety: "armed", summary: "One click at a point or element path." },
      { name: "macos_type", safety: "armed", summary: "Type text; newlines are refused." },
      { name: "macos_key", safety: "confirm", summary: "Allowlisted key. Enter/Return need confirm: true." },
      { name: "macos_paste", safety: "confirm", summary: "Paste via clipboard. Submit-class: confirm: true." },
      { name: "macos_scroll", safety: "armed", summary: "Vertical scroll at a point, 1–10 pages." },
      { name: "macos_set_value", safety: "armed", summary: "Write a value into one AX element." },
      { name: "macos_perform", safety: "armed", summary: "Run one advertised AX action." },
      { name: "macos_stop", safety: "panic", summary: "Disarm, close sessions, end streams, audit." },
      { name: "macos_task", safety: "armed", summary: "Bounded scripted sequence of the tools above." }
    ]
  },
  {
    id: "cleanup",
    title: "Cleanup Lab",
    platform: "all hosts",
    docs: "lat.md/cleanup-lab.md (CUX-10)",
    rules: [
      "Scan, suggest and review never move files.",
      "cleanup_clean needs confirm: true after the user approved the plan. Trash only.",
      "Tools take catalog ids, never raw paths."
    ],
    tools: [
      { name: "cleanup_status", safety: "read-only", summary: "Readiness, requirements and capabilities." },
      { name: "cleanup_catalog", safety: "read-only", summary: "Detector catalog for this OS. No paths." },
      { name: "cleanup_volumes", safety: "read-only", summary: "Local volumes, capacity and pressure." },
      { name: "cleanup_monitor", safety: "read-only", summary: "Background monitor config and warnings." },
      { name: "cleanup_permissions", safety: "read-only", summary: "Full Disk Access and folder grants." },
      { name: "cleanup_bookmarks", safety: "read-only", summary: "Quick-clean bookmarks." },
      { name: "cleanup_history", safety: "read-only", summary: "Verified audit history." },
      { name: "cleanup_widget", safety: "read-only", summary: "Desktop-widget snapshot." },
      { name: "cleanup_preferences", safety: "read-only", summary: "Saved suggestion preferences." },
      { name: "cleanup_job", safety: "read-only", summary: "Poll one scan, plan or clean job." },
      { name: "cleanup_scan", safety: "read-only", summary: "Measure catalog entries. Removes nothing." },
      { name: "cleanup_suggest", safety: "read-only", summary: "What to clean from a finished scan." },
      { name: "cleanup_review", safety: "read-only", summary: "Scan, suggest and build the Trash plan." },
      { name: "cleanup_quick_clean_plan", safety: "read-only", summary: "Trash plan for quick-clean bookmarks." },
      { name: "cleanup_clean", safety: "confirm", summary: "Run a previewed plan to Trash. confirm: true." },
      { name: "cleanup_preferences_save", safety: "read-only", summary: "Save suggestion preferences on this computer." },
      { name: "cleanup_monitor_config", safety: "read-only", summary: "Replace the monitor config." },
      { name: "cleanup_monitor_evaluate", safety: "read-only", summary: "Run one monitor check now." },
      { name: "cleanup_bookmark_add", safety: "read-only", summary: "Bookmark a catalog entry." },
      { name: "cleanup_bookmark_remove", safety: "read-only", summary: "Remove a bookmark." },
      { name: "cleanup_reveal", safety: "read-only", summary: "Show a catalog folder in the file manager." }
    ]
  },
  {
    id: "websec",
    title: "Web Sec Lab",
    platform: "all hosts",
    docs: "lat.md/web-sec.md, web-sec/README.md",
    rules: [
      "Every scan is scope-guarded. Targets outside the scope file are refused.",
      "Passive scans need no confirmation.",
      "Intrusive checks need active: true and confirm: true after written authorization."
    ],
    tools: [
      { name: "websec_status", safety: "read-only", summary: "Readiness, scope summary and storage." },
      { name: "websec_catalogue", safety: "read-only", summary: "Registered checks and whether they are intrusive." },
      { name: "websec_guides", safety: "read-only", summary: "SecOps guides for the checks." },
      { name: "websec_preferences", safety: "read-only", summary: "Saved workbench choices. Intrusive mode is never saved." },
      { name: "websec_history", safety: "read-only", summary: "Recent scans for a target." },
      { name: "websec_reports", safety: "read-only", summary: "Stored report names for a target." },
      { name: "websec_report", safety: "read-only", summary: "One stored report (markdown, json, sarif, text, html)." },
      { name: "websec_compare", safety: "read-only", summary: "What changed between two stored runs." },
      { name: "websec_job", safety: "read-only", summary: "Poll one scan or bulk job." },
      { name: "websec_review", safety: "read-only", summary: "Normalize the target, ask the scope guard, list checks." },
      { name: "websec_scan", safety: "confirm", summary: "Run a scope-checked scan. Active needs confirm: true." },
      { name: "websec_scan_cancel", safety: "read-only", summary: "Stop a running scan or bulk job." },
      { name: "websec_bulk", safety: "read-only", summary: "Validate up to 20 targets passively." },
      { name: "websec_monitor", safety: "read-only", summary: "Opt-in passive monitor state." },
      { name: "websec_monitor_config", safety: "read-only", summary: "Replace the monitor config. Always passive." },
      { name: "websec_monitor_run", safety: "read-only", summary: "Run one monitor check now." },
      { name: "websec_stats", safety: "read-only", summary: "Totals over stored runs." },
      { name: "websec_favourite", safety: "read-only", summary: "Mark or unmark a stored run." },
      { name: "websec_delete_runs", safety: "confirm", summary: "Delete stored runs. confirm: true." },
      { name: "websec_clear_history", safety: "confirm", summary: "Delete stored runs of one or all targets. confirm: true." },
      { name: "websec_preferences_save", safety: "read-only", summary: "Save workbench choices on this computer." }
    ]
  },
  {
    id: "winapps",
    title: "Windows Apps Lab",
    platform: "Windows only",
    docs: "lat.md/win-lab.md, win-lab/winapps-policy.json",
    rules: [
      "Offered only when the server runs on Windows (os-lab-windows).",
      "Read-only. The allowlist in win-lab/winapps-policy.json is empty by default (no apps).",
      "Restricted windows are never captured. There is no arm tool and no input tool."
    ],
    tools: [
      { name: "winapps_apps", safety: "windows-only", summary: "Allowlisted desktop windows. withheld counts the rest." },
      { name: "winapps_screenshot", safety: "windows-only", summary: "PNG of one allowlisted, unrestricted window." },
      { name: "winapps_capabilities", safety: "windows-only", summary: "Allowlist counts, policy errors, no input." },
      { name: "winapps_doctor", safety: "windows-only", summary: "Desktop session, elevation, one capture probe." },
      { name: "winapps_audit", safety: "windows-only", summary: "Newest agent calls and refusals, without titles." }
    ]
  }
];
