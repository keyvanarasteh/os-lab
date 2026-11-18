/**
 * MCP-01: connect os-lab's MCP servers to an MCP client.
 *
 * A client launches an os-lab MCP server itself, so connecting one means adding
 * an entry to that client's configuration. The page follows the console's
 * preview → confirm → run rule: Connect asks the console for the exact change
 * (the CLI command, or the file and entry), shows it, and applies it only with
 * the preview's token. An `oslab://mcp/connect/<server>?client=<id>` URL opens
 * the same dialog through this page's query; it never applies anything itself.
 */
import { useEffect, useState } from "react";
import { PlugsConnectedIcon } from "@phosphor-icons/react";
import { AppShell } from "../shell/app-shell";
import { TopBar } from "../shell/top-bar";
import { Badge, CopyButton, Empty, Modal, PageHead, Section, Skeleton, Status } from "../components/ui";
import { api, message, usePoll, type McpClient, type McpPlan, type McpServer } from "../lib/api";

// @lat: [[dashboard#MCP servers (MCP-01)]]

const quote = (arg: string) => (/^[\w@%+=:,./-]+$/.test(arg) ? arg : `'${arg.replace(/'/g, `'\\''`)}'`);

/** The connect request a page URL asks for, if any: `?connect=<server>&client=<id>`. */
function requested(): { server: string; client: string | null } | null {
  if (typeof window === "undefined") return null;
  const query = new URLSearchParams(window.location.search);
  const server = query.get("connect");
  return server ? { server, client: query.get("client") } : null;
}

export default function McpPage() {
  const { data, error, reload } = usePoll(api.mcpStatus, 0);
  const [dialog, setDialog] = useState<{ server: string; client: string | null } | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  // A URL request opens the dialog once the console has answered; unknown ids
  // are reported rather than guessed at.
  useEffect(() => {
    if (!data) return;
    const want = requested();
    if (!want) return;
    window.history.replaceState(null, "", window.location.pathname);
    const server = data.servers.find((s) => s.id === want.server);
    const client = want.client ? data.clients.find((c) => c.id === want.client) : null;
    if (!server || (want.client && !client)) {
      setResult({ ok: false, text: "That MCP server or client is not available" });
      return;
    }
    setDialog({ server: server.id, client: client?.id ?? null });
  }, [data]);

  return (
    <AppShell activeId="mcp">
      <TopBar title="MCP servers" icon={<PlugsConnectedIcon size={20} weight="duotone" />} />
      <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
        <PageHead
          icon={<PlugsConnectedIcon size={22} />}
          title="MCP servers"
          description="Connect os-lab's MCP servers to Claude Code, Codex, Claude Desktop or Cursor. Connecting gives an agent no control: input tools still need armed control mode."
        />
        <Status value={result} />
        {error ? <Status value={{ ok: false, text: error }} /> : null}
        {!data && !error ? <Skeleton rows={3} /> : null}
        {data?.servers.length === 0 ? <Empty>No MCP servers are available.</Empty> : null}
        {data?.servers.map((server) => (
          <ServerCard key={server.id} server={server} clients={data.clients} onConnect={(client) => { setResult(null); setDialog({ server: server.id, client }); }} />
        ))}
      </main>
      {dialog && data ? (
        <ConnectDialog
          server={data.servers.find((s) => s.id === dialog.server)!}
          clients={data.clients}
          initialClient={dialog.client}
          onClose={() => setDialog(null)}
          onDone={(text) => { setDialog(null); setResult({ ok: true, text }); reload(); }}
        />
      ) : null}
    </AppShell>
  );
}

function ServerCard({ server, clients, onConnect }: { server: McpServer; clients: McpClient[]; onConnect: (client: string) => void }) {
  return (
    <Section id={`mcp-${server.id}`} icon={<PlugsConnectedIcon size={16} />} title={server.label} description={server.description}>
      <p className="mb-3 flex flex-wrap items-center gap-2 text-xs text-(--iux-muted-foreground)">
        <span>Entry name</span>
        <code data-no-translate dir="ltr">{server.name}</code>
      </p>
      <ul className="flex flex-col divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
        {clients.map((client) => {
          const registered = client.registered[server.id];
          return (
            <li key={client.id} data-mcp-client={client.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
              <span className="min-w-0 flex-1 font-medium">{client.label}</span>
              {!client.installed ? (
                <Badge>Not installed</Badge>
              ) : registered ? (
                <Badge tone="success">Connected</Badge>
              ) : registered === null ? (
                <Badge>Unknown</Badge>
              ) : (
                <Badge tone="warning">Not connected</Badge>
              )}
              <button
                type="button"
                className="iux-btn"
                data-variant="outline"
                disabled={!client.installed}
                onClick={() => onConnect(client.id)}
              >
                {registered ? "Reconnect" : "Connect"}
              </button>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function ConnectDialog({ server, clients, initialClient, onClose, onDone }: {
  server: McpServer;
  clients: McpClient[];
  initialClient: string | null;
  onClose: () => void;
  onDone: (text: string) => void;
}) {
  const installed = clients.filter((c) => c.installed);
  const [client, setClient] = useState(initialClient ?? installed[0]?.id ?? "");
  const [preview, setPreview] = useState<{ plan: McpPlan; token: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const label = clients.find((c) => c.id === client)?.label ?? client;

  useEffect(() => {
    setPreview(null);
    setError(null);
    if (!client) return;
    let live = true;
    api.mcpPreview(server.id, client).then((p) => live && setPreview(p), (e) => live && setError(message(e)));
    return () => { live = false; };
  }, [server.id, client]);

  const connect = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      await api.mcpConnect(server.id, client, preview.token);
      onDone(`${server.label} is connected to ${label}. Restart ${label} to load it.`);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const plan = preview?.plan;
  const command = plan?.argv ? plan.argv.map(quote).join(" ") : "";
  const entry = plan?.entry ? JSON.stringify({ [plan.name]: plan.entry }, null, 2) : "";
  return (
    <Modal
      title={`Connect ${server.label}`}
      icon={<PlugsConnectedIcon size={16} />}
      description="Review the exact change before it is made. Nothing is written until you confirm."
      onClose={onClose}
    >
      <div className="flex flex-col gap-3 px-6 pb-5 text-sm">
        <label className="flex flex-col gap-1.5">
          <span className="font-medium">Client</span>
          <select className="iux-input" value={client} onChange={(e) => setClient(e.target.value)} aria-label="MCP client">
            {clients.map((c) => (
              <option key={c.id} value={c.id} disabled={!c.installed}>{c.label}</option>
            ))}
          </select>
        </label>
        {!client ? <Empty>No supported MCP client is installed on this computer.</Empty> : null}
        {client && !preview && !error ? <Skeleton rows={2} /> : null}
        {plan?.argv ? (
          <div className="flex flex-col gap-1.5" data-mcp-plan="cli">
            <span className="font-medium">Runs this command</span>
            <pre data-no-translate dir="ltr" className="overflow-x-auto rounded-md bg-(--iux-muted) p-3 text-xs whitespace-pre-wrap break-all">{command}</pre>
            <div><CopyButton text={command} /></div>
          </div>
        ) : null}
        {plan?.file ? (
          <div className="flex flex-col gap-1.5" data-mcp-plan="json">
            <span className="font-medium">Adds this entry to the client's config file</span>
            <code data-no-translate dir="ltr" className="text-xs break-all">{plan.file}</code>
            <pre data-no-translate dir="ltr" className="overflow-x-auto rounded-md bg-(--iux-muted) p-3 text-xs">{entry}</pre>
            <p className="text-xs text-(--iux-muted-foreground)">Other entries stay as they are, and the previous file is kept next to it as a backup.</p>
          </div>
        ) : null}
        {plan?.replaces ? <Status value={{ ok: false, text: "An entry with this name already exists and will be replaced." }} /> : null}
        {error ? <Status value={{ ok: false, text: error }} /> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={onClose}>Cancel</button>
          <button type="button" className="iux-btn" disabled={!preview || busy} onClick={() => void connect()}>
            {busy ? "Connecting…" : "Connect"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
