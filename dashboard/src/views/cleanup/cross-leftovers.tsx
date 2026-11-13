import { useEffect, useState } from "react";
import { Empty, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type CleanupCrossLeftovers } from "../../lib/api";

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const bytes = (value: number) => value < 1024 ? `${value} B` : `${(value / 1024 ** 2).toFixed(1)} MiB`;

export function CrossPlatformLeftovers() {
  const [job, setJob] = useState<CleanupAuxJob<CleanupCrossLeftovers> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (job?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupCrossLeftovers>(job.id)
        .then((value) => { if (alive) setJob(value); })
        .catch((failure) => { if (alive) setJob((old) => old ? { ...old, state: "failed", error: errorText(failure) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.state]);

  async function scan() {
    setSubmitting(true); setError(""); setJob(null);
    try { setJob(await api.cleanupCrossLeftovers()); }
    catch (failure) { setError(errorText(failure)); }
    finally { setSubmitting(false); }
  }

  async function cancel() {
    if (!job) return;
    setError("");
    try { await api.cleanupCancel(job.id); }
    catch (failure) { setError(errorText(failure)); }
  }

  return <Section title="Leftovers" description="Report only. No files are deleted here.">
    <div className="flex gap-2">
      <button type="button" className="iux-btn" disabled={submitting || job?.state === "running"} onClick={() => void scan()}>Scan</button>
      {job?.state === "running" && <button type="button" className="iux-btn" onClick={() => void cancel()}>Cancel</button>}
    </div>
    {job?.state === "running" && <p role="status">Scanning app leftovers…</p>}
    {job?.state === "failed" && <Status value={{ ok: false, text: job.error || "Scan failed." }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    {job?.result && <>
      {!job.result.available && <p>{job.result.reason}</p>}
      {job.result.cancelled && <p>Scan cancelled. Results are partial.</p>}
      {!!job.result.inventorySources?.length && <p>Source: <span translate="no">{job.result.inventorySources.join(", ")}</span></p>}
      {job.result.inventoryErrors?.map((message, index) => <Status key={index} value={{ ok: false, text: message }} />)}
      {job.result.items.length === 0 ? <Empty>No leftovers were reported.</Empty> : job.result.items.map((item) =>
        <div key={item.path} className="border-b border-(--iux-border) py-2 text-sm">
          <strong>{item.name}</strong> · <span translate="no">{item.status}</span> · {bytes(item.sizeBytes)} · Confidence: {Math.round(item.confidence * 100)}%
          <p className="break-all" translate="no">{item.path}</p>
          <p translate="no">{item.rule}</p>
        </div>)}
      {!!job.result.unreadable?.length && <p>unreadable paths: <span translate="no">{job.result.unreadable.join(", ")}</span></p>}
    </>}
  </Section>;
}
