import { useEffect, useState } from "react";
import { Empty, Section, Status } from "../../components/ui";
import { api, type CleanupAuxJob, type CleanupContainerCapabilities, type CleanupContainerPreview, type CleanupContainerResult, type CleanupVMInventory } from "../../lib/api";

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const bytes = (value: number) => value < 1024 ? `${value} B` : `${(value / 1024 ** 2).toFixed(1)} MiB`;

export function CleanupExtraTools({ now }: { now: number }) {
  const [capabilities, setCapabilities] = useState<CleanupContainerCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [preview, setPreview] = useState<CleanupContainerPreview | null>(null);
  const [containerJob, setContainerJob] = useState<CleanupAuxJob<CleanupContainerResult> | null>(null);
  const [vmJob, setVmJob] = useState<CleanupAuxJob<CleanupVMInventory> | null>(null);
  const [containerError, setContainerError] = useState("");
  const [vmError, setVMError] = useState("");
  const [containerPending, setContainerPending] = useState(false);
  const [vmPending, setVMPending] = useState(false);

  useEffect(() => {
    let alive = true;
    void api.cleanupContainers().then((value) => { if (alive) setCapabilities(value); })
      .catch((error) => { if (alive) setCapabilityError(errorText(error)); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (containerJob?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupContainerResult>(containerJob.id)
        .then((job) => { if (alive) setContainerJob(job); })
        .catch((error) => { if (alive) setContainerJob((old) => old ? { ...old, state: "failed", error: errorText(error) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [containerJob?.id, containerJob?.state]);

  useEffect(() => {
    if (vmJob?.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupAuxJob<CleanupVMInventory>(vmJob.id)
        .then((job) => { if (alive) setVmJob(job); })
        .catch((error) => { if (alive) setVmJob((old) => old ? { ...old, state: "failed", error: errorText(error) } : old); });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [vmJob?.id, vmJob?.state]);

  async function loadPreview(actionId: string) {
    setContainerPending(true); setContainerError(""); setPreview(null); setContainerJob(null);
    try { setPreview(await api.cleanupContainerPreview(actionId)); }
    catch (error) { setContainerError(errorText(error)); }
    finally { setContainerPending(false); }
  }

  async function prune() {
    if (!preview || preview.expiresAt <= now || preview.candidateCount === 0) return;
    setContainerPending(true); setContainerError("");
    try { setContainerJob(await api.cleanupContainerPrune(preview.previewId)); setPreview(null); }
    catch (error) { setContainerError(errorText(error)); }
    finally { setContainerPending(false); }
  }

  async function scanVMs() {
    setVMPending(true); setVMError(""); setVmJob(null);
    try { setVmJob(await api.cleanupVMScan()); }
    catch (error) { setVMError(errorText(error)); }
    finally { setVMPending(false); }
  }

  const containerBusy = containerPending || containerJob?.state === "running";
  return <>
    <Section title="Containers" description="Preview candidates before pruning. Volumes may contain persistent data.">
      {capabilityError && <Status value={{ ok: false, text: capabilityError }} />}
      {capabilityError && <button type="button" className="iux-btn" onClick={() => {
        setCapabilityError("");
        void api.cleanupContainers().then(setCapabilities).catch((error) => setCapabilityError(errorText(error)));
      }}>Retry</button>}
      {!capabilities && !capabilityError && <p role="status">Checking container engine…</p>}
      {capabilities && !capabilities.available && <p>{capabilities.reason}</p>}
      {capabilities?.available && <>
        <p>Container engine: <code translate="no">{capabilities.engine}</code></p>
        <div className="flex flex-wrap gap-2">{capabilities.actions.map((action) =>
          <button key={action.id} type="button" className="iux-btn" disabled={containerBusy}
            onClick={() => void loadPreview(action.id)}>Preview <span translate="no">{action.id}</span></button>)}</div>
      </>}
      {preview && <div className="mt-3 border-t border-(--iux-border) pt-3">
        <p><strong translate="no">{preview.actionId}</strong> · Risk: {preview.risk} · Candidates: {preview.candidateCount}</p>
        <p>Command: <code translate="no">{preview.command.join(" ")}</code></p>
        <details><summary>Candidates</summary><pre className="max-h-48 overflow-auto text-xs" translate="no">{JSON.stringify(preview.candidates, null, 2)}</pre></details>
        {preview.expiresAt <= now ? <p>Preview expired. Preview again.</p> :
          <button type="button" className="iux-btn mt-2" data-variant="primary" disabled={containerBusy || preview.candidateCount === 0}
            onClick={() => void prune()}>Confirm prune</button>}
        {preview.candidateCount === 0 && <p>No candidates to prune.</p>}
      </div>}
      {containerJob?.state === "running" && <p role="status">Container prune in progress…</p>}
      {containerJob?.state === "done" && containerJob.result && <p role="status">Prune completed. <span translate="no">{containerJob.result.output}</span></p>}
      {containerJob?.state === "failed" && <Status value={{ ok: false, text: containerJob.error || containerJob.result?.error || "Container prune failed." }} />}
      {containerError && <Status value={{ ok: false, text: containerError }} />}
    </Section>
    <Section title="Virtual machines" description="Report only. No virtual machines are deleted here.">
      <button type="button" className="iux-btn" disabled={vmPending || vmJob?.state === "running"} onClick={() => void scanVMs()}>Scan virtual machines</button>
      {vmJob?.state === "running" && <p role="status">VM inventory in progress…</p>}
      {vmJob?.state === "failed" && <Status value={{ ok: false, text: vmJob.error || "VM inventory failed." }} />}
      {vmError && <Status value={{ ok: false, text: vmError }} />}
      {vmJob?.result && <>
        {vmJob.result.cancelled && <p>Scan cancelled. Results are partial.</p>}
        {vmJob.result.items.length === 0 ? <Empty>No virtual machines found.</Empty> : vmJob.result.items.map((item) =>
          <div key={item.path} className="border-b border-(--iux-border) py-2 text-sm"><strong>{item.name}</strong> · {bytes(item.sizeBytes)} · Report only<p className="break-all" translate="no">{item.path}</p></div>)}
        {vmJob.result.unavailable.map((item, index) => <p key={`${item.id}-${index}`} className="text-sm"><span translate="no">{item.root || item.id}</span>: {item.reason}</p>)}
      </>}
    </Section>
  </>;
}
