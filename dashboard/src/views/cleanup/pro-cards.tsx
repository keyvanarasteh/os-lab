/**
 * Compact "pro" cards for the cleanup capabilities that have no dashboard card
 * yet: privileged actions, projects deep scan, simulators, package review,
 * cross-platform leftovers, containers & VMs and custom entries.
 *
 * Every card loads real data from its typed engine endpoint (no mocked data),
 * renders loading → data → empty → error states, and never invents byte counts.
 * Destructive actions follow preview → confirm → run; report-only capabilities
 * never offer a delete control.
 *
 * Cards are deliberately compact so several fit in a dashboard grid without
 * crowding the main Ready / Bookmarks cards.
 */
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  ArrowsClockwiseIcon, BookmarkSimpleIcon, BugIcon, CubeIcon, HardDrivesIcon,
  MagnifyingGlassIcon, PackageIcon, SparkleIcon, TrashIcon, WrenchIcon,
} from "@phosphor-icons/react";
import { Badge, Modal, Status } from "../../components/ui";
import {
  api, formatBytes,
  type CleanupAuxJob, type CleanupEntry, type CleanupDeepRoot,
  type CleanupDeepScanItem, type CleanupPackageCandidate,
  type CleanupPrivilegedPreview, type CleanupPrivilegedRun, type CleanupPrivilegedStatus,
  type CleanupSimulators, type CleanupVMInventory, type CleanupContainerPreview,
  type CleanupCrossLeftovers,
} from "../../lib/api";

export type ProCardTone = "accent" | "success" | "danger" | "warning" | "muted";

const DOT: Record<ProCardTone, string> = {
  accent: "bg-[#f36c21]", success: "bg-(--iux-success)", danger: "bg-(--iux-danger)",
  warning: "bg-(--iux-warning)", muted: "bg-(--iux-muted-foreground)",
};

