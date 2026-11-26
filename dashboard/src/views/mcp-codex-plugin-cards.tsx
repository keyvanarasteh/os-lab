/**
 * Check and install the os-lab Codex plugin. Changes are previewed here; install,
 * update and uninstall run only from a terminal (Codex has no agent apply path).
 */
import { useCallback, useEffect, useState } from "react";
import { Badge, CopyButton, Modal, Section, Skeleton, Status, type Tone } from "../components/ui";
import { api, type CodexPluginPlan, type CodexPluginState, type CodexPluginUpdates } from "../lib/api";
import { codexPluginSnippet, scriptCommand } from "../lib/mcp-guides";

type Note = { ok: boolean; text: string } | null;
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

function Action({ label, onClick, disabled, primary }: { label: string; onClick: () => void; disabled?: boolean; primary?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`iux-touch-target rounded-md border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${primary ? "border-transparent bg-(--iux-foreground) text-(--iux-card)" : "border-(--iux-border) hover:bg-(--iux-muted)"}`}
    >
      {label}
    </button>
  );
}

function State({ tone, label, version }: { tone: Tone; label: string; version?: string | null }) {
  return (
    <p className="mb-3 flex flex-wrap items-center gap-2 text-sm">
      <Badge tone={tone}>{label}</Badge>
      {version ? <span translate="no" className="text-(--iux-muted-foreground)">{version}</span> : null}
    </p>
  );
}

function Terminal({ command }: { command: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-(--iux-border) p-3">
      <pre translate="no" className="iux-scroll min-w-0 flex-1 overflow-auto text-xs">{command}</pre>
      <CopyButton text={command} label="Copy command" />
    </div>
  );
}

export function McpCodexPluginCards({ root, python }: { root?: string; python?: string | null }) {
  const [state, setState] = useState<CodexPluginState | null>(null);
  const [updates, setUpdates] = useState<CodexPluginUpdates | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  const [plan, setPlan] = useState<CodexPluginPlan | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.codexPlugin();
      if (!next.codex) throw new Error("The console did not report the Codex plugin state.");
      setState(next);
      setLoadError(null);
    } catch (error) {
      setState(null);
      setLoadError(message(error));
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setNote(null);
    try {
      await work();
    } catch (error) {
      setNote({ ok: false, text: message(error) });
    } finally {
      setBusy(false);
    }
  };
  const preview = (action: "install" | "update" | "uninstall") =>
    run(async () => setPlan(await api.codexPluginPreview(action)));
  const check = () =>
    run(async () => {
      setUpdates(await api.codexPluginCheck(true));
      await refresh();
    });

  if (loadError) {
    return (
      <Section id="mcp-codex-cards" title="Install as a Codex plugin" description="Connect the local console to check the plugin from this page. Install runs in a terminal.">
        <Terminal command={codexPluginSnippet(root, python)} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Action label="Try again" onClick={() => void refresh()} />
          <span className="text-xs text-(--iux-muted-foreground)">{loadError}</span>
        </div>
      </Section>
    );
  }
  if (!state) return <Section id="mcp-codex-cards" title="Install as a Codex plugin"><Skeleton rows={2} /></Section>;

  const { codex, checkoutVersion, terminalCommand } = state;
  const outdated = !!codex.installed && !!codex.version && codex.version !== checkoutVersion;
  const duplicates = codex.duplicates.map((row) => row.name);

  return (
    <div id="mcp-codex-cards" className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-2">
        <Section id="mcp-card-codex" title="Codex plugin" description="Server and lab skills for the Codex CLI and desktop app.">
          {!codex.cli ? <State tone="danger" label="Codex CLI not found" />
            : !codex.installed ? <State tone={undefined} label="Not installed" />
              : codex.enabled === false ? <State tone="warning" label="Disabled" version={codex.version} />
                : outdated ? <State tone="warning" label="Update available" version={`${codex.version} → ${checkoutVersion}`} />
                  : <State tone="success" label="Installed" version={codex.version} />}
          {codex.error ? <Status value={{ ok: false, text: codex.error }} /> : null}
          <div className="flex flex-wrap gap-2">
            {!codex.installed
              ? <Action primary label="Preview install" disabled={busy || !codex.cli} onClick={() => void preview("install")} />
              : (
                <>
                  <Action primary label="Preview update" disabled={busy} onClick={() => void preview("update")} />
                  <Action label="Preview uninstall" disabled={busy} onClick={() => void preview("uninstall")} />
                </>
              )}
          </div>
        </Section>

        <Section id="mcp-card-codex-updates" title="Updates" description="Checking asks GitHub for the published version.">
          {!updates ? <State tone={undefined} label="Not checked" version={checkoutVersion} />
            : updates.published?.note ? <State tone="warning" label="Published version unavailable" />
              : updates.updatesAvailable.length ? <State tone="warning" label="Update available" version={updates.updatesAvailable.join(", ")} />
                : <State tone="success" label="Up to date" version={checkoutVersion} />}
          <Action primary label="Check for updates" disabled={busy} onClick={() => void check()} />
        </Section>
      </div>

      {duplicates.length ? <p className="text-sm text-(--iux-muted-foreground)">Other MCP entries also run this server: <span translate="no">{duplicates.join(", ")}</span></p> : null}
      {state.doctor.checks.filter((row) => !row.ok).map((row) => <Status key={row.name} value={{ ok: false, text: row.fix ?? row.detail }} />)}
      <Status value={note} />
      <Terminal command={terminalCommand ? scriptCommand(terminalCommand, root, python) : codexPluginSnippet(root, python)} />

      {plan ? (
        <Modal title="Review the change" description="Nothing has changed yet. Run the terminal command after you approve." onClose={() => setPlan(null)}>

          <div className="flex flex-col gap-3">
            {plan.commands.map((command) => <Terminal key={command} command={command} />)}
            <Terminal command={plan.terminalCommand ?? scriptCommand(`python3 scripts/codex-plugin.py ${plan.action}`, root, python)} />
            {[...(plan.manual ?? []), ...(plan.warnings ?? [])].map((text) => <p key={text} className="text-sm text-(--iux-muted-foreground)">{text}</p>)}
            <div className="flex flex-wrap justify-end gap-2">
              <Action label="Close" onClick={() => setPlan(null)} />
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
