/**
 * Help → MCP servers: attach snippets for major hosts, tool groups with safety
 * and verification slots (engine / widgets / apps), plus planned lab gaps.
 */
import { PlugsIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { Badge, CopyButton, PageHead, Section, Status } from "../components/ui";
import { hostStore } from "../lib/api";
import { McpPluginCards } from "./mcp-plugin-cards";
import { McpCodexPluginCards } from "./mcp-codex-plugin-cards";
import { McpHostPluginCards } from "./mcp-host-plugin-cards";
import {
  MCP_GROUPS,
  MCP_PLAN,
  MCP_PLANNED_SECTIONS,
  MCP_PLUGINS,
  MCP_SERVER_FILE,
  MCP_SKILLS,
  MCP_VERIFICATION,
  antigravitySnippet,
  claudeCodeSnippet,
  claudeDesktopSnippet,
  codexSnippet,
  cursorSnippet,
  genericSnippet,
  openCodeSnippet,
  serverName,
  zcodeSnippet,
  type ToolSafety,
  type VerifySlot,
  type VerifyStatus
} from "../lib/mcp-guides";

const SAFETY_LABEL: Record<ToolSafety, string> = {
  "read-only": "read-only",
  armed: "armed",
  confirm: "confirm",
  panic: "panic stop",
  "windows-only": "Windows only",
  write: "write"
};

const SAFETY_TONE: Record<ToolSafety, "success" | "warning" | "danger" | undefined> = {
  "read-only": "success",
  armed: "warning",
  confirm: "danger",
  panic: undefined,
  "windows-only": undefined,
  write: "warning"
};

const VERIFY_TONE: Record<VerifyStatus, "success" | "warning" | "danger" | undefined> = {
  none: undefined,
  pending: "warning",
  verified: "success",
  "n/a": undefined
};

function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-md border border-(--iux-border) p-3">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-medium">{label}</h3>
        <span className="ms-auto"><CopyButton text={text} label="Copy snippet" /></span>
      </div>
      <pre translate="no" className="iux-scroll max-h-48 overflow-auto text-xs leading-relaxed">{text}</pre>
    </div>
  );
}

function VerifyBadges({ label, slot }: { label: string; slot: VerifySlot }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs">
      <span className="text-(--iux-muted-foreground)">{label}</span>
      <Badge tone={VERIFY_TONE[slot.status]}>{slot.status}</Badge>
      {slot.proof ? <span className="text-(--iux-muted-foreground)" translate="no">{slot.proof}</span> : <span className="text-(--iux-muted-foreground)">proof: —</span>}
    </span>
  );
}