/** Compact card shell: eyebrow, headline, stats, bar, footer, optional body. */
export function ProCard({
  id, title, description, dot = "accent", actions, stats, bar, footer, children
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  dot?: ProCardTone;
  actions?: ReactNode;
  stats?: { key: string; value: ReactNode; label: string; tone?: ProCardTone }[];
  bar?: { percent: number; caption: ReactNode; label: string; tone?: ProCardTone };
  footer?: { key: string; icon: ReactNode; text: ReactNode }[];
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const hasDetails = Boolean(children && stats?.length);
  const visibleFooter = footer?.slice(0, 2);
  return <section id={id} className="iux-card flex min-h-44 flex-col overflow-hidden rounded-2xl bg-linear-to-b from-(--iux-card) to-(--iux-background) pb-4">
    <div className="flex items-center justify-between gap-3 px-4 pt-3">
      <span translate="no" className="text-[10px] font-semibold tracking-wide text-(--iux-muted-foreground)">os-lab</span>
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${DOT[dot]}`} />
    </div>
    <div className="mt-1 flex items-start justify-between gap-2 px-4">
      <div className="min-w-0">
        <h2 className="text-base leading-tight font-bold">{title}</h2>
        {description && <p className="mt-0.5 text-[10px] text-(--iux-muted-foreground)">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
    {stats && stats.length > 0 && <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 px-4">
      {stats.map((stat) => <div key={stat.key} className="min-w-0">
        <p dir="ltr" className={`text-sm font-bold tabular-nums ${stat.tone === "success" ? "text-(--iux-success)" : stat.tone === "danger" ? "text-(--iux-danger)" : stat.tone === "warning" ? "text-(--iux-warning)" : "text-[#f36c21]"}`}>{stat.value}</p>
        <p className="mt-0.5 truncate text-[10px] text-(--iux-muted-foreground)">{stat.label}</p>
      </div>)}
    </div>}
    {bar && <div className="mt-3 px-4">
      <div className="h-1 overflow-hidden rounded-full bg-(--iux-muted)" role="progressbar" aria-label={bar.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar.percent)}>
        <span className={`block h-full rounded-full ${bar.tone === "success" ? "bg-(--iux-success)" : bar.tone === "danger" ? "bg-(--iux-danger)" : bar.tone === "warning" ? "bg-(--iux-warning)" : "bg-[#f36c21]"}`}
          style={{ width: `${Math.min(100, Math.max(0, bar.percent))}%` }} />
      </div>
      <p className="mt-1 truncate text-[10px] text-(--iux-muted-foreground)">{bar.caption}</p>
    </div>}
    {visibleFooter && visibleFooter.length > 0 && <div className="mt-3 border-t border-(--iux-border) px-4 pt-2">
      <ul className="space-y-1 text-xs text-(--iux-muted-foreground)">
        {visibleFooter.map((line) => <li key={line.key} className="flex min-w-0 items-center gap-1.5 truncate">
          <span className="mt-0.5 shrink-0 text-[10px] text-(--iux-muted-foreground)" aria-hidden="true">{line.icon}</span>
          <span className="min-w-0 flex-1 truncate">{line.text}</span>
        </li>)}
      </ul>
    </div>}
    {hasDetails && <div className="mt-auto px-4 pt-3">
      <button type="button" className="iux-btn w-full justify-center" data-variant="outline" onClick={() => setOpen(true)}>Details</button>
    </div>}
    {children && !hasDetails && <div className="mt-auto px-4 pt-3">{children}</div>}
    {open && hasDetails && <Modal title={title} onClose={() => setOpen(false)}>
      <div className="max-h-[65vh] overflow-y-auto px-1 py-2">{children}</div>
    </Modal>}
  </section>;
}

/** Compact icon action in a pro card header. */
function ProAction({
  label, icon, onClick, disabled, busy = false
}: { label: string; icon: ReactNode; onClick: () => void; disabled: boolean; busy?: boolean }) {
  return <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title={label} aria-label={label}
    disabled={disabled} onClick={onClick}>
    <span className={busy ? "inline-flex animate-spin" : "inline-flex"}>{icon}</span>
  </button>;
}

/** Shows an error Status next to a failing action. */
function ErrorLine({ text, className }: { text: string; className?: string }) {
  return <div className={className ?? "px-4 pt-1"}><Status value={{ ok: false, text }} /></div>;
}

/** Shared job runner: starts a job, polls until done, then stops. */
function useJob<T>(start: () => Promise<CleanupAuxJob<T>>, poll: (id: string) => Promise<CleanupAuxJob<T>>) {
  const [job, setJob] = useState<CleanupAuxJob<T> | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const timer = useRef<number | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; if (timer.current != null) window.clearInterval(timer.current); };
  }, []);

  async function run() {
    if (submitting || job?.state === "running") return;
    setError("");
    setSubmitting(true);
    try {
      const started = await start();
      if (!alive.current) return;
      setJob(started);
      if (started.state === "running") {
        timer.current = window.setInterval(() => {
          void poll(started.id).then((updated) => {
            if (!alive.current) return;
            setJob(updated);
            if (updated.state !== "running") window.clearInterval(timer.current as number);
          }).catch((pollError) => {
            if (alive.current) {
              setError(String(pollError));
              setJob((old) => old ? { ...old, state: "failed", error: String(pollError) } : null);
              window.clearInterval(timer.current as number);
            }
          });
        }, 650);
      }
    } catch (startError) {
      if (alive.current) setError(String(startError));
    } finally {
      if (alive.current) setSubmitting(false);
    }
  }

  async function cancel() {
    if (!job || cancelling) return;
    setError("");
    setCancelling(true);
    try { await api.cleanupCancel(job.id); }
    catch (cancelError) { setError(String(cancelError)); }
    finally { setCancelling(false); }
  }

  return { job, error, run, cancel, busy: submitting || job?.state === "running", cancelling };
}

export function relativeTime(atSeconds: number | null | undefined, locale: string, nowSeconds: number): string | null {
  if (atSeconds == null || !Number.isFinite(atSeconds)) return null;
  const diff = atSeconds - nowSeconds, abs = Math.abs(diff);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];
  for (const [unit, size] of units) {
    if (abs >= size || unit === "second") return formatter.format(Math.round(diff / size), unit);
  }
  return null;
}

/**
 * Privileged actions (CLN-20): system maintenance offered by this host.
 * Preview shows elevation + command + bytes; run executes through the host's
 * own elevation — never a free-form command from the page.
 */
export function PrivilegedCard({ locale, now }: { locale: string; now: number }) {
  const [status, setStatus] = useState<CleanupPrivilegedStatus | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<CleanupPrivilegedPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const job = useJob<CleanupPrivilegedRun>(
    () => api.cleanupPrivilegedRun(preview?.previewId ?? ""),
    (id) => api.cleanupAuxJob<CleanupPrivilegedRun>(id),
  );

  useEffect(() => {
    let alive = true;
    void api.cleanupPrivileged().then((value) => { if (alive) setStatus(value); }).catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);

  async function loadPreview(actionId: string) {
    setPreview(null); setPreviewError("");
    try { setPreview(await api.cleanupPrivilegedPreview(actionId)); }
    catch (e) { setPreviewError(String(e)); }
  }

  const loading = status == null && error === "";
  const applicable = status?.applicable === true;
  const actions = status?.actions ?? [];

  if (loading) return <ProCard id="pro-privileged" title="Privileged actions" dot="muted" stats={[]}><p className="px-4 py-2 text-[10px] text-(--iux-muted-foreground)">Checking privileged actions…</p></ProCard>;
  if (error) return <ProCard id="pro-privileged" title="Privileged actions" dot="danger" stats={[]}><ErrorLine text={error} className="px-4 py-2" /></ProCard>;
  if (!applicable) {
    return <ProCard id="pro-privileged" title="Privileged actions" dot="muted"
      footer={[{ key: "elevation", icon: <WrenchIcon size={13} />, text: <span>No typed elevation mechanism on this host</span> }]}>
      <p className="text-xs text-(--iux-muted-foreground)">Privileged system maintenance is not offered on <span translate="no">{status?.platform}</span>.</p>
    </ProCard>;
  }

  const runLabel = job.busy ? "Running…" : "Run";
  return <ProCard id="pro-privileged" title="Privileged actions" dot="warning"
    actions={<>
      <ProAction label="Refresh" icon={<ArrowsClockwiseIcon size={15} />} onClick={() => { void api.cleanupPrivileged().then(setStatus).catch((e) => setError(String(e))); }} disabled={job.busy} />
    </>}
    stats={[
      { key: "actions", value: actions.length, label: "Actions", tone: actions.length ? "accent" : "muted" },
      { key: "elevation", value: status.elevation ? <span className="text-[10px]">●</span> : "—", label: "Elevation", tone: status.elevation ? "success" : "danger" },
    ]}
    footer={actions.map((action) => ({
      key: action.id,
      icon: <Badge tone={action.risk === "high" ? "danger" : action.risk === "medium" ? "warning" : "success"}>{action.risk}</Badge>,
      text: <><span className="font-medium">{action.name}</span> <span className="text-(--iux-muted-foreground)">{action.impact}</span></>,
    }))}>
    {error && <ErrorLine text={error} className="px-4 pt-1" />}
    <div className="divide-y divide-(--iux-border) px-4 py-2">
      {actions.map((action) => <div key={action.id} className="flex items-center justify-between gap-2 py-1.5 text-sm">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Badge tone={action.risk === "high" ? "danger" : action.risk === "medium" ? "warning" : "success"}>{action.risk}</Badge>
            <span className="font-medium truncate">{action.name}</span>
          </div>
          <p className="text-[10px] text-(--iux-muted-foreground) truncate">{action.impact}</p>
        </div>
        <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" disabled={job.busy || (!preview && job.job != null)}
          title={`Preview ${action.name}`} onClick={() => void loadPreview(action.id)}>
          {preview?.actionId === action.id ? <TrashIcon size={13} /> : <MagnifyingGlassIcon size={13} />}
        </button>
      </div>)}
    </div>
    {preview && <div className="mt-2 border border-(--iux-border) rounded-md px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-medium">Preview: {preview.actionId}</span>
        <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title="Close preview" onClick={() => setPreview(null)}>✕</button>
      </div>
      <p className="text-[10px] text-(--iux-muted-foreground) truncate">{preview.command.join(" ")}</p>
      <div className="mt-1 flex items-center gap-2 text-[10px]">
        <Badge tone={preview.risk === "high" ? "danger" : preview.risk === "medium" ? "warning" : "success"}>{preview.risk}</Badge>
        <span className="text-(--iux-muted-foreground)">{preview.candidateCount} candidates</span>
        {preview.totalBytes != null && <span className="text-(--iux-muted-foreground)">· {formatBytes(preview.totalBytes)}</span>}
      </div>
      {previewError && <ErrorLine text={previewError} className="mt-1" />}
      <div className="mt-2 flex gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={!preview || job.busy || preview.expiresAt <= now || preview.candidateCount === 0} onClick={() => void job.run()}>{runLabel}</button>
        <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" onClick={() => setPreview(null)}>Close</button>
      </div>
      {job.job && <div className="mt-1 text-[10px]">{job.job.state === "running" ? "Running privileged action…" : job.job.state === "failed" ? `Failed: ${job.job.error}` : `Finished: ${job.job.result?.status}`}</div>}
    </div>}
    {job.error && <ErrorLine text={job.error} className="px-4 pt-1" />}
  </ProCard>;
}

/**
 * Projects deep scan (CLN-24): marker-verified build outputs over registered roots.
 * Pick available roots and an idle-days floor; the sweep reports what can be
 * regenerated — report only, never deletes.
 */
export function DeepScanCard({ locale, now }: { locale: string; now: number }) {
  const [roots, setRoots] = useState<CleanupDeepRoot[] | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [minIdleDays, setMinIdleDays] = useState(0);
  const job = useJob<CleanupDeepScanItem[]>(
    () => api.cleanupDeepScan(selected, minIdleDays > 0 ? minIdleDays : undefined),
    (id) => api.cleanupAuxJob<CleanupDeepScanItem[]>(id),
  );

  useEffect(() => {
    let alive = true;
    void api.cleanupDeepRoots().then((value) => { if (alive) { setRoots(value.roots); setSelected(value.roots.filter((root) => root.available).map((root) => root.id)); } }).catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);

  const loading = roots == null && error === "";
  const available = (roots ?? []).filter((root) => root.available);
  const canScan = selected.length > 0 && !job.busy;

  if (loading) return <ProCard id="pro-deep-scan" title="Projects deep scan" dot="muted" stats={[]}><p className="px-4 py-2 text-[10px] text-(--iux-muted-foreground)">Loading project roots…</p></ProCard>;
  if (error) return <ProCard id="pro-deep-scan" title="Projects deep scan" dot="danger" stats={[]}><ErrorLine text={error} className="px-4 py-2" /></ProCard>;

  const items = job.job?.result ?? [];
  const done = job.job?.state === "done";
  const totals = items.reduce((sum, item) => sum + item.sizeBytes, 0);

  return <ProCard id="pro-deep-scan" title="Projects deep scan" dot={done ? (items.length ? "success" : "muted") : job.busy ? "accent" : "muted"}
    actions={<ProAction label="Refresh" icon={<ArrowsClockwiseIcon size={15} />} onClick={() => { void api.cleanupDeepRoots().then((value) => setRoots(value.roots.filter((root) => root.available))).catch((e) => setError(String(e))); }} disabled={job.busy} />}
    stats={[
      { key: "roots", value: available.length, label: "Roots", tone: available.length ? "accent" : "muted" },
      { key: "found", value: done ? items.length : "—", label: done ? "Projects found" : job.busy ? "Scanning" : "Not scanned", tone: items.length ? "accent" : "muted" },
      { key: "size", value: done ? formatBytes(totals) : "—", label: "Regeneratable", tone: totals ? "success" : "muted" },
    ]}
    footer={available.map((root) => ({
      key: root.id,
      icon: <HardDrivesIcon size={13} />,
      text: <><span className="font-medium truncate">{root.id}</span> <span className="text-(--iux-muted-foreground)">{root.path ?? root.reason}</span></>,
    }))}>
    {error && <ErrorLine text={error} className="px-4 pt-1" />}
    <div className="px-4 py-2 space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span className="font-medium text-(--iux-muted-foreground)">Idle at least</span>
        <input type="number" className="iux-input w-12 text-[10px]" min={0} max={3650} value={minIdleDays} disabled={job.busy}
          onChange={(event) => setMinIdleDays(Math.max(0, Math.min(3650, Number(event.target.value) || 0)))} /> days
        <span className="text-(--iux-muted-foreground)">·</span>
        <span className="text-[10px] text-(--iux-muted-foreground)">{selected.length} root{selected.length === 1 ? "" : "s"} selected</span>
      </div>
      <div className="flex flex-wrap items-center gap-1 mt-1">
        {available.map((root) => <button key={root.id} type="button" className={`iux-btn iux-touch-target text-[10px] ${selected.includes(root.id) ? "data-variant=primary bg-(--iux-primary) text-(--iux-primary-foreground)" : "data-variant=outline"}`} disabled={job.busy}
          onClick={() => setSelected((old) => old.includes(root.id) ? old.filter((id) => id !== root.id) : [...old, root.id])}>{root.id}</button>)}
      </div>
      {job.job?.state === "running" && <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">Sweeping {selected.join(", ")}…</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={!canScan || job.busy} onClick={() => void job.run()}>Scan</button>
        {job.job?.state === "running" && <button type="button" className="iux-btn" onClick={() => void job.cancel()}>Cancel</button>}
      </div>
      {items.length > 0 && <div className="mt-2 divide-y divide-(--iux-border)">
        {items.map((item) => <div key={`${item.rootId}-${item.id}`} className="flex items-center justify-between gap-2 py-1 text-xs">
          <div className="min-w-0 flex-1">
            <span className="font-medium truncate">{item.id}</span>
            <p className="text-[10px] text-(--iux-muted-foreground) truncate">{item.project}</p>
          </div>
          <div className="flex items-center gap-2 text-[10px]">
            <Badge>{item.ecosystem}</Badge>
            <span dir="ltr" className="tabular-nums">{formatBytes(item.sizeBytes)}</span>
          </div>
        </div>)}
      </div>}
      {done && items.length === 0 && <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">No regeneratable projects found.</p>}
      {job.job?.state === "failed" && <ErrorLine text={job.job.error || "Deep scan failed."} className="px-4 pt-1" />}
    </div>
  </ProCard>;
}

/**
 * Simulators (CLN-09): Xcode CoreSimulator device inventory. Report only —
 * devices are never deleted from here; relocation moves them off the OS disk.
 */
export function SimulatorsCard({}: {}) {
  const [info, setInfo] = useState<CleanupSimulators | null>(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    let alive = true;
    void api.cleanupSimulators().then((value) => { if (alive) setInfo(value); }).catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);

  const loading = info == null && error === "";

  if (loading) return <ProCard id="pro-simulators" title="Simulators" dot="muted" stats={[]}><p className="px-4 py-2 text-[10px] text-(--iux-muted-foreground)">Loading simulator inventory…</p></ProCard>;
  if (error) return <ProCard id="pro-simulators" title="Simulators" dot="danger" stats={[]}><div className="px-4 py-2"><Status value={{ ok: false, text: error }} /></div></ProCard>;
  if (!info?.available) {
    return <ProCard id="pro-simulators" title="Simulators" dot="muted" stats={[]}><p className="px-4 py-2 text-[10px] text-(--iux-muted-foreground)">{info?.reason || "Simulators unavailable on this host."}</p></ProCard>;
  }

  const devices = info.devices ?? [];
  const totalBytes = devices.reduce((sum, d) => sum + (d.sizeBytes ?? 0), 0);

  return <ProCard id="pro-simulators" title="Simulators" dot="accent"
    actions={<ProAction label="Refresh" icon={<ArrowsClockwiseIcon size={15} />} onClick={() => { setScanning(true); void api.cleanupSimulators().then(setInfo).catch((e) => setError(String(e))).finally(() => setScanning(false)); }} disabled={scanning} />}
    stats={[
      { key: "devices", value: devices.length, label: "Devices", tone: devices.length ? "accent" : "muted" },
      { key: "size", value: formatBytes(totalBytes), label: "On disk", tone: totalBytes ? "success" : "muted" },
    ]}
    footer={devices.map((device) => ({
      key: device.id ?? device.name ?? "",
      icon: <CubeIcon size={13} />,
      text: <><span className="font-medium truncate">{device.name ?? device.id ?? "device"}</span>
        <span className="text-(--iux-muted-foreground)"> · {device.runtime ?? "—"}</span>
        <span className="text-(--iux-muted-foreground)"> · {formatBytes(device.sizeBytes ?? 0)}</span>
        {device.available ? null : <span className="text-(--iux-danger)"> · unavailable</span>}</>,
    }))}>
    <p className="px-4 py-1 text-[10px] text-(--iux-muted-foreground)">Report only — simulators are never deleted here. Relocation moves a device store off the OS disk.</p>
    {error && <ErrorLine text={error} className="px-4 pt-1" />}
  </ProCard>;
}

/**
 * Package review (CLN-11): Homebrew/pip/gem top-level candidates. Report only
 * — each result carries its exact uninstall argv as a preview, no execution.
 */
export function PackageReviewCard({}: {}) {
  const job = useJob<CleanupPackageCandidate[]>(
    () => api.cleanupPackagesScan(),
    (id) => api.cleanupAuxJob<CleanupPackageCandidate[]>(id),
  );

  const items = job.job?.result ?? [];
  const byTool = new Map<string, CleanupPackageCandidate[]>();
  for (const item of items) { const group = byTool.get(item.tool) ?? []; group.push(item); byTool.set(item.tool, group); }

  const done = job.job?.state === "done";
  return <ProCard id="pro-packages" title="Package review" dot={done ? (items.length ? "success" : "muted") : job.busy ? "accent" : "muted"}
    stats={[
      { key: "tools", value: done ? byTool.size : "—", label: "Tools", tone: byTool.size ? "accent" : "muted" },
      { key: "candidates", value: done ? items.length : "—", label: done ? "Candidates" : job.busy ? "Scanning" : "Not scanned", tone: items.length ? "accent" : "muted" },
    ]}
    footer={Array.from(byTool.entries()).map(([tool, group]) => ({
      key: tool,
      icon: <PackageIcon size={13} />,
      text: <><span className="font-medium">{tool}</span> <span className="text-(--iux-muted-foreground)">{group.length} candidate{group.length === 1 ? "" : "s"}</span></>,
    }))}>
    {job.error && <ErrorLine text={job.error} className="px-4 pt-1" />}
    <div className="px-4 py-2">
      <div className="mt-1 flex gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={job.busy} onClick={() => void job.run()}>Scan packages</button>
        {job.busy && <button type="button" className="iux-btn" onClick={() => void job.cancel()}>Cancel</button>}
      </div>
      {items.length > 0 && <div className="mt-2 divide-y divide-(--iux-border)">
        {items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 py-1 text-xs">
          <div className="min-w-0 flex-1">
            <span className="font-medium truncate">{item.name}</span>
            <p className="text-[10px] text-(--iux-muted-foreground) truncate">{item.version ?? "—"} · {item.command.join(" ")}</p>
          </div>
          <Badge>Report only</Badge>
        </div>)}
      </div>}
      {done && items.length === 0 && <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">No reviewable packages found.</p>}
      {job.job?.state === "failed" && <ErrorLine text={job.job.error || "Package scan failed."} className="px-4 pt-1" />}
    </div>
  </ProCard>;
}

/**
 * Cross-platform leftovers (CLN-09/10): orphaned app data detected by OS
 * package inventories. Report only — confidence, paths, inventory sources.
 */
export function LeftoversCard({ locale, now }: { locale: string; now: number }) {
  const job = useJob<CleanupCrossLeftovers>(
    () => api.cleanupCrossLeftovers(),
    (id) => api.cleanupAuxJob<CleanupCrossLeftovers>(id),
  );

  const items = job.job?.result?.items ?? [];
  const likely = items.filter((item) => item.confidence >= 0.8);
  const possible = items.filter((item) => item.confidence >= 0.4 && item.confidence < 0.8);
  const totalBytes = items.reduce((sum, item) => sum + item.sizeBytes, 0);

  const done = job.job?.state === "done";
  const confidenceTone = (value: number) => value >= 0.8 ? "danger" : value >= 0.4 ? "warning" : undefined;
  const confidenceLabel = (value: number) => value >= 0.8 ? "Likely leftover" : value >= 0.4 ? "Possible leftover" : "Uncertain";

  return <ProCard id="pro-leftovers" title="Cross-platform leftovers" dot={done ? (items.length ? likely.length ? "danger" : "warning" : "muted") : job.busy ? "accent" : "muted"}
    stats={[
      { key: "items", value: done ? items.length : "—", label: done ? "Leftovers" : job.busy ? "Scanning" : "Not scanned", tone: items.length ? "accent" : "muted" },
      { key: "size", value: done ? formatBytes(totalBytes) : "—", label: "Detected", tone: totalBytes ? "success" : "muted" },
      { key: "likely", value: done ? likely.length : "—", label: "High confidence", tone: likely.length ? "danger" : "muted" },
    ]}
    footer={[
      { key: "sources", icon: <HardDrivesIcon size={13} />, text: job.job?.result?.inventorySources ? <span className="text-[10px] text-(--iux-muted-foreground)">{job.job.result.inventorySources.join(", ")}</span> : <span className="text-[10px] text-(--iux-muted-foreground)">—</span> },
    ]}>
    {job.error && <ErrorLine text={job.error} className="px-4 pt-1" />}
    <div className="px-4 py-2">
      <div className="mt-1 flex gap-2">
        <button type="button" className="iux-btn" data-variant="primary" disabled={job.busy} onClick={() => void job.run()}>Scan leftovers</button>
        {job.busy && <button type="button" className="iux-btn" onClick={() => void job.cancel()}>Cancel</button>}
      </div>
      <div className="mt-2 flex gap-1 text-[10px]">
        <Badge tone="danger">{likely.length} likely</Badge>
        <Badge tone="warning">{possible.length} possible</Badge>
      </div>
      {items.length > 0 && <div className="mt-2 divide-y divide-(--iux-border)">
        {items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 py-1 text-xs">
          <div className="min-w-0 flex-1">
            <span className="font-medium truncate">{item.name}</span>
            <p className="text-[10px] text-(--iux-muted-foreground) truncate">{item.path}</p>
          </div>
          <div className="flex items-center gap-1 text-[10px]">
            <Badge tone={confidenceTone(item.confidence)}>{confidenceLabel(item.confidence)}</Badge>
            <span dir="ltr" className="tabular-nums">{formatBytes(item.sizeBytes)}</span>
          </div>
        </div>)}
      </div>}
      {done && items.length === 0 && <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">No leftovers detected.</p>}
      {job.job?.state === "failed" && <ErrorLine text={job.job.error || "Leftovers scan failed."} className="px-4 pt-1" />}
    </div>
  </ProCard>;
}

/**
 * Containers & VMs (CLN-08): Docker/Podman prune preview + run, and VM
 * inventory. Compact version of the Advanced scan extra-tools card.
 */
export function ContainersVmsCard({ locale, now }: { locale: string; now: number }) {
  const [caps, setCaps] = useState<{ available: boolean; engine: string | null; actions: { id: string; risk: string }[]; reason: string } | null>(null);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<CleanupContainerPreview | null>(null);
  const containerJob = useJob<{ status: string; output?: string; bytesRemoved?: number | null; candidateCount?: number }>(
    () => api.cleanupContainerPrune(preview?.previewId ?? ""),
    (id) => api.cleanupAuxJob<{ status: string; output?: string; bytesRemoved?: number | null; candidateCount?: number }>(id),
  );
  const vmJob = useJob<CleanupVMInventory>(
    () => api.cleanupVMScan(),
    (id) => api.cleanupAuxJob<CleanupVMInventory>(id),
  );

  useEffect(() => {
    let alive = true;
    void api.cleanupContainers().then((value) => { if (alive) setCaps({ available: value.available, engine: value.engine, actions: value.actions.map((a) => ({ id: a.id, risk: a.risk })), reason: value.reason }); }).catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);

  async function loadPreview(actionId: string) {
    setPreview(null);
    try { setPreview(await api.cleanupContainerPreview(actionId)); }
    catch (e) { setError(String(e)); }
  }
  async function prune() {
    if (!preview || preview.expiresAt <= now || preview.candidateCount === 0) return;
    await containerJob.run();
  }
  async function scanVms() {
    await vmJob.run();
  }

  const loading = caps == null && error === "";
  const actions = caps?.actions ?? [];

  if (loading) return <ProCard id="pro-containers" title="Containers & VMs" dot="muted" stats={[]}><p className="px-4 py-2 text-[10px] text-(--iux-muted-foreground)">Checking container engine…</p></ProCard>;
  const containerCaps = caps ?? { available: false, engine: null, actions: [], reason: error || "No container engine responds." };
  const vmDone = vmJob.job?.state === "done";
  return <ProCard id="pro-containers" title="Containers & VMs" dot={error ? "danger" : containerCaps.available ? "accent" : "muted"}
    actions={<ProAction label="Refresh" icon={<ArrowsClockwiseIcon size={15} />} onClick={() => { void api.cleanupContainers().then((value) => setCaps({ available: value.available, engine: value.engine, actions: value.actions.map((a) => ({ id: a.id, risk: a.risk })), reason: value.reason })).catch((e) => setError(String(e))); }} disabled={containerJob.busy} />}
    stats={[
      { key: "engine", value: <span className="text-[10px]">{containerCaps.engine?.toUpperCase() ?? "—"}</span>, label: "Engine", tone: containerCaps.available ? "success" : "muted" },
      { key: "actions", value: actions.length, label: "Prunable", tone: actions.length ? "accent" : "muted" },
      { key: "vms", value: vmDone ? (vmJob.job?.result?.items.length ?? 0) : "—", label: "VMs", tone: vmDone ? "accent" : "muted" },
    ]}
    footer={containerCaps.available ? actions.map((action) => ({
      key: action.id,
      icon: <Badge tone={action.risk === "high" ? "danger" : action.risk === "medium" ? "warning" : "success"}>{action.risk}</Badge>,
      text: <span className="text-sm">{action.id}</span>,
    })) : [{ key: "engine-unavailable", icon: <CubeIcon size={13} />, text: containerCaps.reason || "No container engine responds." }]}>
    {containerCaps.available && <div className="px-4 py-2 space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-sm">Preview & prune</span>
        {actions.map((action) => <button key={action.id} type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" disabled={containerJob.busy} title={`Preview ${action.id}`} onClick={() => void loadPreview(action.id)}>
          <MagnifyingGlassIcon size={13} />
        </button>)}
      </div>
      {preview && <div className="mt-1 border border-(--iux-border) rounded-md px-2 py-1 text-xs">
        <div className="flex items-center justify-between gap-1 mb-1">
          <span className="font-medium">{preview.actionId}</span>
          <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title="Close" onClick={() => setPreview(null)}>✕</button>
        </div>
        <p className="text-[10px] text-(--iux-muted-foreground) truncate">{preview.command.join(" ")}</p>
        <div className="mt-0.5 flex items-center gap-1 text-[10px]">
          <Badge tone={preview.risk === "high" ? "danger" : preview.risk === "medium" ? "warning" : "success"}>{preview.risk}</Badge>
          <span className="text-(--iux-muted-foreground)">{preview.candidateCount} candidates</span>
        </div>
        <div className="mt-1 flex gap-1">
          <button type="button" className="iux-btn" data-variant="primary" disabled={!preview || containerJob.busy || preview.expiresAt <= now || preview.candidateCount === 0} onClick={() => void prune()}>Confirm prune</button>
          <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" onClick={() => setPreview(null)}>Close</button>
        </div>
        {containerJob.job && <p className="mt-0.5 text-[10px]">{containerJob.job.state === "running" ? "Pruning…" : containerJob.job.state === "failed" ? `Failed: ${containerJob.job.error}` : `Finished: ${containerJob.job.result?.bytesRemoved != null ? formatBytes(containerJob.job.result?.bytesRemoved) : containerJob.job.result?.output ?? "done"}`}</p>}
      </div>}
    </div>}
    <div className="px-4 py-2">
      <p className="text-xs font-medium"><span>VMs</span> <span aria-hidden="true">·</span> <span className="text-(--iux-muted-foreground)">Report only</span></p>
      <div className="mt-2 flex gap-2">
        <button type="button" className="iux-btn" disabled={vmJob.busy} onClick={() => void scanVms()}>Scan VMs</button>
        {vmJob.busy && <button type="button" className="iux-btn" onClick={() => void vmJob.cancel()}>Cancel</button>}
      </div>
      {vmDone && (vmJob.job?.result?.items.length ?? 0) > 0 && <div className="mt-1 divide-y divide-(--iux-border)">
        {vmJob.job?.result?.items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 py-0.5 text-xs">
          <span className="font-medium truncate">{item.name}</span>
          <span className="flex items-center gap-1 text-[10px]"><Badge>Report only</Badge> <span dir="ltr" className="tabular-nums">{formatBytes(item.sizeBytes)}</span></span>
        </div>)}
      </div>}
      {vmDone && !vmJob.job?.result?.items.length && <p className="mt-2 text-xs text-(--iux-muted-foreground)">No virtual machines found.</p>}
      {vmJob.job?.state === "failed" && <ErrorLine text={vmJob.job.error || "VM scan failed."} className="pt-1" />}
      {vmJob.error && <ErrorLine text={vmJob.error} className="pt-1" />}
    </div>
    {error && <ErrorLine text={error} className="px-4 pt-1" />}
    {containerJob.error && <ErrorLine text={containerJob.error} className="px-4 pt-1" />}
  </ProCard>;
}

/**
 * Custom entries (CLNP-20): user folders bookmarked as `custom.<slug>` entries.
 * List them with remove; adding a folder goes through the Settings flow.
 */
export function CustomEntriesCard({ settingsHref }: { settingsHref: string }) {
  const [entries, setEntries] = useState<CleanupEntry[] | null>(null);
  const [error, setError] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void api.cleanupCatalog().then((value) => { if (alive) setEntries(value.entries); }).catch((e) => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);

  const items = entries?.filter((item) => item.id.startsWith("custom.")) ?? [];

  async function remove(entryId: string) {
    setError("");
    setRemoving(entryId);
    try { await api.cleanupCustomRemove(entryId); setEntries((old) => old?.filter((entry) => entry.id !== entryId) ?? null); }
    catch (e) { setError(String(e)); }
    finally { setRemoving(null); }
  }

  if (entries == null && !error) return <ProCard id="pro-custom" title="Custom entries" dot="muted"><p>Loading custom folders…</p></ProCard>;
  return <ProCard id="pro-custom" title="Custom entries" dot={items.length ? "accent" : "muted"}
    stats={[
      { key: "count", value: items.length, label: "Custom folders", tone: items.length ? "accent" : "muted" },
    ]}
    actions={<a className="iux-btn iux-touch-target" data-variant="outline" data-size="icon" title="Add a folder" href={settingsHref}><SparkleIcon size={14} /></a>}
    footer={items.map((item) => ({
      key: item.id,
      icon: <BookmarkSimpleIcon size={13} />,
      text: <><span className="font-medium truncate">{item.name}</span>
        <span className="text-(--iux-muted-foreground)"> · Your folder</span></>,
    }))}>
    {error && <ErrorLine text={error} className="px-4 pt-1" />}
    <div className="px-4 py-2 space-y-1">
      {items.map((item) => <div key={item.id} className="flex items-center justify-between gap-2 py-1 text-xs">
        <div className="min-w-0 flex-1">
          <span className="font-medium truncate">{item.name}</span>
          <p className="text-[10px] text-(--iux-muted-foreground) truncate">{item.paths.map((p) => p.path ?? p.reason).join(" · ")}</p>
        </div>
        <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title="Remove custom entry" aria-label="Remove custom entry" disabled={removing !== null} onClick={() => void remove(item.id)}>✕</button>
      </div>)}
      {items.length === 0 && <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">No custom folders yet.</p>}
      <p className="mt-1 text-[10px] text-(--iux-muted-foreground)">Add a user folder in <a className="underline" href={settingsHref}>Settings → Bookmarks</a>.</p>
    </div>
  </ProCard>;
}
