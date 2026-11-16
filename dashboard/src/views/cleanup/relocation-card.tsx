/** CLN-27 dashboard layer: move a catalog folder to another volume behind a verified symlink, and back. */
import { useEffect, useRef, useState } from "react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { api, usePoll, type CleanupAuxJob, type CleanupRelocationEntry, type CleanupRelocationPlan, type CleanupRelocationRun, type CleanupRelocationStatus } from "../../lib/api";
import { keepModalFocus } from "../modal-focus";
import { bytes } from "./format";

const PUBLIC = import.meta.env.PUBLIC_SITE_MODE === "pages";
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const PREVIEW_TTL_SECONDS = 600;
type RelocationAction = "move" | "restore" | "relink" | "resume";

/** Row chip: the API reports relocatable (a real folder) and interrupted; link detail lives on the plan. */
function entryBadge(entry: CleanupRelocationEntry) {
  return entry.interrupted
    ? <Badge tone="warning">Interrupted</Badge>
    : entry.relocatable ? <Badge>Local folder</Badge> : <Badge tone="success">Linked</Badge>;
}

function actionFor(entry: CleanupRelocationEntry): RelocationAction | null {
  if (entry.interrupted) return "resume";
  return entry.relocatable ? "move" : null;
}

/** One relocation plan awaiting its confirm dialog, with the client-side preview clock. */
interface PendingPlan { plan: CleanupRelocationPlan; plannedAt: number }

/** The confirm dialog: names the entry, the destination and the symlink fact before anything moves. */
function RelocationConfirmDialog({
  pending, busy, error, onRun, onClose
}: {
  pending: PendingPlan; busy: boolean; error: string; onRun: () => void; onClose: () => void;
}) {
  const box = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    box.current?.showModal();
    box.current?.focus();
    return () => {
      if (box.current?.open) box.current.close();
      document.body.style.overflow = previousOverflow;
      prev?.focus();
    };
  }, []);
  const { plan } = pending;
  const expired = pending.plannedAt + PREVIEW_TTL_SECONDS <= Date.now() / 1000;
  const blocked = busy || expired;
  return <dialog ref={box} tabIndex={-1} aria-labelledby="relocation-confirm-title"
    className="iux-dialog m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl p-5"
    onClose={onClose} onKeyDown={keepModalFocus}
    onMouseDown={(event) => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
        event.preventDefault();
        onClose();
      }
    }}>
    <h2 id="relocation-confirm-title" className="text-sm font-semibold">Confirm relocation</h2>
    <p className="mt-2 text-sm"><span className="font-semibold">{plan.entryName}</span> · <span className="tabular-nums">{plan.files}</span> <span>files</span> · <span dir="ltr" className="tabular-nums">{bytes(plan.sizeBytes)}</span></p>
    <p className="mt-1 text-sm font-medium">{plan.action === "move" ? "Move" : plan.action === "restore" ? "Restore" : plan.action === "relink" ? "Relink" : "Resume interrupted move"}</p>
    <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no">{plan.homePath}</p>
    <p className="break-all text-xs text-(--iux-muted-foreground)" translate="no">→ {plan.storePath}</p>
    <p className="mt-1 text-xs text-(--iux-muted-foreground)">Destination <code translate="no">{plan.destination}</code> · <span dir="ltr" className="tabular-nums">{bytes(plan.freeBytes)}</span> free</p>
    <p className="mt-2 text-sm">This replaces the folder with a link to the copy on the destination volume.</p>
    {expired ? <p className="mt-3 text-sm">Preview expired. Preview again.</p> :
      <p className="mt-3 text-xs text-(--iux-muted-foreground)">The preview stays valid for 10 minutes.</p>}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="mt-4 flex gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={blocked} onClick={onRun}>Run relocation</button>
      <button type="button" className="iux-btn" onClick={onClose}>Back</button>
    </div>
  </dialog>;
}

