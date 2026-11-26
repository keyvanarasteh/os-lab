/**
 * CLA-01: Android emulator (AVD) inventory on every desktop. Delete and wipe
 * go through a previewed, single-use action. Only shut-down AVDs can change.
 */
import { useEffect, useMemo, useState } from "react";
import { Badge, CopyButton, Empty, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type CleanupEmulatorPreview, type CleanupEmulatorResult, type CleanupEmulators } from "../../lib/api";
import { bytes, riskLabel, riskTone } from "./format";

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export function emulatorActionLabel(actionId: string): string {
  const labels: Record<string, string> = {
    "emulators.delete-unavailable": "Delete unavailable emulators",
    "emulators.wipe-data": "Wipe selected emulator data",
    "emulators.delete-avds": "Delete selected emulators"
  };
  return labels[actionId] ?? actionId;
}

export function EmulatorsCard({ now }: { now: number }) {
  const [inventory, setInventory] = useState<CleanupEmulators | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<CleanupEmulatorPreview | null>(null);
  const [job, setJob] = useState<CleanupAuxJob<CleanupEmulatorResult> | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  function load() {
    setLoadError("");
    void api.cleanupEmulators().then((value) => {
      setInventory(value);
      setSelected((old) => new Set([...old].filter((id) => value.devices.some((item) => item.id === id && item.state === "Shutdown"))));
    }).catch((reason) => setLoadError(errorText(reason)));
  }
  useEffect(load, []);

  useEffect(() => {
    if (job?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupEmulatorResult>(job.id)
        .then((next) => { if (alive) { setJob(next); if (next.state !== "running") load(); } })
        .catch((reason) => { if (alive) setJob((old) => old ? { ...old, state: "failed", error: errorText(reason) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.state]);

  const devices = useMemo(() => [...(inventory?.devices ?? [])].sort((a, b) =>
    Number(a.available) - Number(b.available) || (b.sizeBytes ?? 0) - (a.sizeBytes ?? 0)), [inventory]);
  const unavailable = devices.filter((item) => !item.available);
  const total = devices.reduce((sum, item) => sum + (item.sizeBytes ?? 0), 0);
  const unavailableBytes = unavailable.reduce((sum, item) => sum + (item.sizeBytes ?? 0), 0);
  const busy = pending || job?.state === "running";

  async function loadPreview(actionId: string, deviceIds?: string[]) {
    setPending(true); setError(""); setPreview(null); setJob(null);
    try { setPreview(await api.cleanupEmulatorPreview(actionId, deviceIds)); }
    catch (reason) { setError(errorText(reason)); }
    finally { setPending(false); }
  }

  async function run() {
    if (!preview || preview.expiresAt <= now || !preview.candidateCount) return;
    setPending(true); setError("");
    try { setJob(await api.cleanupEmulatorRun(preview.previewId)); setPreview(null); setSelected(new Set()); }
    catch (reason) { setError(errorText(reason)); }
    finally { setPending(false); }
  }

  function toggle(id: string) {
    setSelected((old) => { const next = new Set(old); if (next.has(id)) next.delete(id); else next.add(id); return next; });
    setPreview(null);
  }

  return <Section id="scan-emulators" title="Android emulators" description="AVDs on this computer. Preview before wiping or deleting; only shut-down emulators can be changed.">
    {loadError && <><Status value={{ ok: false, text: loadError }} /><button type="button" className="iux-btn mt-2" onClick={load}>Retry</button></>}
    {!inventory && !loadError && <p role="status">Checking Android emulators…</p>}
    {inventory && !inventory.available && <p>{inventory.reason || "No Android emulator folder on this computer."}</p>}
    {inventory?.available && <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span><span dir="ltr" className="font-semibold tabular-nums">{devices.length}</span> <span>emulators</span></span>
        <span className="text-(--iux-muted-foreground)">·</span>
        <span dir="ltr" className="tabular-nums">{bytes(total)}</span>
        {unavailable.length > 0 && <Badge tone="warning">{unavailable.length} <span>unavailable</span></Badge>}
        <button type="button" className="iux-btn ms-auto" data-variant="ghost" disabled={busy} onClick={load}>Refresh</button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="iux-btn" disabled={busy || !unavailable.length} onClick={() => void loadPreview("emulators.delete-unavailable")}>
          <span>Delete unavailable emulators</span>
          {unavailable.length > 0 && <span dir="ltr" className="tabular-nums text-(--iux-muted-foreground)">{bytes(unavailableBytes)}</span>}
        </button>
        <button type="button" className="iux-btn" disabled={busy || !selected.size} onClick={() => void loadPreview("emulators.wipe-data", [...selected])}>Wipe selected data</button>
        <button type="button" className="iux-btn" disabled={busy || !selected.size} onClick={() => void loadPreview("emulators.delete-avds", [...selected])}>Delete selected</button>
      </div>
      {!devices.length ? <div className="mt-3"><Empty>No Android emulators were found.</Empty></div> :
        <ul className="iux-scroll mt-3 max-h-80 divide-y divide-(--iux-border) overflow-auto rounded-md border border-(--iux-border)">
          {devices.map((device) => {
            const locked = device.state !== "Shutdown";
            return <li key={device.id}>
              <label className={`flex items-center gap-3 px-3 py-2 text-sm ${locked ? "opacity-70" : "cursor-pointer"}`}>
                <input type="checkbox" disabled={locked || busy} checked={selected.has(device.id)} onChange={() => toggle(device.id)}
                  aria-label={device.name ?? device.id} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium" translate="no">{device.name ?? device.id}</span>
                  <span className="block truncate text-xs text-(--iux-muted-foreground)" translate="no">{device.runtime || device.path}</span>
                </span>
                {!device.available && <Badge tone="warning">Unavailable</Badge>}
                {locked && <Badge>Running</Badge>}
                <span dir="ltr" className="w-20 shrink-0 text-end tabular-nums">{device.sizeBytes === null || device.sizeBytes === undefined ? "—" : bytes(device.sizeBytes)}</span>
              </label>
            </li>;
          })}
        </ul>}
      {preview && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <strong>{emulatorActionLabel(preview.actionId)}</strong>
          <Badge tone={riskTone(preview.risk)}>{riskLabel(preview.risk)}</Badge>
          <span className="tabular-nums text-(--iux-muted-foreground)">{preview.candidateCount} <span>emulators</span> · <span dir="ltr">{bytes(preview.bytes)}</span></span>
          <span className="ms-auto"><CopyButton text={preview.command.join(" ")} label="Copy command" /></span>
        </div>
        <p className="mt-1 break-all text-xs"><span className="font-medium text-(--iux-muted-foreground)">Command</span> <code translate="no">{preview.command.join(" ")}</code></p>
        <p className="mt-1 text-xs text-(--iux-muted-foreground)" translate="no">{preview.devices.map((item) => item.name ?? item.id).join(", ")}</p>
        {preview.actionId === "emulators.wipe-data"
          ? <p className="mt-1 text-xs">Wipes userdata, cache and snapshots. The AVD definition stays.</p>
          : <p className="mt-1 text-xs text-(--iux-danger)">Deleted emulators and their apps and data cannot be restored.</p>}
        {preview.expiresAt <= now ? <p className="mt-2">Preview expired. Preview again.</p> :
          <div className="mt-2 flex gap-2">
            <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !preview.candidateCount} onClick={() => void run()}>Confirm</button>
            <button type="button" className="iux-btn" onClick={() => setPreview(null)}>Cancel</button>
          </div>}
      </div>}
      {job?.state === "running" && <p className="mt-2" role="status">Android emulator cleanup in progress…</p>}
      {job?.state === "done" && job.result && <p className="mt-2" role="status">Done. <span dir="ltr">{bytes(job.result.bytesFreed)}</span> <span>freed</span></p>}
      {job?.state === "failed" && <Status value={{ ok: false, text: job.error || job.result?.error || "Android emulator cleanup failed." }} />}
    </>}
    {error && <Status value={{ ok: false, text: error }} />}
  </Section>;
}
