/**
 * CLS-01: Xcode simulator devices on the Advanced scan tab. The inventory is
 * read-only; erase and delete go through a previewed, single-use simctl action
 * (`POST /api/cleanup/simulators/preview` → `/run`) and land in the audit
 * history. Only shut-down simulators can be selected.
 */
import { useEffect, useMemo, useState } from "react";
import { Badge, CopyButton, Empty, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type CleanupSimulatorPreview, type CleanupSimulatorResult, type CleanupSimulators } from "../../lib/api";
import { bytes, riskLabel, riskTone } from "./format";

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

/** `com.apple.CoreSimulator.SimRuntime.iOS-18-0` → `iOS 18.0`. */
export function runtimeLabel(runtime: string): string {
  const tail = runtime.split(".").at(-1) ?? runtime;
  const [os, ...version] = tail.split("-");
  return version.length ? `${os} ${version.join(".")}` : tail;
}

export function simulatorActionLabel(actionId: string): string {
  const labels: Record<string, string> = {
    "simulators.delete-unavailable": "Delete unavailable simulators",
    "simulators.erase-devices": "Erase selected simulators",
    "simulators.delete-devices": "Delete selected simulators",
    "simulators.delete-runtime": "Delete simulator runtime"
  };
  return labels[actionId] ?? actionId;
}

