/**
 * CLN-29: the simulator/emulator runtimes section.
 *
 * Report-only inventory (Xcode runtimes, Android AVDs and system images) with
 * sizes and in-use state; deletion runs the tool's own command after a typed
 * preview — the page sends kind and id, the engine builds fixed argv and
 * re-checks the candidate, and the run is audited like a prune.
 */
import { useEffect, useState } from "react";
import { TrashIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type RuntimeDeletePreview, type RuntimeDeleteResult, type RuntimeItem, type RuntimesPayload } from "../../lib/api";
import { bytes } from "./format";

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

function RuntimeRow({ item, busy, onDelete }: {
  item: RuntimeItem; busy: boolean; onDelete: (kind: string, id: string) => void;
}) {
  return <div className="border-b border-(--iux-border) py-2 text-sm">
    <div className="flex flex-wrap items-center gap-2">
      <Badge>{item.kind}</Badge>
      <span className="min-w-0 flex-1 truncate font-medium" dir="ltr">{item.name || item.id}</span>
      {item.inUse && <Badge tone="warning">in use</Badge>}
      <span className="tabular-nums text-xs text-(--iux-muted-foreground)" dir="ltr">
        {item.sizeBytes == null ? "size unknown" : bytes(item.sizeBytes)}
      </span>
      {item.deletable && !item.inUse && <button type="button" className="iux-btn" data-variant="ghost"
        title="Delete this runtime" disabled={busy} onClick={() => onDelete(item.kind, item.id)}>
        <TrashIcon size={14} />
      </button>}
    </div>
    {item.path && <p className="break-all text-xs text-(--iux-muted-foreground)" translate="no">{item.path}</p>}
    {item.note && <p className="text-xs text-(--iux-muted-foreground)">{item.note}</p>}
  </div>;
}

export function RuntimesCard({ now }: { now: number }) {
  const [payload, setPayload] = useState<RuntimesPayload | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<RuntimeDeletePreview | null>(null);
  const [job, setJob] = useState<CleanupAuxJob<RuntimeDeleteResult> | null>(null);
  const [pending, setPending] = useState(false);

  const reload = () => {
    void api.cleanupRuntimes().then(setPayload).catch((e) => setError(errorText(e)));
  };
  useEffect(() => { reload(); }, []);

  useEffect(() => {
    if (job?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<RuntimeDeleteResult>(job.id)
        .then((value) => { if (alive) setJob(value); })
        .catch((e) => { if (alive) setJob((old) => old ? { ...old, state: "failed", error: errorText(e) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.state]);

  async function previewDelete(kind: string, id: string) {
    setPending(true); setError(""); setPreview(null); setJob(null);
    try { setPreview(await api.cleanupRuntimeDeletePreview(kind, id)); }
    catch (e) { setError(errorText(e)); }
    finally { setPending(false); }
  }

  async function runDelete() {
    if (!preview || preview.expiresAt <= now) return;
    setPending(true); setError("");
    try { setJob(await api.cleanupRuntimeDeleteRun(preview.previewId)); setPreview(null); }
    catch (e) { setError(errorText(e)); }
    finally { setPending(false); }
  }

  const items = [...(payload?.xcode.items ?? []), ...(payload?.android.items ?? [])];
  const busy = pending || job?.state === "running";
  const unavailable = [payload?.xcode, payload?.android].filter((probe) => probe && !probe.available);

  return <Section title="Simulator runtimes"
    description="Xcode simulator runtimes and Android images, with sizes. Deleting runs the tool's own command after a preview.">
    {error && <Status value={{ ok: false, text: error }} />}
    {job?.state === "failed" && job.error && <Status value={{ ok: false, text: job.error }} />}
    {unavailable.map((probe) => <p key={probe?.reason} className="text-sm text-(--iux-muted-foreground)">{probe?.reason}</p>)}
    {!payload && !error && <p role="status">Checking runtimes…</p>}
    {payload && items.length === 0 && <Empty>No simulator runtimes or Android images found on this computer.</Empty>}
    {items.length > 0 && <div>
      {items.map((item) => <RuntimeRow key={`${item.kind}-${item.id}`} item={item} busy={busy} onDelete={(kind, id) => void previewDelete(kind, id)} />)}
    </div>}
    {preview && <div className="mt-3 rounded-md border border-(--iux-border) p-3 text-sm">
      <p>The delete runs this command once:</p>
      <p className="mt-1 break-all font-mono text-xs" dir="ltr" translate="no">{preview.argv.join(" ")}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={busy || preview.expiresAt <= now}
          onClick={() => void runDelete()}>Delete</button>
        <button type="button" className="iux-btn" disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
      </div>
    </div>}
    {job?.state === "running" && <p role="status">Runtime delete in progress…</p>}
    {job?.state === "done" && job.result && <p role="status">Delete completed. <span translate="no">{job.result.stdout}</span></p>}
  </Section>;
}
