/**
 * The dashboard's summary cards in the reference widget's style: a quiet
 * "os-lab" eyebrow with a state dot, one bold headline, a 2×2 grid of
 * headline numbers, one ratio bar and a short icon footer. The cards carry
 * the actions themselves — Clean and Rescan as icon buttons in the header —
 * and keep the cleanup plan, its checkboxes and the confirm flow working
 * exactly as before. Colours stay on the lab's own tokens.
 */
import type { ReactNode } from "react";
import {
  ArrowsClockwiseIcon, BellIcon, BookmarkSimpleIcon, BroomIcon, ClockIcon, LightningIcon, PulseIcon, SparkleIcon, TrashIcon
} from "@phosphor-icons/react";
import { Badge, Status } from "../../components/ui";
import { formatBytes, type BookmarksPayload, type CleanupEntry, type CleanupJob, type CleanupMonitorStatus, type CleanupScan, type CleanupWidgetSnapshot } from "../../lib/api";
import { CATALOG_GROUPS, groupIdOf } from "./groups";
import { GroupTile } from "./group-icon";

export type SummaryTone = "accent" | "success" | "danger" | "warning" | "muted";

const VALUE_TONE: Record<SummaryTone, string> = {
  accent: "text-[#f36c21]",
  success: "text-(--iux-success)",
  danger: "text-(--iux-danger)",
  warning: "text-(--iux-warning)",
  muted: "text-(--iux-muted-foreground)",
};
const DOT_TONE: Record<SummaryTone, string> = {
  accent: "bg-[#f36c21]",
  success: "bg-(--iux-success)",
  danger: "bg-(--iux-danger)",
  warning: "bg-(--iux-warning)",
  muted: "bg-(--iux-muted-foreground)",
};

/**
 * A localized relative time ("3 hours ago", "in 5 minutes"), or null when no
 * timestamp was proven. Intl keeps the wording in the active locale instead of
 * shipping an English suffix for every unit.
 */
export function relativeTime(atSeconds: number | null | undefined, locale: string, nowSeconds: number): string | null {
  if (atSeconds == null || !Number.isFinite(atSeconds)) return null;
  const diff = atSeconds - nowSeconds;
  const abs = Math.abs(diff);
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1]];
  for (const [unit, size] of units) {
    if (abs >= size || unit === "second") return formatter.format(Math.round(diff / size), unit);
  }
  return null;
}

export type SummaryStat = { key: string; value: ReactNode; label: string; tone?: SummaryTone };
export type SummaryFooterLine = { key: string; icon: ReactNode; text: ReactNode };
export type SummaryBar = { percent: number; caption: ReactNode; label: string; tone?: SummaryTone };