export function SimulatorsCard({ now }: { now: number }) {
  const [inventory, setInventory] = useState<CleanupSimulators | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<CleanupSimulatorPreview | null>(null);
  const [job, setJob] = useState<CleanupAuxJob<CleanupSimulatorResult> | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  function load() {
    setLoadError("");
    void api.cleanupSimulators().then((value) => {
      setInventory(value);
      setSelected((old) => new Set([...old].filter((id) => value.devices.some((d) => d.id === id && d.state === "Shutdown"))));
    }).catch((reason) => setLoadError(errorText(reason)));
  }
  useEffect(load, []);

  useEffect(() => {
    if (job?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupSimulatorResult>(job.id)
        .then((next) => { if (!alive) return; setJob(next); if (next.state !== "running") load(); })
        .catch((reason) => { if (alive) setJob((old) => old ? { ...old, state: "failed", error: errorText(reason) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.state]);

  const devices = useMemo(() => [...(inventory?.devices ?? [])].sort((a, b) =>
    Number(a.available) - Number(b.available) || (b.sizeBytes ?? 0) - (a.sizeBytes ?? 0)), [inventory]);
  const unavailable = devices.filter((d) => !d.available);
  const total = devices.reduce((sum, d) => sum + (d.sizeBytes ?? 0), 0);
  const unavailableBytes = unavailable.reduce((sum, d) => sum + (d.sizeBytes ?? 0), 0);
  const busy = pending || job?.state === "running";
  const runtimes = useMemo(() => [...(inventory?.runtimes ?? [])].sort((a, b) => (b.sizeBytes ?? 0) - (a.sizeBytes ?? 0)), [inventory]);
  const usedBy = (runtime: string) => devices.filter((d) => d.runtime === runtime).length;
  const isRuntimePreview = preview?.actionId === "simulators.delete-runtime";

  async function loadPreview(actionId: string, deviceIds?: string[]) {
    setPending(true); setError(""); setPreview(null); setJob(null);
    try { setPreview(await api.cleanupSimulatorPreview(actionId, deviceIds)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setPending(false); }
  }

  async function run() {
    if (!preview || preview.expiresAt <= now || !preview.candidateCount) return;
    setPending(true); setError("");
    try { setJob(await api.cleanupSimulatorRun(preview.previewId)); setPreview(null); setSelected(new Set()); }
    catch (reason) { setError(errorText(reason)); }
    finally { setPending(false); }
  }

  function toggle(id: string) {
    setSelected((old) => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; });
    setPreview(null);
  }

  return <Section id="scan-simulators" title="Simulators" description="Xcode simulator devices. Preview before erasing or deleting; only shut-down simulators can be changed.">
    {loadError && <><Status value={{ ok: false, text: loadError }} /><button type="button" className="iux-btn mt-2" onClick={load}>Retry</button></>}
    {!inventory && !loadError && <p role="status">Checking simulators…</p>}
    {inventory && !inventory.available && <p>{inventory.reason || "Simulator tooling is unavailable."}</p>}
    {inventory && (inventory.available || runtimes.length > 0 || Boolean(inventory.runtimeReason)) && <>
      {inventory.available && <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span><span dir="ltr" className="font-semibold tabular-nums">{devices.length}</span> <span>simulators</span></span>
        <span className="text-(--iux-muted-foreground)">·</span>
        <span dir="ltr" className="tabular-nums">{bytes(total)}</span>
        {unavailable.length > 0 && <Badge tone="warning">{unavailable.length} <span>unavailable</span></Badge>}
        <button type="button" className="iux-btn ms-auto" data-variant="ghost" disabled={busy} onClick={load}>Refresh</button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="iux-btn" disabled={busy || !unavailable.length} onClick={() => void loadPreview("simulators.delete-unavailable")}>
          <span>Delete unavailable simulators</span>
          {unavailable.length > 0 && <span dir="ltr" className="tabular-nums text-(--iux-muted-foreground)">{bytes(unavailableBytes)}</span>}
        </button>
        <button type="button" className="iux-btn" disabled={busy || !selected.size} onClick={() => void loadPreview("simulators.erase-devices", [...selected])}>Erase selected</button>
        <button type="button" className="iux-btn" disabled={busy || !selected.size} onClick={() => void loadPreview("simulators.delete-devices", [...selected])}>Delete selected</button>
      </div>

      {!devices.length ? <div className="mt-3"><Empty>No simulators were found.</Empty></div> :
        <ul className="iux-scroll mt-3 max-h-80 divide-y divide-(--iux-border) overflow-auto rounded-md border border-(--iux-border)">
          {devices.map((device) => {
            const locked = device.state !== "Shutdown";
            return <li key={device.id}>
              <label className={`flex items-center gap-3 px-3 py-2 text-sm ${locked ? "opacity-70" : "cursor-pointer"}`}>
                <input type="checkbox" disabled={locked || busy} checked={selected.has(device.id)} onChange={() => toggle(device.id)}
                  aria-label={device.name ?? device.id} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{device.name ?? device.id}</span>
                  <span className="block truncate text-xs text-(--iux-muted-foreground)" translate="no">{runtimeLabel(device.runtime)}</span>
                </span>
                {!device.available && <Badge tone="warning">Unavailable</Badge>}
                {locked && <Badge>{device.state === "Booted" ? "Running" : device.state ?? "Unknown"}</Badge>}
                <span dir="ltr" className="w-20 shrink-0 text-end tabular-nums">{device.sizeBytes === null ? "—" : bytes(device.sizeBytes)}</span>
              </label>
            </li>;
          })}
        </ul>}
      </>}

      {runtimes.length > 0 && <div className="mt-4">
        <h3 className="text-xs font-medium uppercase tracking-wide text-(--iux-muted-foreground)">Runtimes</h3>
        <ul className="mt-2 divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
          {runtimes.map((runtime) => <li key={runtime.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium" translate="no">{runtime.name}</span>
              <span className="block truncate text-xs text-(--iux-muted-foreground)">
                <span translate="no">{runtime.build ?? ""}</span> · {inventory.available ? <>{usedBy(runtime.runtime)} <span>simulators</span></> : <span>usage unknown</span>}
              </span>
            </span>
            {!runtime.deletable && <Badge>Managed by Xcode</Badge>}
            <span dir="ltr" className="w-20 shrink-0 text-end tabular-nums">{runtime.sizeBytes === null ? "—" : bytes(runtime.sizeBytes)}</span>
            <button type="button" className="iux-btn" disabled={busy || !runtime.deletable}
              onClick={() => void loadPreview("simulators.delete-runtime", [runtime.id])}>Delete</button>
          </li>)}
        </ul>
      </div>}
      {inventory.runtimeReason && <p className="mt-3 text-xs text-(--iux-muted-foreground)">{inventory.runtimeReason}</p>}

      {preview && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <strong>{simulatorActionLabel(preview.actionId)}</strong>
          <Badge tone={riskTone(preview.risk)}>{riskLabel(preview.risk)}</Badge>
          <span className="tabular-nums text-(--iux-muted-foreground)">{isRuntimePreview ? null : <>{preview.candidateCount} <span>simulators</span> · </>}<span dir="ltr">{bytes(preview.bytes)}</span></span>
          <span className="ms-auto"><CopyButton text={preview.command.join(" ")} label="Copy command" /></span>
        </div>
        <p className="mt-1 break-all text-xs"><span className="font-medium text-(--iux-muted-foreground)">Command</span> <code translate="no">{preview.command.join(" ")}</code></p>
        <p className="mt-1 text-xs text-(--iux-muted-foreground)">{preview.devices.map((d) => d.name ?? d.id).join(", ")}</p>
        {isRuntimePreview ? <p className="mt-1 text-xs text-(--iux-danger)">Simulators that use this runtime become unavailable. Xcode can download the runtime again.</p>
          : preview.actionId !== "simulators.erase-devices" && <p className="mt-1 text-xs text-(--iux-danger)">Deleted simulators and their apps and data cannot be restored.</p>}
        {preview.expiresAt <= now ? <p className="mt-2">Preview expired. Preview again.</p> :
          <div className="mt-2 flex gap-2">
            <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !preview.candidateCount} onClick={() => void run()}>Confirm</button>
            <button type="button" className="iux-btn" onClick={() => setPreview(null)}>Cancel</button>
          </div>}
      </div>}
      {job?.state === "running" && <p className="mt-2" role="status">Simulator cleanup in progress…</p>}
      {job?.state === "done" && job.result && <p className="mt-2" role="status">Done. <span dir="ltr">{bytes(job.result.bytesFreed)}</span> <span>freed</span></p>}
      {job?.state === "failed" && <Status value={{ ok: false, text: job.error || job.result?.error || "Simulator cleanup failed." }} />}
    </>}
    {error && <Status value={{ ok: false, text: error }} />}
  </Section>;
}
