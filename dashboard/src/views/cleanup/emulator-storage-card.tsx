/**
 * CLA-02: AVD folder on the Relocation tab and the dashboard setup card.
 * Move now hands the destination to the Relocation card. Windows uses a
 * junction; POSIX uses a symlink. Nothing moves from here directly.
 */
import { useEffect, useState } from "react";
import { Badge, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type CleanupEmulatorPreview, type CleanupEmulatorResult, type CleanupEmulators, type CleanupEmulatorStorage, type CleanupRelocationPlan, type CleanupRelocationRun } from "../../lib/api";
import { bytes, riskLabel, riskTone } from "./format";
import { RelocationConfirmDialog } from "./relocation-card";
import { emulatorActionLabel } from "./emulators-card";

const GIB = 1024 ** 3;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

function stateBadge(report: CleanupEmulatorStorage) {
  if (report.state === "linked") return <Badge tone="success">On another disk</Badge>;
  if (report.state === "disk-missing") return <Badge tone="danger">Disk not connected</Badge>;
  if (report.state === "local") return <Badge>On the system disk</Badge>;
  return <Badge>Not found</Badge>;
}

export function EmulatorStorageCard({ onMove, refreshKey = 0 }: { onMove: (entryId: string, destination: string) => void; refreshKey?: number }) {
  const [report, setReport] = useState<CleanupEmulatorStorage | null>(null);
  const [error, setError] = useState("");
  const [destination, setDestination] = useState("");
  const [suggest, setSuggest] = useState(true);
  const [floorGiB, setFloorGiB] = useState(20);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  function apply(value: CleanupEmulatorStorage) {
    setReport(value);
    if (value.config) {
      setDestination(value.config.destination ?? value.destinations?.[0]?.mountPoint ?? "");
      setSuggest(value.config.suggest);
      setFloorGiB(Math.round(value.config.floorBytes / GIB));
    }
  }
  useEffect(() => {
    let alive = true;
    void api.cleanupEmulatorStorage().then((value) => { if (alive) apply(value); })
      .catch((reason) => { if (alive) setError(errorText(reason)); });
    return () => { alive = false; };
  }, [refreshKey]);

  async function save() {
    setSaving(true); setError(""); setSaved(false);
    try {
      apply(await api.cleanupEmulatorStorageSave({ destination: destination || null, suggest, floorBytes: Math.round(floorGiB) * GIB }));
      setSaved(true);
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }

  if (report && !report.available) return null;
  const chosen = report?.destinations?.find((item) => item.mountPoint === destination);
  const suggestion = report?.suggestion?.action;

  return <Section id="emulator-storage" title="Emulator storage" description="Keep Android Virtual Devices on another disk. The emulator still opens them from the original path.">
    {!report && !error && <p role="status">Checking emulator storage…</p>}
    {report?.available && <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {stateBadge(report)}
        {report.state === "linked" && <span className="break-all text-xs text-(--iux-muted-foreground)" translate="no" dir="ltr">{report.target}</span>}
        {report.home && <span className="ms-auto text-xs text-(--iux-muted-foreground)">
          <span>System disk</span> · <span dir="ltr" className="tabular-nums">{bytes(report.home.freeBytes ?? 0)}</span> <span>free</span>
        </span>}
      </div>
      {suggestion === "reconnect" && <p className="mt-3 rounded-md border border-(--iux-danger)/50 bg-(--iux-danger)/5 px-3 py-2 text-sm">
        Connect the disk that holds your emulators before opening Android Studio.
      </p>}
      {suggestion === "move" && <p className="mt-3 rounded-md border border-(--iux-warning)/50 bg-(--iux-warning)/10 px-3 py-2 text-sm">
        The system disk is below your free-space floor. Move the emulators to free space.
      </p>}
      {report.configError && <Status value={{ ok: false, text: report.configError }} />}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="block text-xs font-medium text-(--iux-muted-foreground)">Disk for emulators</span>
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
      {chosen?.kind === "removable" && <p className="mt-2 text-xs text-(--iux-warning)">This disk can be unplugged. The emulator cannot start while it is disconnected.</p>}
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

type PendingPlan = { plan: CleanupRelocationPlan; plannedAt: number };

export function EmulatorSetupCard() {
  const [report, setReport] = useState<CleanupEmulatorStorage | null>(null);
  const [inventory, setInventory] = useState<CleanupEmulators | null>(null);
  const [interrupted, setInterrupted] = useState(false);
  const [destination, setDestination] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<PendingPlan | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [planJob, setPlanJob] = useState<CleanupAuxJob<CleanupRelocationPlan> | null>(null);
  const [runJob, setRunJob] = useState<CleanupAuxJob<CleanupRelocationRun> | null>(null);
  const [result, setResult] = useState<CleanupRelocationRun | null>(null);
  const [preview, setPreview] = useState<CleanupEmulatorPreview | null>(null);
  const [emuJob, setEmuJob] = useState<CleanupAuxJob<CleanupEmulatorResult> | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now() / 1000);

  function load() {
    void api.cleanupEmulatorStorage().then((value) => {
      setReport(value);
      setDestination((current) => current || value.config?.destination || value.destinations?.[0]?.mountPoint || "");
    }).catch(() => setReport(null));
    void api.cleanupEmulators().then(setInventory).catch(() => setInventory(null));
    void api.cleanupRelocation().then((status) => {
      setInterrupted(!!(status.entries ?? []).some((entry) => entry.entryId === "simulators.android-avd" && entry.interrupted));
    }).catch(() => setInterrupted(false));
  }
  useEffect(load, []);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000); return () => window.clearInterval(timer); }, []);

  useEffect(() => {
    const job = planJob?.state === "running" ? planJob : runJob?.state === "running" ? runJob : emuJob?.state === "running" ? emuJob : null;
    if (!job) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob(job.id).then((next) => {
        if (!alive) return;
        if (job.kind === "relocation-plan") {
          const typed = next as CleanupAuxJob<CleanupRelocationPlan>;
          setPlanJob(typed);
          if (typed.state === "done" && typed.result) {
            setPending({ plan: typed.result, plannedAt: Math.floor(Date.now() / 1000) });
            setConfirmOpen(true);
          } else if (typed.state === "failed") setError(typed.error || "Planning the move failed.");
        } else if (job.kind === "relocation-run") {
          const typed = next as CleanupAuxJob<CleanupRelocationRun>;
          setRunJob(typed);
          if (typed.state === "failed") setError(typed.error || "The move failed. The original folder is still in place.");
          if (typed.state !== "running") { setResult(typed.result); load(); }
        } else {
          const typed = next as CleanupAuxJob<CleanupEmulatorResult>;
          setEmuJob(typed);
          if (typed.state !== "running") void api.cleanupEmulators().then(setInventory).catch(() => {});
        }
      }).catch((reason) => { if (alive) setError(errorText(reason)); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [planJob?.id, planJob?.state, runJob?.id, runJob?.state, emuJob?.id, emuJob?.state]);

  const unavailable = (inventory?.devices ?? []).filter((item) => !item.available);
  const unavailableBytes = unavailable.reduce((sum, item) => sum + (item.sizeBytes ?? 0), 0);
  const needsStorage = !!report?.available && (report.state === "local" || report.state === "disk-missing" || interrupted);
  const needsCleanup = !!inventory?.available && unavailable.length > 0;
  const working = busy || planJob?.state === "running" || runJob?.state === "running" || emuJob?.state === "running";
  const step = runJob?.progress as { step?: string; stepsDone?: number; stepsTotal?: number } | null | undefined;

  if (!needsStorage && !needsCleanup) return null;

  async function move(action: "move" | "resume") {
    if (!report?.entryId || !destination) { setError("Choose a disk first."); return; }
    setBusy(true); setError(""); setResult(null);
    try {
      if (action === "move") {
        await api.cleanupEmulatorStorageSave({
          destination, suggest: report.config?.suggest ?? true, floorBytes: report.config?.floorBytes ?? 20 * GIB
        });
      }
      setPlanJob(await api.cleanupRelocationPlan(action, report.entryId, destination));
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  async function runMove() {
    if (!pending) return;
    setBusy(true); setError("");
    try {
      setRunJob(await api.cleanupRelocationRun(pending.plan.previewId));
      setConfirmOpen(false); setPending(null); setPlanJob(null);
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  async function previewUnavailable() {
    setBusy(true); setError(""); setPreview(null); setEmuJob(null);
    try { setPreview(await api.cleanupEmulatorPreview("emulators.delete-unavailable")); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  async function runUnavailable() {
    if (!preview || preview.expiresAt <= now || !preview.candidateCount) return;
    setBusy(true); setError("");
    try { setEmuJob(await api.cleanupEmulatorRun(preview.previewId)); setPreview(null); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  return <Section id="emulator-setup" title="Android emulator setup"
    description="Android Virtual Devices should live on a non-system disk. Unavailable AVDs can be deleted through a previewed avdmanager action.">
    {error && <Status value={{ ok: false, text: error }} />}
    {needsStorage && report && <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {stateBadge(report)}
        {report.home && <span className="ms-auto text-xs text-(--iux-muted-foreground)">
          <span>System disk</span> · <span dir="ltr" className="tabular-nums">{bytes(report.home.freeBytes ?? 0)}</span> <span>free</span>
        </span>}
      </div>
      {report.state === "disk-missing" && <p className="mt-3 rounded-md border border-(--iux-danger)/50 bg-(--iux-danger)/5 px-3 py-2 text-sm">
        Connect the disk that holds your emulators before opening Android Studio.
      </p>}
      {report.state === "local" && <p className="mt-3 rounded-md border border-(--iux-warning)/50 bg-(--iux-warning)/10 px-3 py-2 text-sm">
        Android Virtual Devices are still on the system disk. Move them to another disk; Android Studio still opens them from the original path.
      </p>}
      {interrupted && <p className="mt-3 rounded-md border border-(--iux-warning)/50 bg-(--iux-warning)/10 px-3 py-2 text-sm">
        A previous move was interrupted. Resume it before starting a new one.
      </p>}
      {report.state === "local" && !report.destinations?.length && <p className="mt-3 text-sm">Connect another disk to move emulators off the system disk.</p>}
      {!!report.destinations?.length && report.state !== "disk-missing" && <label className="mt-3 block text-sm">
        <span className="block text-xs font-medium text-(--iux-muted-foreground)">Disk for emulators</span>
        <select className="iux-input mt-1 w-full max-w-md" value={destination} disabled={working}
          onChange={(event) => setDestination(event.target.value)}>
          {report.destinations.map((item) => <option key={item.mountPoint} value={item.mountPoint}>
            {item.name || item.mountPoint} · {bytes(item.freeBytes)} free
          </option>)}
        </select>
      </label>}
      <div className="mt-3 flex flex-wrap gap-2">
        {interrupted && <button type="button" className="iux-btn" data-variant="primary" disabled={working || !destination}
          onClick={() => void move("resume")}>Resume interrupted move</button>}
        {report.state === "local" && !!report.destinations?.length && !interrupted &&
          <button type="button" className="iux-btn" data-variant="primary" disabled={working || !destination}
            onClick={() => void move("move")}>Move emulators off the system disk</button>}
      </div>
    </>}
    {needsCleanup && <div className="mt-4">
      <p className="text-sm"><span dir="ltr" className="font-semibold tabular-nums">{unavailable.length}</span> unavailable emulators
        {unavailableBytes > 0 && <> · <span dir="ltr" className="tabular-nums">{bytes(unavailableBytes)}</span></>}</p>
      <button type="button" className="iux-btn mt-2" disabled={working} onClick={() => void previewUnavailable()}>Delete unavailable emulators</button>
    </div>}
    {preview && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <strong>{emulatorActionLabel(preview.actionId)}</strong>
        <Badge tone={riskTone(preview.risk)}>{riskLabel(preview.risk)}</Badge>
        <span dir="ltr" className="tabular-nums">{bytes(preview.bytes)}</span>
      </div>
      <p className="mt-1 text-xs text-(--iux-danger)">Deleted emulators and their apps and data cannot be restored.</p>
      {preview.expiresAt <= now ? <p className="mt-2">Preview expired. Preview again.</p> :
        <div className="mt-2 flex gap-2">
          <button type="button" className="iux-btn" data-variant="primary" disabled={working || !preview.candidateCount} onClick={() => void runUnavailable()}>Confirm</button>
          <button type="button" className="iux-btn" onClick={() => setPreview(null)}>Cancel</button>
        </div>}
    </div>}
    {(planJob?.state === "running" || runJob?.state === "running") && <p className="mt-3" role="status">
      {planJob?.state === "running" ? "Planning the move…" : <>Moving emulators… {step?.stepsTotal ? <span dir="ltr" className="tabular-nums">({step.stepsDone ?? 0}/{step.stepsTotal} · {step.step ?? ""})</span> : null}</>}
    </p>}
    {emuJob?.state === "running" && <p className="mt-3" role="status">Android emulator cleanup in progress…</p>}
    {result && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm" role="status">
      {result.status === "completed" && !result.cancelled
        ? <p>Moved <span dir="ltr" className="tabular-nums">{bytes(result.bytesRelocated)}</span> off the system disk.</p>
        : <p>{result.status === "failed" ? "The move failed. The original folder is still in place." : "The move stopped."}</p>}
      {result.storePath && <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no">{result.storePath}</p>}
      {result.status === "completed" && !result.cancelled && <p className="mt-1 text-xs">
        {result.linkKind === "junction"
          ? "Studio still opens these AVDs through a junction at the original path."
          : "Studio still opens these AVDs through a symlink at the original path."}
      </p>}
    </div>}
    {emuJob?.state === "done" && emuJob.result && <p className="mt-3" role="status">Done. <span dir="ltr">{bytes(emuJob.result.bytesFreed)}</span> freed.</p>}
    {emuJob?.state === "failed" && <Status value={{ ok: false, text: emuJob.error || emuJob.result?.error || "Android emulator cleanup failed." }} />}
    {pending && confirmOpen && <RelocationConfirmDialog pending={pending} busy={runJob?.state === "running"} error={error}
      onRun={() => void runMove()} onClose={() => { setConfirmOpen(false); setPending(null); }} />}
  </Section>;
}
