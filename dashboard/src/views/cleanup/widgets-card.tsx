/**
 * CLW-10: the desktop-widgets card — the dashboard surface for the macOS
 * WidgetKit extension (CLW-06/07).
 *
 * The card renders the same numbers the widget shows (one fold of the lab's
 * state) as a live preview, publishes the snapshot on demand, and explains
 * how to add the widget. Publishing is the console's job; `capable` is its
 * honest probe of the App Group container, so a browser or a machine without
 * the widget gets the note instead of a silent no-op. Public Pages never
 * mounts it, and a non-conforming payload renders as "no snapshot yet"
 * instead of crashing the island.
 */
import { useEffect } from "react";
import { MonitorIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Status } from "../../components/ui";
import { formatBytes, type CleanupWidgetSnapshot } from "../../lib/api";

const STATUS_LABELS: Partial<Record<string, string>> = {
  "cleaning": "Cleaning",
  "scanning": "Scanning",
  "ready-to-clean": "Ready to clean",
  "up-to-date": "Up to date",
};

/** Older consoles and empty mocks must degrade, never crash the island. */
function isSnapshot(value: CleanupWidgetSnapshot | null): value is CleanupWidgetSnapshot {
  return !!value && typeof value === "object"
    && typeof value.status === "string"
    && !!value.disk && !!value.monitor && !!value.bookmarks
    && !!value.permissions && !!value.cleanup
    && !!value.publish && typeof value.publish.published === "boolean";
}

function relative(seconds: number | null, fallback: string): string {
  if (seconds == null) return fallback;
  const delta = seconds - Date.now() / 1000;
  if (delta < -60) return `${Math.round(-delta / 60)} min ago`;
  if (delta < 0) return "just now";
  return `in ${Math.max(1, Math.round(delta / 60))} min`;
}

export function WidgetsCard({ snapshot, reload }: { snapshot: CleanupWidgetSnapshot | null; reload: () => void }) {
  const valid = isSnapshot(snapshot);

  // Publishing is automatic: opening this page already builds and publishes the snapshot, and the
  // console refreshes it on a timer, so there is nothing for the user to press.
  useEffect(() => {
    const timer = setInterval(reload, 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, [reload]);

  // Widgets are a macOS feature: on other systems the card would only be noise.
  if (valid && snapshot.platform !== "macos") return null;

  return <Section id="cleanup-widgets" title="Desktop widgets" description="Glanceable storage and cleanup status in macOS Notification Center, kept fresh by this console.">
    {valid && snapshot.platform === "macos" && !snapshot.capable &&
      <Status value={{ ok: true, text: "Publishing is idle until the installed os-lab app creates its widget container." }} />}
    {valid && snapshot.capable && !snapshot.publish.published && snapshot.publish.reason &&
      <Status value={{ ok: false, text: snapshot.publish.reason }} />}
    {valid && snapshot.capable && snapshot.publish.published &&
      <Status value={{ ok: true, text: "Kept up to date automatically." }} />}
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-(--iux-muted-foreground)">What the widget shows</summary>
    {valid && <div className="mt-3 rounded-md border border-(--iux-border) p-3">
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone={snapshot.status === "ready-to-clean" ? "success" : snapshot.status === "cleaning" || snapshot.status === "scanning" ? "warning" : undefined}>
          {STATUS_LABELS[snapshot.status] ?? snapshot.status}
        </Badge>
        {snapshot.monitor.enabled ? <Badge tone={snapshot.monitor.warningCount ? "danger" : undefined}>
          <MonitorIcon size={10} className="inline" /> monitor every {Math.round((snapshot.monitor.intervalSeconds ?? 0) / 60)} min
        </Badge> : <Badge>monitor off</Badge>}
        <Badge tone={snapshot.permissions.fullDiskAccess === false ? "warning" : undefined}>
          {snapshot.permissions.fullDiskAccess === null ? "FDA unknown" : snapshot.permissions.fullDiskAccess ? "FDA granted" : "FDA missing"}
        </Badge>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-(--iux-muted-foreground)">Found</dt>
          <dd className="tabular-nums" dir="ltr">{snapshot.lastScan ? `${snapshot.lastScan.foundItems} items` : "—"}</dd></div>
        <div><dt className="text-xs text-(--iux-muted-foreground)">Reclaimable</dt>
          <dd className="tabular-nums" dir="ltr">{snapshot.lastScan ? formatBytes(snapshot.lastScan.foundBytes) : "—"}</dd></div>
        <div><dt className="text-xs text-(--iux-muted-foreground)">Disk free</dt>
          <dd className="tabular-nums" dir="ltr">{formatBytes(snapshot.disk.freeBytes)}</dd></div>
        <div><dt className="text-xs text-(--iux-muted-foreground)">Total reclaimed</dt>
          <dd className="tabular-nums" dir="ltr">{formatBytes(snapshot.cleanup.totalReclaimedBytes)}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-(--iux-muted-foreground)">
        {snapshot.lastScan?.finishedAt ? `Last scan ${relative(snapshot.lastScan.finishedAt, "—")} · ` : "No scan recorded · "}
        {snapshot.cleanup.lastRunAt ? `last cleanup ${relative(snapshot.cleanup.lastRunAt, "—")} · ` : "no cleanup yet · "}
        {snapshot.monitor.enabled && snapshot.monitor.nextCheckAt ? `next monitor check ${relative(snapshot.monitor.nextCheckAt, "—")}` : "no monitor check scheduled"}
        {snapshot.progress && ` · progress ${snapshot.progress.done}/${snapshot.progress.total}`}
        {` · ${snapshot.bookmarks.count} bookmarks (${snapshot.bookmarks.quickCleanCount} quick)`}
      </p>
    </div>}
    </details>
    {!valid && <Empty>The widget snapshot appears after the first publish.</Empty>}
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-(--iux-muted-foreground)">Adding the widget</summary>
      <ul className="mt-1 list-disc space-y-1 ps-5 text-xs text-(--iux-muted-foreground)">
        <li>Open Notification Center (click the date and time), scroll down and choose <strong>Edit Widgets</strong>.</li>
        <li>Find <strong>os-lab</strong> and add the small, medium or large size. Desktop placement works the same way.</li>
        <li>Rows are tappable: they open this dashboard on the matching page, and the widget's quick-clean button reviews a Trash-only plan of your quick-clean bookmarks here.</li>
      </ul>
    </details>
  </Section>;
}
