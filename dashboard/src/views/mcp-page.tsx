/**
 * Help → MCP servers: how to attach the local stdio server, and the four tool
 * groups with their safety rules. The repo path comes from GET /api/host.
 */
import { PlugsIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { Badge, CopyButton, PageHead, Section, Status } from "../components/ui";
import { hostStore } from "../lib/api";
import {
  MCP_GROUPS,
  MCP_SERVER_FILE,
  claudeCodeSnippet,
  claudeDesktopSnippet,
  genericSnippet,
  serverName,
  type ToolSafety
} from "../lib/mcp-guides";

const SAFETY_LABEL: Record<ToolSafety, string> = {
  "read-only": "read-only",
  armed: "armed",
  confirm: "confirm",
  panic: "panic stop",
  "windows-only": "Windows only"
};

const SAFETY_TONE: Record<ToolSafety, "success" | "warning" | "danger" | undefined> = {
  "read-only": "success",
  armed: "warning",
  confirm: "danger",
  panic: undefined,
  "windows-only": undefined
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

export default function McpPage() {
  const { data, error } = hostStore.use();
  const root = data?.host?.root;
  const os = data?.host?.os;
  const code = claudeCodeSnippet(root, os);
  const desktop = claudeDesktopSnippet(root, os);
  const generic = genericSnippet();

  return (
    <AppShell activeId="mcp">
      <TopBar title="MCP servers" icon={<PlugsIcon size={20} weight="duotone" />} />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <PageHead
          icon={<PlugsIcon size={22} />}
          title="MCP servers"
          description="One stdio server on this computer. The model decides; the console guards every step."
        />

        <Section id="mcp-about" title="What this server is" description="Standard library only. Start it from the repo; Claude Code, Claude Desktop or any stdio client can attach.">
          <p className="text-sm leading-relaxed">
            <code translate="no">{serverName(os)}</code>
            {" "}(<code translate="no">{MCP_SERVER_FILE}</code>)
          </p>
          <p className="mt-2 text-sm leading-relaxed">It exposes 66 tools in four groups. Cleanup and Web Sec tools are refused inside macos_task.</p>
        </Section>

        <Section id="mcp-setup" title="Set up a client" description="Snippets use this computer's repo path when the console is connected.">
          {error && <Status value={{ ok: false, text: error }} />}
          {!root && !error && <p className="mb-3 text-sm text-(--iux-muted-foreground)">Connect the local console to fill this computer's repo path. Until then the snippets use {"<repo>"}.</p>}
          {root && <p className="mb-3 text-sm text-(--iux-muted-foreground)">Repo path: <code translate="no">{root}</code></p>}
          <div className="grid gap-3">
            <Snippet label="Claude Code" text={code} />
            <Snippet label="Claude Desktop" text={desktop} />
            <Snippet label="Generic stdio" text={generic} />
          </div>
        </Section>

        {MCP_GROUPS.map((group) => (
          <Section
            key={group.id}
            id={`mcp-${group.id}`}
            title={group.title}
            description={`${group.platform} · ${group.tools.length} · ${group.docs}`}
          >
            <ul className="mb-3 list-disc ps-5 text-sm leading-relaxed text-(--iux-muted-foreground)">
              {group.rules.map((rule) => <li key={rule}>{rule}</li>)}
            </ul>
            <ul className="divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
              {group.tools.map((tool) => (
                <li key={tool.name} className="flex flex-wrap items-start gap-2 px-3 py-2 text-sm">
                  <code translate="no" className="font-medium">{tool.name}</code>
                  <Badge tone={SAFETY_TONE[tool.safety]}>{SAFETY_LABEL[tool.safety]}</Badge>
                  <span className="min-w-0 flex-1 text-(--iux-muted-foreground)">{tool.summary}</span>
                </li>
              ))}
            </ul>
          </Section>
        ))}

        <Section id="mcp-troubleshoot" title="Troubleshooting" description="Permissions, armed mode and the Web Sec scope file.">
          <ul className="list-disc ps-5 text-sm leading-relaxed">
            <li>macOS screenshots need Screen Recording; the accessibility tree needs Accessibility. Grant them from the macOS Lab dashboard, not from the agent.</li>
            <li>Input tools refuse while control mode is off. Arm it from the dashboard. It expires by itself.</li>
            <li>Web Sec scans outside the declared scope file are refused. Edit the scope on the Web Sec Lab page.</li>
            <li>Windows Apps tools appear only on Windows. An empty allowlist means the agent sees no apps.</li>
            <li>Start the server with <code translate="no">{`python3 ${MCP_SERVER_FILE}`}</code> from the repo, or <code translate="no">{generic}</code>.</li>
          </ul>
        </Section>
      </main>
    </AppShell>
  );
}