export default function McpPage() {
  const { data, error } = hostStore.use();
  const root = data?.host?.root;
  const python = data?.host?.pythonExecutable;
  const os = data?.host?.os;
  const toolCount = MCP_GROUPS.reduce((n, g) => n + g.tools.length, 0);

  return (
    <AppShell activeId="mcp">
      <TopBar title="MCP servers" icon={<PlugsIcon size={20} weight="duotone" />} />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <PageHead
          icon={<PlugsIcon size={22} />}
          title="MCP servers"
          description="One stdio server on this computer. The model decides; the console guards every step."
        />

        <Section id="mcp-about" title="What this server is" description="Standard library only. Start it from the repo; Claude, Codex, Cursor, OpenCode, Zcode, Antigravity or any stdio client can attach.">
          <p className="text-sm leading-relaxed">
            <code translate="no">{serverName(os)}</code>
            {" "}(<code translate="no">{MCP_SERVER_FILE}</code>)
          </p>
          <p className="mt-2 text-sm leading-relaxed">
            It exposes {toolCount} tools in four groups, plus prompts and Cleanup Lab UI resources.
            Cleanup and Web Sec tools are refused inside macos_task.
          </p>
          <p className="mt-2 text-sm leading-relaxed text-(--iux-muted-foreground)">
            Coverage plan: <code translate="no">{MCP_PLAN}</code> · verification registry: <code translate="no">{MCP_VERIFICATION}</code> ·
            skills: <code translate="no">{MCP_SKILLS}</code> · plugins: <code translate="no">{MCP_PLUGINS}</code>
          </p>
        </Section>

        <Section id="mcp-setup" title="Set up a client" description="Snippets use this computer's repo path when the console is connected. Plugin scaffolds live under plugins/mcp/.">
          {error && <Status value={{ ok: false, text: error }} />}
          {!root && !error && <p className="mb-3 text-sm text-(--iux-muted-foreground)">Connect the local console to fill this computer's repo path. Until then the snippets use {"<repo>"}.</p>}
          {root && <p className="mb-3 text-sm text-(--iux-muted-foreground)">Repo path: <code translate="no">{root}</code></p>}
          <div className="grid gap-3">
            <Snippet label="Claude Code" text={claudeCodeSnippet(root, os, python)} />
            <Snippet label="Claude Desktop" text={claudeDesktopSnippet(root, os, python)} />
            <Snippet label="Codex" text={codexSnippet(root, python)} />
            <Snippet label="Cursor" text={cursorSnippet(root, python)} />
            <Snippet label="OpenCode" text={openCodeSnippet(root, python)} />
            <Snippet label="Zcode" text={zcodeSnippet(root, python)} />
            <Snippet label="Antigravity" text={antigravitySnippet(root, python)} />
            <Snippet label="Generic stdio" text={genericSnippet()} />
          </div>
        </Section>

        <McpPluginCards root={root} python={python} />
        <McpCodexPluginCards root={root} python={python} />
        <McpHostPluginCards root={root} python={python} />

        {MCP_GROUPS.map((group) => (
          <Section
            key={group.id}
            id={`mcp-${group.id}`}
            title={group.title}
            description={`${group.platform} · ${group.tools.length} tools · ${group.docs}`}
          >
            <div className="mb-3 flex flex-wrap gap-3 text-sm">
              <VerifyBadges label="engine" slot={group.engineUsage} />
              <VerifyBadges label="widgets" slot={group.widgets} />
              <VerifyBadges label="apps" slot={group.apps} />
            </div>
            <ul className="mb-3 list-disc ps-5 text-sm leading-relaxed text-(--iux-muted-foreground)">
              {group.rules.map((rule) => <li key={rule}>{rule}</li>)}
            </ul>
            <ul className="divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
              {group.tools.map((tool) => (
                <li key={tool.name} className="flex flex-col gap-1 px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-start gap-2">
                    <code translate="no" className="font-medium">{tool.name}</code>
                    <Badge tone={SAFETY_TONE[tool.safety]}>{SAFETY_LABEL[tool.safety]}</Badge>
                    <span className="min-w-0 flex-1 text-(--iux-muted-foreground)">{tool.summary}</span>
                  </div>
                  <div className="flex flex-wrap gap-3 ps-0.5">
                    <VerifyBadges label="engine" slot={tool.engineUsage ?? { status: "none", proof: null }} />
                    <VerifyBadges label="widget" slot={tool.widget ?? { status: "none", proof: null }} />
                    <VerifyBadges label="app" slot={tool.app ?? { status: "none", proof: null }} />
                  </div>
                </li>
              ))}
            </ul>
          </Section>
        ))}

        <Section id="mcp-planned" title="Planned lab coverage" description="Labs that exist in os-lab but still lack MCP tools. Tracked in docs/PLAN-mcp-coverage.md.">
          <ul className="divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
            {MCP_PLANNED_SECTIONS.map((section) => (
              <li key={section.id} className="flex flex-col gap-1 px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <code translate="no" className="font-medium">{section.id}</code>
                  <span className="font-medium">{section.title}</span>
                </div>
                <p className="text-(--iux-muted-foreground)">{section.note}</p>
                <div className="flex flex-wrap gap-3">
                  <VerifyBadges label="engine" slot={section.engineUsage} />
                  <VerifyBadges label="widgets" slot={section.widgets} />
                  <VerifyBadges label="apps" slot={section.apps} />
                </div>
              </li>
            ))}
          </ul>
        </Section>

        <Section id="mcp-troubleshoot" title="Troubleshooting" description="Permissions, armed mode and the Web Sec scope file.">
          <ul className="list-disc ps-5 text-sm leading-relaxed">
            <li>macOS screenshots need Screen Recording; the accessibility tree needs Accessibility. Grant them from the macOS Lab dashboard, not from the agent.</li>
            <li>Input tools refuse while control mode is off. Arm it from the dashboard. It expires by itself.</li>
            <li>Web Sec scans outside the declared scope file are refused. Edit the scope on the Web Sec Lab page.</li>
            <li>Windows Apps tools appear only on Windows. An empty allowlist means the agent sees no apps.</li>
            <li>To contribute a verification, set <code translate="no">status</code> to <code translate="no">verified</code> and fill <code translate="no">proof</code> in <code translate="no">{MCP_VERIFICATION}</code>.</li>
            <li>Start the server with <code translate="no">{`python3 ${MCP_SERVER_FILE}`}</code> from the repo, or <code translate="no">{genericSnippet()}</code>.</li>
          </ul>
        </Section>
      </main>
    </AppShell>
  );
}
