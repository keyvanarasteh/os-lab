/**
 * CLNP-11: the background-monitor card and its warning banner.
 *
 * The card edits the typed config through POST /api/cleanup/monitor/config
 * (the whole config is sent; the engine validates and normalizes it) and
 * shows the runner state, per-volume floors against live free space, and the
 * recent events. The monitor state itself is polled by pages.tsx — only
 * while the runner is enabled — and passed in through props, so this card
 * never starts a second poller. Public Pages never mounts it.
 */
import { useState } from "react";
import { ArrowsClockwiseIcon, BellIcon, ClockIcon, PlusIcon, PulseIcon, TrashIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { api, formatBytes, message, type CleanupMonitorConfig, type CleanupMonitorStatus, type CleanupVolume } from "../../lib/api";
import { SummaryCard, relativeTime } from "./summary-cards";

const INTERVALS = [60, 120, 300, 600, 1800, 3600];

function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

export function MonitorBanner({ monitor, scanHref }: { monitor: CleanupMonitorStatus | null; scanHref: string }) {
  if (!monitor?.enabled || !monitor.activeWarnings.length) return null;
  return <div role="status" className="rounded-md border border-(--iux-warning)/50 bg-(--iux-warning)/10 p-3 text-sm">
    <p className="font-medium">Free space is running low</p>
    {monitor.activeWarnings.map((warning, index) => <p key={index} className="mt-1 text-xs">
      <span translate="no">{warning.volume}</span> — the monitor warned about this volume.{" "}
      <a className="underline" href={scanHref}>Run a scan to see what can be freed.</a>
    </p>)}
  </div>;
}

export function MonitorCard({
  monitor, volumes, reload
}: {
  monitor: CleanupMonitorStatus | null; volumes: CleanupVolume[] | null; reload: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(mutate: (current: CleanupMonitorStatus) => CleanupMonitorConfig) {
    if (!monitor) return;
    setBusy(true); setError("");
    try {
      await api.cleanupMonitorConfig(mutate(monitor));
      reload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  function configFrom(current: CleanupMonitorStatus): CleanupMonitorConfig {
    return {
      enabled: current.enabled,
      intervalSeconds: current.intervalSeconds,
      cooldownSeconds: current.cooldownSeconds,
      volumes: current.volumes.map(({ mountPoint, minFreeBytes, minFreePercent, enabled }) => ({
        mountPoint, minFreeBytes, minFreePercent, enabled,
      })),
    };
  }

  if (!monitor || !Array.isArray(monitor.volumes)) return null;
  const configuredMounts = new Set(monitor.volumes.map((entry) => entry.mountPoint).filter(Boolean));
  const addable = (volumes ?? []).filter((volume) => !configuredMounts.has(volume.mountPoint));

  return <Section id="cleanup-monitor-config" title="Background monitor" description="Checks disk free space while the console runs and warns when a volume crosses its threshold. Nothing is cleaned automatically by this card.">
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant={monitor.enabled ? "primary" : "outline"} disabled={busy}
        onClick={() => void save((current) => ({ ...configFrom(current), enabled: !current.enabled }))}>
        {monitor.enabled ? "Monitoring" : "Enable monitoring"}
      </button>
      <label className="text-sm">Check every{" "}
        <select className="iux-input ml-1" value={monitor.intervalSeconds} disabled={busy || !monitor.enabled}
          onChange={(event) => void save((current) => ({ ...configFrom(current), intervalSeconds: Number(event.target.value) }))}>
          {INTERVALS.map((seconds) => <option key={seconds} value={seconds}>{formatInterval(seconds)}</option>)}
        </select>
      </label>
      <span className="text-xs text-(--iux-muted-foreground)">
        {monitor.enabled ? (monitor.running ? "runner active" : "runner starting") : "off — no checks run"}
      </span>
      <button type="button" className="iux-btn ms-auto" disabled={busy || !monitor.enabled} onClick={() => { setBusy(true); setError(""); void api.cleanupMonitorEvaluate().then(() => reload()).catch((e) => setError(message(e))).finally(() => setBusy(false)); }}>
        Check now
      </button>
    </div>
    {monitor.configError && <Status value={{ ok: false, text: monitor.configError }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="mt-3 divide-y divide-(--iux-border)">
      {monitor.volumes.map((entry, index) => {
        const state = monitor.state.volumes[`volumes:${entry.mountPoint}`];
        return <div key={`${entry.mountPoint}-${index}`} className="flex flex-wrap items-center gap-2 py-2 text-sm">
          <input type="checkbox" className="iux-touch-target size-4 accent-[#f36c21]" aria-label="Check this volume"
            checked={entry.enabled} disabled={busy}
            onChange={(event) => void save((current) => ({
              ...configFrom(current),
              volumes: current.volumes.map((row, rowIndex) => rowIndex === index ? { ...row, enabled: event.target.checked } : row),
            }))} />
          <span className="min-w-0 flex-1 truncate" translate="no">{entry.mountPoint || "Home volume"}</span>
          {entry.volume && <span dir="ltr" className="tabular-nums text-xs text-(--iux-muted-foreground)">
            {formatBytes(entry.volume.freeBytes)} free
          </span>}
          <Badge tone={state?.state === "warning" ? "danger" : state?.state === "ok" ? "success" : undefined}>
            {state?.state === "warning" ? "warning" : state?.state === "ok" ? "ok" : "no data"}
          </Badge>
          <label className="text-xs">warn under{" "}
            <input type="number" className="iux-input w-20" min={0} dir="ltr" disabled={busy} defaultValue={Math.round(entry.minFreeBytes / (1024 * 1024 * 1024))}
              onBlur={(event) => void save((current) => ({
                ...configFrom(current),
                volumes: current.volumes.map((row, rowIndex) => rowIndex === index ? { ...row, minFreeBytes: Math.max(0, Number(event.target.value)) * 1024 * 1024 * 1024 } : row),
              }))} />{" "}GiB
          </label>
          <label className="text-xs">or{" "}
            <input type="number" className="iux-input w-16" min={0} max={100} dir="ltr" disabled={busy} defaultValue={entry.minFreePercent}
              onBlur={(event) => void save((current) => ({
                ...configFrom(current),
                volumes: current.volumes.map((row, rowIndex) => rowIndex === index ? { ...row, minFreePercent: Math.min(100, Math.max(0, Number(event.target.value))) } : row),
              }))} />{" "}%
          </label>
          <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} title="Remove this volume"
            onClick={() => void save((current) => ({ ...configFrom(current), volumes: current.volumes.filter((_, rowIndex) => rowIndex !== index) }))}>
            <TrashIcon size={14} />
          </button>
        </div>;
      })}
    </div>
    {addable.length > 0 && <details className="mt-2 text-sm">
      <summary className="iux-btn cursor-pointer" data-variant="ghost"><PlusIcon size={14} className="inline" /> Add a volume</summary>
      <div className="mt-2 space-y-1">
        {addable.map((volume) => <button key={volume.mountPoint} type="button" className="iux-btn w-full justify-start text-left" disabled={busy}
          onClick={() => void save((current) => ({
            ...configFrom(current),
            volumes: [...current.volumes, { mountPoint: volume.mountPoint, minFreeBytes: 10 * 1024 * 1024 * 1024, minFreePercent: 10, enabled: true }],
          }))}>
          <span translate="no">{volume.mountPoint}</span> <span className="text-xs text-(--iux-muted-foreground)">{volume.kind}</span>
        </button>)}
      </div>
    </details>}
    <div className="mt-3">
      <p className="text-xs font-medium text-(--iux-muted-foreground)">Recent events</p>
      {monitor.state.events.length ? <ul className="mt-1 space-y-1 text-xs">
        {monitor.state.events.slice(-8).reverse().map((event, index) => <li key={index} className="flex gap-2">
          <BellIcon size={12} className={event.kind === "warning" ? "mt-0.5 text-(--iux-danger)" : event.kind === "recovered" ? "mt-0.5 text-(--iux-success)" : "mt-0.5 text-(--iux-muted-foreground)"} />
          <span>{new Date(event.at * 1000).toLocaleTimeString()} · {event.kind} · <span translate="no">{event.volume}</span>{event.freeBytes != null && ` · ${formatBytes(event.freeBytes)} free`}{event.message && ` · ${event.message}`}</span>
        </li>)}
      </ul> : <Empty>Nothing recorded yet.</Empty>}
    </div>
  </Section>;
}

/**
 * CLNP-11 / dashboard summary style: the monitor's read-only state as one
 * summary card — configured volumes, active warnings, check interval, next
 * check, the home volume's used bar and the latest check. It lives on the
 * Settings tab beside the Background monitor card that edits thresholds; the
 * dashboard keeps only one monitor line inside the Ready to clean card.
 */
export function MonitorStatsCard({
  monitor, volumes, locale, now, onReload
}: {
  monitor: CleanupMonitorStatus | null; volumes: CleanupVolume[] | null; locale: string; now: number; onReload: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!monitor || !Array.isArray(monitor.volumes)) return null;
  const warnings = monitor.activeWarnings.length;
  const measured = (volumes ?? []).filter((volume) => !volume.error && volume.totalBytes && volume.freeBytes != null);
  const home = measured.find((volume) => volume.isHome) ?? measured[0];
  const usedPercent = home?.usage != null ? Math.round(home.usage * 100) : null;
  const lastEvaluationAt = monitor.state?.lastEvaluationAt ?? null;
  const nextCheckAt = monitor.enabled && lastEvaluationAt != null ? lastEvaluationAt + monitor.intervalSeconds : null;
  const nextCheck = nextCheckAt == null ? null : nextCheckAt > now ? relativeTime(nextCheckAt, locale, now) : "due now";
  const lastChecked = relativeTime(lastEvaluationAt, locale, now);
  const rows = monitor.volumes.length ? monitor.volumes.map((entry) => ({
    key: entry.mountPoint,
    label: entry.mountPoint || "Home volume",
    freeBytes: entry.volume?.freeBytes ?? null,
    state: monitor.state?.volumes?.[`volumes:${entry.mountPoint}`]?.state,
    monitored: true,
  })) : (volumes ?? []).slice(0, 4).map((volume) => ({
    key: volume.mountPoint,
    label: volume.mountPoint,
    freeBytes: volume.freeBytes ?? null,
    state: volume.pressure === "warning" ? "warning" : undefined,
    monitored: false,
  }));

  async function checkNow() {
    setBusy(true);
    setError("");
    try {
      await api.cleanupMonitorEvaluate();
      onReload();
    } catch (evaluateError) {
      setError(message(evaluateError));
    } finally {
      setBusy(false);
    }
  }

  return <SummaryCard id="cleanup-monitor" title="Monitor stats"
    description="Free-space checks while the console runs."
    dot={!monitor.enabled ? "muted" : warnings ? "danger" : "success"}
    actions={<button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title="Check now" aria-label="Check now"
      disabled={busy || !monitor.enabled} onClick={() => void checkNow()}>
      <ArrowsClockwiseIcon size={16} className={busy ? "animate-spin" : undefined} />
    </button>}
    stats={[
      { key: "volumes", value: monitor.volumes.length, label: "Monitored volumes", tone: monitor.volumes.length ? "accent" : "muted" },
      { key: "warnings", value: warnings, label: "Warnings", tone: warnings ? "danger" : "success" },
      { key: "interval", value: formatInterval(monitor.intervalSeconds), label: "Check interval", tone: "accent" },
      { key: "next", value: nextCheck ?? "—", label: "Next check", tone: nextCheckAt == null ? "muted" : nextCheckAt > now ? "accent" : "danger" },
    ]}
    bar={usedPercent != null ? { percent: usedPercent, label: "% used", caption: <><span dir="ltr">{usedPercent}</span>% used</> } : undefined}
    footer={[
      { key: "state", icon: <PulseIcon size={14} />, text: <>
        <span>{monitor.enabled ? "Monitoring on" : "Monitoring off"}</span>{" "}
        <span className="text-(--iux-muted-foreground)">
          · {monitor.enabled ? (monitor.running ? "runner active" : "runner starting") : "no checks run"}
        </span>
      </> },
      { key: "active", icon: <BellIcon size={14} />, text: warnings
        ? <span className="text-(--iux-danger)"><span dir="ltr">{warnings}</span>{" "}
            <span>{warnings === 1 ? "warning active" : "warnings active"}</span></span>
        : <span>No warnings</span> },
      { key: "checked", icon: <ClockIcon size={14} />, text: <><span>Last checked</span>{" "}
        <span className="text-(--iux-muted-foreground)">{lastChecked ?? "Never"}</span></> },
    ]}>
    {monitor.configError && <Status value={{ ok: false, text: monitor.configError }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="divide-y divide-(--iux-border)">
      {rows.map((row) => <div key={row.key} className="flex flex-wrap items-center gap-2 py-2 text-sm">
        <span className="min-w-0 flex-1 truncate" translate="no">{row.label}</span>
        {row.freeBytes != null && <span dir="ltr" className="tabular-nums text-xs text-(--iux-muted-foreground)">{formatBytes(row.freeBytes)} free</span>}
        <Badge tone={row.state === "warning" ? "danger" : row.state === "ok" ? "success" : undefined}>
          {row.state === "warning" ? "warning" : row.state === "ok" ? "ok" : row.monitored ? "no data" : "not monitored"}
        </Badge>
      </div>)}
      {!rows.length && <Empty>No volumes measured yet.</Empty>}
    </div>
    {(monitor.state?.events?.length ?? 0) > 0 && <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-xs text-(--iux-muted-foreground)">Recent events</summary>
      <ul className="mt-1 space-y-1 text-xs">
        {(monitor.state?.events ?? []).slice(-4).reverse().map((event, index) => <li key={index} className="flex gap-2">
          <BellIcon size={12} className={event.kind === "warning" ? "mt-0.5 text-(--iux-danger)" : event.kind === "recovered" ? "mt-0.5 text-(--iux-success)" : "mt-0.5 text-(--iux-muted-foreground)"} />
          <span>{new Date(event.at * 1000).toLocaleTimeString()} · {event.kind} · <span translate="no">{event.volume}</span>{event.freeBytes != null && ` · ${formatBytes(event.freeBytes)} free`}{event.message && ` · ${event.message}`}</span>
        </li>)}
      </ul>
    </details>}
  </SummaryCard>;
}