export function RelocationCard({ now }: { now: number }) {
  const { data: status, error: statusError, reload: reloadStatus } = usePoll<CleanupRelocationStatus>(
    () => PUBLIC ? Promise.reject(new Error("local")) : api.cleanupRelocation(), 0
  );
  const [destination, setDestination] = useState("");
  const [planJob, setPlanJob] = useState<CleanupAuxJob<CleanupRelocationPlan> | null>(null);
  const [runJob, setRunJob] = useState<CleanupAuxJob<CleanupRelocationRun> | null>(null);
  const [pending, setPending] = useState<PendingPlan | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<CleanupRelocationRun | null>(null);
  const [actionError, setActionError] = useState("");
  const [planningFor, setPlanningFor] = useState<string | null>(null);

  // Default the destination to the first listed volume; the user still confirms it on every plan.
  useEffect(() => {
    if (!destination && status?.destinations.length) setDestination(status.destinations[0].mountPoint);
  }, [status, destination]);

  useEffect(() => {
    if (planJob?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupRelocationPlan>(planJob.id)
        .then((job) => {
          if (!alive) return;
          setPlanJob(job);
          if (job.state === "done" && job.result) {
            setPending({ plan: job.result, plannedAt: Math.floor(Date.now() / 1000) });
            setConfirmOpen(true);
            setPlanningFor(null);
          } else if (job.state === "failed" || job.state === "cancelled") {
            setActionError(job.error || "Planning the relocation failed.");
            setPlanningFor(null);
          }
        })
        .catch((error) => { if (alive) { setActionError(errorText(error)); setPlanningFor(null); } });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [planJob?.id, planJob?.state]);

  useEffect(() => {
    if (runJob?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupRelocationRun>(runJob.id)
        .then((job) => {
          if (!alive) return;
          setRunJob(job);
          if (job.state !== "running" && job.state !== "failed") {
            setResult(job.result);
            void reloadStatus();
          }
        })
        .catch(() => { /* the next tick retries; a vanished job keeps its last state */ });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [runJob?.id, runJob?.state, reloadStatus]);

  async function plan(entryId: string, action: RelocationAction) {
    if (!destination) { setActionError("Destination: choose a volume first."); return; }
    setActionError(""); setResult(null); setPending(null); setConfirmOpen(false);
    setPlanningFor(entryId);
    try { setPlanJob(await api.cleanupRelocationPlan(action, entryId, destination)); }
    catch (error) { setActionError(errorText(error)); setPlanningFor(null); }
  }

  async function run() {
    if (!pending) return;
    setActionError("");
    try {
      setRunJob(await api.cleanupRelocationRun(pending.plan.previewId));
      setConfirmOpen(false);
      setPending(null);
      setPlanJob(null);
    } catch (error) {
      setActionError(errorText(error));
      setConfirmOpen(false);
      setPending(null);
    }
  }

  async function cancelRun() {
    if (!runJob || runJob.state !== "running") return;
    try { await api.cleanupCancel(runJob.id); } catch { /* the run refuses cancels between steps on its own */ }
  }

  if (PUBLIC) {
    return <Section title="Relocate caches" description="Move a cache to another volume and link it back into place.">
      <p className="text-sm">The Cleanup Lab runs in the local app.</p>
    </Section>;
  }

  const busy = planningFor !== null || planJob?.state === "running" || runJob?.state === "running";
  const anyInterrupted = !!status?.entries.some((entry) => entry.interrupted);
  const step = runJob?.progress as { step?: string; stepsDone?: number; stepsTotal?: number } | null | undefined;

  return <Section title="Relocate caches" description="Move a cache to another volume and link it back into place.">
    {statusError && <Status value={{ ok: false, text: statusError === "local" ? "The Cleanup Lab runs in the local app." : statusError }} />}
    {statusError && <button type="button" className="iux-btn" onClick={() => void reloadStatus()}>Retry</button>}
    {status && status.entries.length === 0 && <Empty>No relocatable folders on this system.</Empty>}
    {anyInterrupted && <p className="mb-3 rounded-md border border-(--iux-warning) px-3 py-2 text-sm">A previous move was interrupted; resume it before starting a new one.</p>}
    {status && status.entries.length > 0 && <>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="relocation-destination" className="text-sm font-medium">Destination</label>
        <select id="relocation-destination" className="iux-input max-w-xs" value={destination}
          onChange={(event) => setDestination(event.target.value)} disabled={busy}>
          {!destination && <option value="">Destination</option>}
          {status.destinations.map((item) =>
            <option key={item.mountPoint} value={item.mountPoint}>
              {item.mountPoint} · {bytes(item.freeBytes)} free
            </option>)}
        </select>
        {!status.destinations.length && <span className="text-sm text-(--iux-muted-foreground)">No other volume with free space was found.</span>}
      </div>
      <div className="mt-3 divide-y divide-(--iux-border)">
        {status.entries.map((entry) => {
          const action = actionFor(entry);
          return <div key={entry.entryId} className="py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-medium">{entry.name}</span>
              {entryBadge(entry)}
              {action === "move" && <button type="button" className="iux-btn" disabled={busy || !destination} onClick={() => void plan(entry.entryId, "move")}>Move</button>}
              {action === "resume" && <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !destination} onClick={() => void plan(entry.entryId, "resume")}>Resume interrupted move</button>}
              {!entry.relocatable && !entry.interrupted && <>
                <button type="button" className="iux-btn" disabled={busy || !destination} onClick={() => void plan(entry.entryId, "restore")}>Restore</button>
                <button type="button" className="iux-btn" disabled={busy || !destination} onClick={() => void plan(entry.entryId, "relink")}>Relink</button>
              </>}
            </div>
            <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no">{entry.path}</p>
          </div>;
        })}
      </div>
    </>}
    {pending && confirmOpen && <RelocationConfirmDialog pending={pending} busy={runJob?.state === "running"} error={actionError}
      onRun={() => void run()} onClose={() => { setConfirmOpen(false); setPending(null); }} />}
    {!pending && planJob?.result && !confirmOpen && <div className="mt-3 border-t border-(--iux-border) pt-3 text-sm">
      <p className="font-semibold">Planned steps</p>
      <ol className="mt-1 list-decimal ps-5 text-xs text-(--iux-muted-foreground)">
        {planJob.result.steps.map((step, index) => <li key={index} className="mt-0.5"><code translate="no">{step.op}</code> <span translate="no">{step.src}</span> <span aria-hidden="true">→</span> <span translate="no">{step.dst}</span></li>)}
      </ol>
      <p className="mt-2">This replaces the folder with a link to the copy on the destination volume.</p>
    </div>}
    {runJob?.state === "running" && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm" role="status">
      <p>Relocation in progress… {step?.stepsTotal ? <span dir="ltr" className="tabular-nums">({step.stepsDone ?? 0}/{step.stepsTotal} · {step.step ?? ""})</span> : null}</p>
      <button type="button" className="iux-btn mt-2" onClick={() => void cancelRun()}>Cancel</button>
      <p className="mt-1 text-xs text-(--iux-muted-foreground)">Cancel stops between steps and reports what remains.</p>
    </div>}
    {result && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
      {result.status === "completed" && !result.cancelled && <>
        <p role="status">Relocated <span dir="ltr" className="tabular-nums">{bytes(result.bytesRelocated)}</span>.</p>
        <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no">{result.storePath}</p>
        <p className="mt-1 text-xs text-(--iux-muted-foreground)">This replaces the folder with a link to the copy on the destination volume.</p>
      </>}
      {result.cancelled && <p role="status">Cancelled — the original or a verified copy is still in place.</p>}
      {result.status !== "completed" && !result.cancelled && <>
        <Status value={{ ok: false, text: result.error || "The relocation failed." }} />
        <p className="mt-1 text-xs text-(--iux-muted-foreground)">The original or a verified copy is still in place.</p>
      </>}
    </div>}
    {runJob?.state === "failed" && !result && <Status value={{ ok: false, text: runJob.error || "The relocation failed." }} />}
    {actionError && <div className="mt-3"><Status value={{ ok: false, text: actionError }} /></div>}
  </Section>;
}
