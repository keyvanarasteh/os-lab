/**
 * CLS-02: Simulator storage on the Relocation tab. Choose the disk that should
 * hold the iOS Simulator devices folder and when to suggest moving it. "Move
 * now" hands the destination to the Relocation card, which plans the move and
 * opens its confirm dialog; nothing moves from here directly.
 */
import { useEffect, useState } from "react";
import { Badge, Section, Status } from "../../components/ui";
import { api, type CleanupSimulatorStorage } from "../../lib/api";
import { bytes } from "./format";

const GIB = 1024 ** 3;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

function stateBadge(report: CleanupSimulatorStorage) {
  if (report.state === "linked") return <Badge tone="success">On another disk</Badge>;
  if (report.state === "disk-missing") return <Badge tone="danger">Disk not connected</Badge>;
  if (report.state === "local") return <Badge>On the system disk</Badge>;
  return <Badge>Not found</Badge>;
}

export function SimulatorStorageCard({ onMove, refreshKey = 0 }: { onMove: (entryId: string, destination: string) => void; refreshKey?: number }) {
  const [report, setReport] = useState<CleanupSimulatorStorage | null>(null);
  const [error, setError] = useState("");
  const [destination, setDestination] = useState("");
  const [suggest, setSuggest] = useState(true);
  const [floorGiB, setFloorGiB] = useState(20);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  function apply(value: CleanupSimulatorStorage) {
    setReport(value);
    if (value.config) {
      setDestination(value.config.destination ?? value.destinations?.[0]?.mountPoint ?? "");
      setSuggest(value.config.suggest);
      setFloorGiB(Math.round(value.config.floorBytes / GIB));
    }
  }
  useEffect(() => {
    let alive = true;
    void api.cleanupSimulatorStorage().then((value) => { if (alive) apply(value); })
      .catch((reason) => { if (alive) setError(errorText(reason)); });
    return () => { alive = false; };
  }, [refreshKey]);

  async function save() {
    setSaving(true); setError(""); setSaved(false);
    try {
      apply(await api.cleanupSimulatorStorageSave({ destination: destination || null, suggest, floorBytes: Math.round(floorGiB) * GIB }));
      setSaved(true);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  if (report && !report.available) return null;
  const chosen = report?.destinations?.find((item) => item.mountPoint === destination);
  const suggestion = report?.suggestion?.action;

  return <Section id="simulator-storage" title="Simulator storage" description="Keep iOS Simulator devices on another disk. Simulator runtimes stay managed by macOS.">
    {!report && !error && <p role="status">Checking simulator storage…</p>}
    {report?.available && <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {stateBadge(report)}
        {report.state === "linked" && <span className="break-all text-xs text-(--iux-muted-foreground)" translate="no" dir="ltr">{report.target}</span>}
        {report.home && <span className="ms-auto text-xs text-(--iux-muted-foreground)">
          <span>System disk</span> · <span dir="ltr" className="tabular-nums">{bytes(report.home.freeBytes ?? 0)}</span> <span>free</span>
        </span>}
      </div>
      {suggestion === "reconnect" && <p className="mt-3 rounded-md border border-(--iux-danger)/50 bg-(--iux-danger)/5 px-3 py-2 text-sm">
        Connect the disk that holds your simulators before opening Simulator. Restore brings them back to the system disk.
      </p>}
      {suggestion === "move" && <p className="mt-3 rounded-md border border-(--iux-warning)/50 bg-(--iux-warning)/10 px-3 py-2 text-sm">
        The system disk is below your free-space floor. Move the simulators to free space.
      </p>}
      {report.configError && <Status value={{ ok: false, text: report.configError }} />}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="block text-xs font-medium text-(--iux-muted-foreground)">Disk for simulators</span>
          <select className="iux-input mt-1 w-full" value={destination} disabled={saving || !report.destinations?.length}
            onChange={(event) => { setDestination(event.target.value); setSaved(false); }}>
            {!report.destinations?.length && <option value="">No other disk is connected</option>}
            {report.destinations?.map((item) => <option key={item.mountPoint} value={item.mountPoint}>
              {item.name || item.mountPoint} · {bytes(item.freeBytes)} free
            </option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-xs font-medium text-(--iux-muted-foreground)">Suggest moving below (GiB free on the system disk)</span>
          <input type="number" min={1} max={2048} className="iux-input mt-1 w-full tabular-nums" value={floorGiB} disabled={saving || !suggest}
            onChange={(event) => { setFloorGiB(Number(event.target.value) || 1); setSaved(false); }} />
        </label>
      </div>
      {chosen?.kind === "removable" && <p className="mt-2 text-xs text-(--iux-warning)">This disk can be unplugged. Simulator cannot start while it is disconnected.</p>}
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={suggest} disabled={saving} onChange={(event) => { setSuggest(event.target.checked); setSaved(false); }} />
        <span>Suggest moving when the system disk runs low, and notify with the monitor</span>
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="iux-btn" disabled={saving} onClick={() => void save()}>Save</button>
        {report.state === "local" && report.entryId && <button type="button" className="iux-btn" data-variant={suggestion === "move" ? "primary" : undefined}
          disabled={saving || !destination} onClick={() => onMove(report.entryId!, destination)}>Move now</button>}
        {saved && <span role="status" className="text-xs text-(--iux-success)">Saved on this computer</span>}
      </div>
    </>}
    {error && <Status value={{ ok: false, text: error }} />}
  </Section>;
}

/** CLS-02: one line on the overview when simulators should move or their disk is missing. */
export function SimulatorStorageNotice({ href }: { href: string }) {
  const [report, setReport] = useState<CleanupSimulatorStorage | null>(null);
  useEffect(() => {
    let alive = true;
    void api.cleanupSimulatorStorage().then((value) => { if (alive) setReport(value); }).catch(() => { /* a hint only; hide on failure */ });
    return () => { alive = false; };
  }, []);
  const action = report?.suggestion?.action;
  if (!report?.available || !action) return null;
  return <div role="status" className={`rounded-md border p-3 text-sm ${action === "reconnect" ? "border-(--iux-danger)/50 bg-(--iux-danger)/5" : "border-(--iux-warning)/50 bg-(--iux-warning)/10"}`}>
    <p className="font-medium">{action === "reconnect" ? "Simulator disk is not connected" : "Move iOS simulators off the system disk"}</p>
    <p className="mt-1 text-xs"><a className="underline" href={href}>Open Simulator storage</a></p>
  </div>;
}
