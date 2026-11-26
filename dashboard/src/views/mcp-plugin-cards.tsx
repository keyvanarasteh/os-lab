/**
 * Check, install and update the os-lab Claude plugin (Claude Code) and extension (Claude
 * Desktop). Every change is previewed first and runs only after Confirm. Without the local
 * console the cards show the terminal commands instead.
 */
import { useCallback, useEffect, useState } from "react";
import { Badge, CopyButton, Modal, Section, Skeleton, Status, type Tone } from "../components/ui";
import { api, type ClaudePluginAction, type ClaudePluginPlan, type ClaudePluginState, type ClaudePluginUpdates } from "../lib/api";
import { claudePluginSnippet } from "../lib/mcp-guides";

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

export function McpPluginCards({ root }: { root?: string }) {
  const [state, setState] = useState<ClaudePluginState | null>(null);
  const [updates, setUpdates] = useState<ClaudePluginUpdates | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  const [plan, setPlan] = useState<ClaudePluginPlan | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.claudePlugin();
      if (!next.code || !next.desktop) throw new Error("The console did not report the plugin state.");
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
  const preview = (action: ClaudePluginAction, updateCheck?: boolean) =>
    run(async () => setPlan(await api.claudePluginPreview(action, updateCheck)));
  const check = () =>
    run(async () => {
      const next = await api.claudePluginCheck(true);
      setUpdates(next);
      await refresh();
    });
  const confirm = (token: string) =>
    run(async () => {
      setPlan(null);
      const result = await api.claudePluginApply(token);
      const failed = result.steps.find((step) => !step.ok);
      setNote({ ok: result.ok, text: failed ? failed.message : result.next });
      await refresh();
    });

  if (loadError) {
    return (
      <Section id="mcp-claude-plugin" title="Install as a Claude plugin" description="Connect the local console to check, install and update from this page. You can also run this in a terminal.">
        <Terminal command={claudePluginSnippet(root)} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Action label="Try again" onClick={() => void refresh()} />
          <span className="text-xs text-(--iux-muted-foreground)">{loadError}</span>
        </div>
      </Section>
    );
  }
  if (!state) return <Section id="mcp-claude-plugin" title="Install as a Claude plugin"><Skeleton rows={2} /></Section>;

  const { code, desktop, checkoutVersion } = state;
  const install = code.installed.find((row) => row.scope === "user") ?? code.installed[0];
  const outdated = !!install && install.version !== checkoutVersion;
  const extension = desktop.extension;
  const duplicates = [...code.duplicates.map((row) => row.name), ...extension.duplicates];

  return (
    <div id="mcp-claude-plugin" className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-3">
        <Section id="mcp-card-code" title="Claude Code plugin" description="Server, lab skills and a session check.">
          {!code.cli ? <State tone="danger" label="Claude Code not found" />
            : !install ? <State tone={undefined} label="Not installed" />
              : !install.enabled ? <State tone="warning" label="Disabled" version={install.version} />
                : outdated ? <State tone="warning" label="Update available" version={`${install.version} → ${checkoutVersion}`} />
                  : <State tone="success" label="Installed" version={install.version} />}
          {code.error ? <Status value={{ ok: false, text: code.error }} /> : null}
          <div className="flex flex-wrap gap-2">
            {!install ? <Action primary label="Install plugin" disabled={busy || !code.cli} onClick={() => void preview("install")} />
              : (
                <>
                  <Action primary label="Update plugin" disabled={busy} onClick={() => void preview("update")} />
                  <Action label={install.enabled ? "Disable" : "Enable"} disabled={busy} onClick={() => void preview(install.enabled ? "disable" : "enable")} />
                </>
              )}
          </div>
        </Section>

        <Section id="mcp-card-desktop" title="Claude Desktop extension" description="Claude Desktop asks you to confirm the install.">
          {desktop.app.installed === false ? <State tone="danger" label="Claude Desktop not found" />
            : !extension.installed ? <State tone={undefined} label="Not installed" />
              : extension.updateAvailable ? <State tone="warning" label="Update available" version={`${extension.version} → ${checkoutVersion}`} />
                : <State tone="success" label="Installed" version={extension.version} />}
          <Action primary label={extension.installed ? "Update extension" : "Install extension"} disabled={busy || desktop.app.installed === false} onClick={() => void preview("extension-install")} />
        </Section>

        <Section id="mcp-card-updates" title="Updates" description="Checking asks GitHub for the published version.">
          {!updates ? <State tone={undefined} label="Not checked" version={checkoutVersion} />
            : updates.published?.note ? <State tone="warning" label="Published version unavailable" />
              : updates.updatesAvailable.length ? <State tone="warning" label="Update available" version={updates.updatesAvailable.join(", ")} />
                : <State tone="success" label="Up to date" version={checkoutVersion} />}
          <div className="flex flex-wrap gap-2">
            <Action primary label="Check for updates" disabled={busy} onClick={() => void check()} />
            <Action label="Turn on daily check" disabled={busy || !install} onClick={() => void preview("configure", true)} />
            <Action label="Turn off daily check" disabled={busy || !install} onClick={() => void preview("configure", false)} />
          </div>
        </Section>
      </div>

      {duplicates.length ? <p className="text-sm text-(--iux-muted-foreground)">Other MCP entries also run this server: <span translate="no">{duplicates.join(", ")}</span></p> : null}
      {state.doctor.checks.filter((row) => !row.ok).map((row) => <Status key={row.name} value={{ ok: false, text: row.fix ?? row.detail }} />)}
      <Status value={note} />

      {plan ? (
        <Modal title="Review the change" description="Nothing has changed yet." onClose={() => setPlan(null)}>
          <div className="flex flex-col gap-3">
            {plan.commands.map((command) => <Terminal key={command} command={command} />)}
            {[...plan.manual, ...plan.warnings].map((text) => <p key={text} className="text-sm text-(--iux-muted-foreground)">{text}</p>)}
            <div className="flex flex-wrap justify-end gap-2">
              <Action label="Cancel" onClick={() => setPlan(null)} />
              <Action primary label="Confirm and run" disabled={busy || !plan.commands.length} onClick={() => void confirm(plan.token)} />
            </div>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