/** The card shell: eyebrow, headline, actions, stat grid, bar and footer. */
export function SummaryCard({
  id, title, description, dot = "accent", actions, stats, bar, footer, children
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  dot?: SummaryTone;
  actions?: ReactNode;
  stats: SummaryStat[];
  bar?: SummaryBar;
  footer: SummaryFooterLine[];
  children?: ReactNode;
}) {
  return <section id={id} className={`iux-card ${children ? "" : "pb-5"}`}>
    <div className="flex items-center justify-between gap-3 px-5 pt-5">
      <span translate="no" className="text-xs font-semibold tracking-wide text-(--iux-muted-foreground)">os-lab</span>
      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${DOT_TONE[dot]}`} />
    </div>
    <div className="mt-1.5 flex items-start justify-between gap-3 px-5">
      <div className="min-w-0">
        <h2 className="text-lg leading-tight font-bold">{title}</h2>
        {description && <p className="mt-1 text-xs text-(--iux-muted-foreground)">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
    <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 px-5">
      {stats.map((stat) => <div key={stat.key} className="min-w-0">
        <p dir="ltr" className={`truncate text-xl font-bold tabular-nums ${VALUE_TONE[stat.tone ?? "accent"]}`}>{stat.value}</p>
        <p className="mt-0.5 truncate text-xs text-(--iux-muted-foreground)">{stat.label}</p>
      </div>)}
    </div>
    {bar && <div className="mt-4 px-5">
      <div className="h-1.5 overflow-hidden rounded-full bg-(--iux-muted)" role="progressbar" aria-label={bar.label}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(bar.percent)}>
        <span className={`block h-full rounded-full ${bar.tone === "success" ? "bg-(--iux-success)" : bar.tone === "danger" ? "bg-(--iux-danger)" : "bg-[#f36c21]"}`}
          style={{ width: `${Math.min(100, Math.max(0, bar.percent))}%` }} />
      </div>
      <p className="mt-1.5 truncate text-xs text-(--iux-muted-foreground)">{bar.caption}</p>
    </div>}
    <div className="mt-4 border-t border-(--iux-border) px-5 pt-3">
      <ul className="space-y-2 text-sm">
        {footer.map((line) => <li key={line.key} className="flex items-start gap-2">
          <span className="mt-0.5 shrink-0 text-(--iux-muted-foreground)" aria-hidden="true">{line.icon}</span>
          <span className="min-w-0 flex-1">{line.text}</span>
        </li>)}
      </ul>
    </div>
    {children && <div className="mt-3 border-t border-(--iux-border) px-5 py-4">{children}</div>}
  </section>;
}

/** One icon action in a summary card's header. */
function CardAction({
  label, icon, onClick, disabled, busy = false
}: {
  label: string; icon: ReactNode; onClick: () => void; disabled: boolean; busy?: boolean;
}) {
  return <button type="button" className="iux-btn iux-touch-target" data-variant="ghost" data-size="icon" title={label} aria-label={label}
    disabled={disabled} onClick={onClick}>
    <span className={busy ? "inline-flex animate-spin" : "inline-flex"}>{icon}</span>
  </button>;
}

/**
 * The "Ready to clean" card: the latest scan's found items and reclaimable
 * size, the disk and reclaim totals around it, one used-space bar, and the
 * last scan / cleanup / monitor / bookmarks facts from the widget snapshot.
 * Rescan measures every catalog entry; Clean plans the safe measured groups
 * and opens the shared confirmation dialog — nothing is removed here.
 */
export function ReadyCard({
  scan, scanFinishedAt, widget, monitor, bookmarks, active, entries, measured, checked, setChecked,
  diskFreeBytes, diskUsedPercent, canWork, locale, now, onScan, onCancel, onClean, groupHref, error
}: {
  scan: CleanupScan | undefined;
  scanFinishedAt: number | null | undefined;
  widget: CleanupWidgetSnapshot | null;
  monitor: CleanupMonitorStatus | null;
  bookmarks: BookmarksPayload | null;
  active: CleanupJob | null;
  entries: CleanupEntry[];
  measured: Map<string, CleanupScan["entries"][number]>;
  checked: string[];
  setChecked: (ids: string[]) => void;
  diskFreeBytes: number | null | undefined;
  diskUsedPercent: number | null;
  canWork: boolean;
  locale: string;
  now: number;
  onScan: () => void;
  onCancel: () => void;
  onClean: (ids: string[]) => void;
  groupHref: (groupId: string) => string;
  error?: string;
}) {
  const scanning = active?.state === "running" && active.kind === "scan";
  const cleaning = active?.state === "running" && active.kind === "clean";
  const done = Number(active?.progress?.pathsDone ?? active?.progress?.itemsDone ?? 0);
  const total = Number(active?.progress?.pathsTotal ?? active?.progress?.itemsTotal ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  const foundItems = scan ? (scan.totals.paths ?? scan.totals.entries ?? scan.entries.length) : widget?.lastScan?.foundItems ?? null;
  const foundBytes = scan ? scan.totals.sizeBytes : widget?.lastScan?.foundBytes ?? null;
  const lastScanAt = scanFinishedAt ?? widget?.lastScan?.finishedAt ?? null;
  const reclaimed = widget?.cleanup.totalReclaimedBytes ?? null;
  const lastCleanupAt = widget?.cleanup.lastRunAt ?? null;

  // A previous session's scan (folded into the widget snapshot) still counts:
  // the headline follows the last measured bytes, not this island's job list.
  // A partial monitor payload (an older console, or a mocked API) must not
  // crash the card: only a payload with its own arrays and state counts.
  const monitorKnown = !!monitor && typeof monitor.enabled === "boolean" && Array.isArray(monitor.volumes);
  const warnings = monitorKnown ? monitor.activeWarnings.length : 0;
  const title = scanning ? "Scanning" : cleaning ? "Cleaning"
    : foundBytes == null ? "Ready to scan" : foundBytes > 0 ? "Ready to clean" : "Up to date";
  const dot: SummaryTone = scanning || cleaning ? "accent"
    : warnings ? "danger" : foundBytes === 0 ? "success" : "accent";

  const rows = CATALOG_GROUPS.map((group) => {
    const items = entries.filter((entry) => groupIdOf(entry.id) === group.id && (measured.get(entry.id)?.sizeBytes ?? 0) > 0);
    return { group, items, bytes: items.reduce((sum, entry) => sum + (measured.get(entry.id)?.sizeBytes ?? 0), 0) };
  }).filter((row) => row.items.length).sort((a, b) => b.bytes - a.bytes);
  const rowIds = (ids: string[]) => ids.filter((id) => checked.includes(id));
  const selectedBytes = rows.reduce((sum, row) => sum + row.items.filter((entry) => checked.includes(entry.id))
    .reduce((sum, entry) => sum + (measured.get(entry.id)?.sizeBytes ?? 0), 0), 0);
  const cleanIds = rows.flatMap((row) => rowIds(row.items.filter((entry) =>
    entry.cleanable !== false && !entry.needsPrivilege && !["high", "credentials", "privacy"].includes(entry.risk)).map((entry) => entry.id)));

  const scanAgo = relativeTime(lastScanAt, locale, now);
  const cleanupAgo = relativeTime(lastCleanupAt, locale, now);
  const lastEvaluationAt = monitorKnown ? monitor.state?.lastEvaluationAt ?? null : null;
  const nextCheckAt = monitorKnown && monitor.enabled && lastEvaluationAt != null
    ? lastEvaluationAt + monitor.intervalSeconds : null;
  // The engine's next tick is last check + interval; once that moment passed the
  // runner is late, so say so instead of rendering a negative "in" value.
  const nextCheck = nextCheckAt == null ? null : nextCheckAt > now ? relativeTime(nextCheckAt, locale, now) : "due now";
  const quick = bookmarks?.bookmarks.filter((item) => item.quickClean).length ?? 0;
  const bookmarkCount = bookmarks?.bookmarks.length ?? 0;

  const bar = scanning || cleaning
    ? { percent, tone: "accent" as SummaryTone, label: scanning ? "Scanning" : "Cleaning",
        caption: <><span dir="ltr">{percent}%</span>{scanning && active?.progress?.currentEntry ? <> · <span translate="no">{String(active.progress.currentEntry)}</span></> : null}</> }
    : diskUsedPercent != null
      ? { percent: diskUsedPercent, tone: "accent" as SummaryTone, label: "% used", caption: <><span dir="ltr">{diskUsedPercent}</span>% used</> }
      : undefined;

  return <SummaryCard id="overview-ready" title={title} dot={dot}
    actions={<>
      <CardAction label="Rescan" icon={<ArrowsClockwiseIcon size={16} />} onClick={onScan} busy={scanning}
        disabled={!canWork || !entries.length} />
      <CardAction label="Clean" icon={<BroomIcon size={16} />} onClick={() => onClean(cleanIds)}
        disabled={!canWork || !cleanIds.length} />
    </>}
    stats={[
      { key: "found", value: foundItems != null ? <>{foundItems} <span className="text-sm font-semibold">items</span></> : "—", label: "Found", tone: foundItems ? "accent" : "muted" },
      { key: "reclaimable", value: formatBytes(foundBytes), label: "Reclaimable", tone: foundBytes ? "accent" : "muted" },
      { key: "disk-free", value: formatBytes(diskFreeBytes), label: "Disk free", tone: diskFreeBytes != null ? "success" : "muted" },
      { key: "reclaimed", value: reclaimed != null ? formatBytes(reclaimed) : "—", label: "Total reclaimed", tone: reclaimed ? "success" : "muted" },
    ]}
    bar={bar}
    footer={[
      { key: "last-scan", icon: <ClockIcon size={14} />, text: <><span>Last scan</span> <span className="text-(--iux-muted-foreground)">{scanAgo ?? "Never"}</span></> },
      { key: "last-cleanup", icon: <TrashIcon size={14} />, text: <><span>Last cleanup</span> <span className="text-(--iux-muted-foreground)">{cleanupAgo ?? "Never"}</span></> },
      ...(monitorKnown ? [{ key: "monitor", icon: <PulseIcon size={14} />, text: warnings
        ? <span className="flex flex-wrap items-center gap-x-1.5 text-(--iux-danger)"><span>Monitor warning</span>
            {nextCheck && <span className="text-(--iux-muted-foreground)">{" · "}<span>Next check</span> {nextCheck}</span>}</span>
        : <span className="flex flex-wrap items-center gap-x-1.5"><span>{monitor.enabled ? "Monitor on" : "Monitor off"}</span>
            {nextCheck && <span className="text-(--iux-muted-foreground)">{" · "}<span>Next check</span> {nextCheck}</span>}</span> }] : []),
      { key: "bookmarks", icon: <SparkleIcon size={14} />, text: <><span dir="ltr">{bookmarkCount}</span> <span>bookmarks</span>
        {quick ? <span className="text-(--iux-muted-foreground)">{" · "}<span dir="ltr">{quick}</span> <span>flagged for quick clean</span></span>
          : <span className="text-(--iux-muted-foreground)">, <span>none flagged for quick clean</span></span>}</> },
    ]}>
    {scanning && <>
      {String(active?.progress?.currentPath ?? "") && <p className="truncate text-xs text-(--iux-muted-foreground)" dir="ltr" translate="no"
        title={String(active?.progress?.currentPath ?? "")}>{String(active?.progress?.currentPath)}</p>}
      <div className="mt-3 flex items-center gap-3">
        <button type="button" className="iux-btn" onClick={onCancel}>Stop scan</button>
        <span className="text-xs text-(--iux-muted-foreground)">Stopping keeps the results found so far.</span>
      </div>
    </>}
    {!scanning && <>
      {error && <p role="alert" className="text-sm text-(--iux-danger)">{error}</p>}
      {rows.length ? <>
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Cleanup plan</h3>
          <span className="text-xs text-(--iux-muted-foreground)"><span>Selected</span> <span dir="ltr" className="tabular-nums">{formatBytes(selectedBytes)}</span></span>
        </div>
        <ul className="mt-2 divide-y divide-(--iux-border) rounded-md border border-(--iux-border)">
          {rows.map(({ group, items, bytes }) => {
            const ids = items.map((entry) => entry.id);
            const on = rowIds(ids);
            return <li key={group.id} className="flex items-center gap-3 px-3 py-2">
              <input type="checkbox" className="size-4 accent-[#f36c21]" aria-label={`Select ${group.label}`} checked={on.length === ids.length}
                ref={(el) => { if (el) el.indeterminate = on.length > 0 && on.length < ids.length; }}
                onChange={(event) => setChecked(event.target.checked ? [...new Set([...checked, ...ids])] : checked.filter((id) => !ids.includes(id)))} />
              <a href={groupHref(group.id)} className="flex min-w-0 flex-1 items-center gap-3 no-underline">
                <GroupTile groupId={group.id} size={30} />
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{group.label}</span>
                  <span className="block text-xs text-(--iux-muted-foreground)">{on.length} of {ids.length} selected</span></span>
                <span dir="ltr" className="text-sm font-semibold tabular-nums">{formatBytes(bytes)}</span>
              </a>
            </li>;
          })}
        </ul>
        <p className="mt-2 text-xs text-(--iux-muted-foreground)">Open a category to review individual items. Measured-only, privileged and high-risk items are never cleaned from here.</p>
      </> : <>
        <p className="text-sm text-(--iux-muted-foreground)">Scan the safe categories, review the plan, then confirm. Nothing is removed during a scan.</p>
        {!canWork && <p className="mt-1 text-xs text-(--iux-muted-foreground)">Scan unavailable until setup is complete</p>}
      </>}
    </>}
  </SummaryCard>;
}

/**
 * The bookmarks summary card: what is bookmarked and how much of it is ready
 * for quick clean, the measured size of those entries and the automation
 * flags, with quick clean and a rescan of only the bookmarked entries as
 * header actions. The bookmark manager itself stays on Settings.
 */
export function BookmarksSummaryCard({
  bookmarks, measured, active, canWork, locale, now, refusals, error, onQuickClean, onRescan, settingsHref
}: {
  bookmarks: BookmarksPayload | null;
  measured: Map<string, CleanupScan["entries"][number]>;
  active: CleanupJob | null;
  canWork: boolean;
  locale: string;
  now: number;
  refusals: string;
  error?: string;
  onQuickClean: () => void;
  onRescan: () => void;
  settingsHref: string;
}) {
  const items = bookmarks?.bookmarks ?? [];
  const quick = items.filter((item) => item.quickClean);
  const hooks = items.filter((item) => item.autoCleanHook.enabled).length;
  const alerts = items.filter((item) => item.sizeAlert.enabled).length;
  const measuredItems = items.filter((item) => measured.get(item.entryId)?.sizeBytes != null);
  const measuredBytes = measuredItems.reduce((sum, item) => sum + (measured.get(item.entryId)?.sizeBytes ?? 0), 0);
  const quickPercent = items.length ? Math.round((quick.length / items.length) * 100) : 0;
  const scanning = active?.state === "running" && active.kind === "scan";
  const ready = canWork && quick.length > 0 && !active;
  const lastAlert = items.map((item) => item.sizeAlert.lastAlertAt).filter((at): at is number => at != null).sort((a, b) => b - a)[0];
  const alertAgo = relativeTime(lastAlert, locale, now);

  return <SummaryCard id="overview-bookmarks" title="Bookmarks" dot={bookmarks?.error ? "warning" : quick.length ? "accent" : "muted"}
    actions={<>
      <CardAction label="Rescan" icon={<ArrowsClockwiseIcon size={16} />} onClick={onRescan} busy={scanning} disabled={!canWork || !items.length} />
      <CardAction label="Clean" icon={<BroomIcon size={16} />} onClick={onQuickClean} disabled={!ready || !!active} />
    </>}
    stats={[
      { key: "count", value: items.length, label: "Bookmarked", tone: items.length ? "accent" : "muted" },
      { key: "quick", value: quick.length, label: "For quick clean", tone: quick.length ? "success" : "muted" },
      { key: "measured", value: measuredItems.length ? formatBytes(measuredBytes) : "—", label: "Measured", tone: measuredItems.length ? "success" : "muted" },
      { key: "hooks", value: hooks, label: "Hooks on", tone: hooks ? "accent" : "muted" },
    ]}
    bar={items.length ? { percent: quickPercent, tone: quick.length ? "accent" : "muted", label: "flagged for quick clean",
      caption: <><span dir="ltr">{quickPercent}%</span> <span>flagged for quick clean</span></> } : undefined}
    footer={[
      { key: "bookmarks", icon: <BookmarkSimpleIcon size={14} />, text: <><span dir="ltr">{items.length}</span> <span>bookmarks</span>
        {quick.length ? <span className="text-(--iux-muted-foreground)">{" · "}<span dir="ltr">{quick.length}</span> <span>flagged for quick clean</span></span>
          : <span className="text-(--iux-muted-foreground)">, <span>none flagged for quick clean</span></span>}</> },
      { key: "hooks-alerts", icon: <LightningIcon size={14} />, text: <><span>Auto-clean hooks</span> <span dir="ltr">{hooks}</span>
        <span className="text-(--iux-muted-foreground)"> · <span>Size alerts</span> <span dir="ltr">{alerts}</span></span></> },
      ...(lastAlert != null ? [{ key: "last-alert", icon: <BellIcon size={14} />,
        text: <><span>Last alert</span> <span className="text-(--iux-muted-foreground)">{alertAgo ?? "Never"}</span></> }] : []),
    ]}>
    {bookmarks?.error && <Status value={{ ok: false, text: bookmarks.error }} />}
    {refusals && <Status value={{ ok: false, text: refusals }} />}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={!ready} onClick={onQuickClean}>Quick clean</button>
      <a className="iux-btn" href={settingsHref}>Manage bookmarks</a>
      {items.length > 0 && <Badge>{quick.length} of {items.length} <span>flagged for quick clean</span></Badge>}
    </div>
    {items.length === 0 ? <p className="mt-2 text-xs text-(--iux-muted-foreground)">No bookmarks yet — bookmark entries on the Advanced scan page or add folders in Settings.</p>
      : quick.length === 0 ? <p className="mt-2 text-xs text-(--iux-muted-foreground)">No bookmarks are marked for quick clean yet — enable quick clean in Settings.</p>
      : null}
  </SummaryCard>;
}
