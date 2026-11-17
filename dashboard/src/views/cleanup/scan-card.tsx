/**
 * The Dashboard scan card: while a scan runs it shows "Scanning your Mac" with a percentage, bar,
 * current path and Stop; once finished it shows "Scan complete" with the selected size, a Clean
 * action and the cleanup plan by catalog group. Each plan row opens that group's own page.
 * Display and routing only: Clean opens the existing plan → confirm flow.
 */
import { BroomIcon, CaretRightIcon, TrashIcon } from "@phosphor-icons/react";
import { formatBytes, type CleanupEntry, type CleanupJob } from "../../lib/api";
import { CATALOG_GROUPS, groupIdOf } from "./groups";
import { GroupTile } from "./group-icon";
import { Section } from "../../components/ui";

export type ScanCardProps = {
  active: CleanupJob | null;
  entries: CleanupEntry[];
  measured: Map<string, number>;
  checked: string[];
  setChecked: (ids: string[]) => void;
  canWork: boolean;
  scanned: boolean;
  onScan: () => void;
  onCancel: () => void;
  onClean: (ids: string[]) => void;
  groupHref: (groupId: string) => string;
  error?: string;
};

export function ScanCard(props: ScanCardProps) {
  const { active, entries, measured, checked, setChecked, canWork, scanned, onScan, onCancel, onClean, groupHref, error } = props;
  const running = active?.state === "running" && active.kind === "scan";
  const done = Number(active?.progress?.pathsDone ?? active?.progress?.itemsDone ?? 0);
  const total = Number(active?.progress?.pathsTotal ?? active?.progress?.itemsTotal ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  if (running) {
    return <Section id="overview-review" title="Scanning your Mac" action={<span dir="ltr" className="text-xl font-semibold tabular-nums" aria-live="polite">{percent}%</span>}
      description={String(active?.progress?.currentEntry || "Preparing…")}>
      <div className="h-1.5 overflow-hidden rounded-full bg-(--iux-muted)" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <span className="block h-full rounded-full bg-[#2f9e91] transition-[width]" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-3 truncate text-xs text-(--iux-muted-foreground)" dir="ltr" translate="no" title={String(active?.progress?.currentPath ?? "")}>{String(active?.progress?.currentPath ?? "…")}</p>
      <div className="mt-3 flex items-center gap-3">
        <button type="button" className="iux-btn" onClick={onCancel}>Stop scan</button>
        <span className="text-xs text-(--iux-muted-foreground)">Stopping keeps the results found so far.</span>
      </div>
    </Section>;
  }
  const rows = CATALOG_GROUPS.map((group) => {
    const items = entries.filter((entry) => groupIdOf(entry.id) === group.id && (measured.get(entry.id) ?? 0) > 0);
    return { group, items, bytes: items.reduce((sum, entry) => sum + (measured.get(entry.id) ?? 0), 0) };
  }).filter((row) => row.items.length).sort((a, b) => b.bytes - a.bytes);
  if (!scanned || !rows.length) {
    return <Section id="overview-review" title="Clean" description="Scan the safe categories, review the plan, then confirm. Nothing is removed during a scan.">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-(--iux-muted-foreground)">{canWork ? "Ready to scan" : "Scan unavailable until setup is complete"} · {entries.length} categories available</p>
        <button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !entries.length} onClick={onScan}>{scanned ? "Scan again" : "Scan now"}</button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-(--iux-danger)">{error}</p>}
    </Section>;
  }
  const found = rows.reduce((sum, row) => sum + row.bytes, 0);
  const rowIds = (ids: string[]) => ids.filter((id) => checked.includes(id));
  const selectedBytes = rows.reduce((sum, row) => sum + row.items.filter((entry) => checked.includes(entry.id)).reduce((s, entry) => s + (measured.get(entry.id) ?? 0), 0), 0);
  const cleanIds = rows.flatMap((row) => rowIds(row.items.filter((entry) => entry.cleanable !== false && !entry.needsPrivilege && !["high", "credentials", "privacy"].includes(entry.risk)).map((entry) => entry.id)));
  return <Section id="overview-review" title="Scan complete" description={`${formatBytes(found)} found across ${rows.length} categories.`}
    action={<span className="flex items-center gap-3">
      <span className="text-end"><span className="block text-[11px] text-(--iux-muted-foreground)">Selected</span><span dir="ltr" className="text-xl font-semibold tabular-nums">{formatBytes(selectedBytes)}</span></span>
      <button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !cleanIds.length} onClick={() => onClean(cleanIds)}>
        <TrashIcon size={14} />Clean {formatBytes(selectedBytes)}
      </button>
    </span>}>
    <div className="flex items-center justify-between">
      <h3 className="text-sm font-semibold">Cleanup plan</h3>
      <button type="button" className="iux-btn" data-variant="ghost" disabled={!canWork} onClick={onScan}><BroomIcon size={13} />Scan again</button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-(--iux-danger)">{error}</p>}
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
            <CaretRightIcon size={14} aria-hidden="true" />
          </a>
        </li>;
      })}
    </ul>
    <p className="mt-2 text-xs text-(--iux-muted-foreground)">Open a category to review individual items. Measured-only, privileged and high-risk items are never cleaned from here.</p>
  </Section>;
}
