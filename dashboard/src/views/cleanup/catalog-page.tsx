/**
 * The Catalogs page: every catalog entry classified by tool group. Without a selected group it
 * lists the groups (entries, measured size); with one it is that group's own view — search, sort,
 * per-item select and bookmark, Rescan, and a footer that sends the selection to the existing
 * plan → confirm dialog ("Review removal"). Nothing here removes files by itself.
 */
import { useMemo, useState } from "react";
import { ArrowClockwiseIcon, CaretRightIcon, MagnifyingGlassIcon, TrashIcon } from "@phosphor-icons/react";
import { Badge, Section } from "../../components/ui";
import { formatBytes, type CleanupEntry } from "../../lib/api";
import { BookmarkToggle } from "./bookmarks-card";
import { CATALOG_GROUPS, groupIdOf } from "./groups";

export type CatalogPageProps = {
  entries: CleanupEntry[];
  sizes: Map<string, number>;
  groupId: string;
  groupHref: (groupId: string) => string;
  selected: string[];
  setSelected: (ids: string[]) => void;
  busy: boolean;
  canWork: boolean;
  isPublic: boolean;
  bookmarkedIds: Set<string>;
  onBookmark: (entryId: string) => void;
  onScan: (ids: string[]) => void;
  onReview: (ids: string[]) => void;
};

const riskTone = (risk: string) => risk === "low" || risk === "safe" ? "success" : risk === "medium" ? "warning" : "danger";

export function CatalogPage(props: CatalogPageProps) {
  const { entries, sizes, groupId, groupHref, selected, setSelected, busy, canWork, isPublic, bookmarkedIds, onBookmark, onScan, onReview } = props;
  const [query, setQuery] = useState("");
  const [order, setOrder] = useState<"size" | "name">("size");
  const group = CATALOG_GROUPS.find((item) => item.id === groupId);
  const inGroup = useMemo(() => group ? entries.filter((entry) => groupIdOf(entry.id) === group.id) : [], [entries, group]);
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = inGroup.filter((entry) => !needle || entry.name.toLowerCase().includes(needle) || entry.paths.some((path) => path.path?.toLowerCase().includes(needle)));
    return rows.sort((a, b) => order === "name" ? a.name.localeCompare(b.name) : (sizes.get(b.id) ?? -1) - (sizes.get(a.id) ?? -1));
  }, [inGroup, query, order, sizes]);

  if (!group) {
    return <Section id="catalog-groups" title="Catalogs" description="Every cleanup entry, classified by tool. Open one to see all its options.">
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {CATALOG_GROUPS.map((item) => {
          const rows = entries.filter((entry) => groupIdOf(entry.id) === item.id);
          if (!rows.length) return null;
          const found = rows.reduce((sum, entry) => sum + (sizes.get(entry.id) ?? 0), 0);
          return <li key={item.id}><a href={groupHref(item.id)} className="flex items-center gap-2 rounded-md border border-(--iux-border) p-3 no-underline hover:bg-(--iux-muted)">
            <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{item.label}</span>
              <span className="block truncate text-xs text-(--iux-muted-foreground)">{rows.length} entries · {item.hint}</span></span>
            <span dir="ltr" className="text-sm tabular-nums">{found > 0 ? formatBytes(found) : "—"}</span>
            <CaretRightIcon size={14} aria-hidden="true" />
          </a></li>;
        })}
      </ul>
    </Section>;
  }

  const ids = inGroup.map((entry) => entry.id);
  const picked = selected.filter((id) => ids.includes(id));
  const pickedBytes = picked.reduce((sum, id) => sum + (sizes.get(id) ?? 0), 0);
  const found = inGroup.reduce((sum, entry) => sum + (sizes.get(entry.id) ?? 0), 0);
  const blocked = (entry: CleanupEntry) => entry.cleanable === false || entry.needsPrivilege;
  const reviewable = picked.filter((id) => { const entry = inGroup.find((row) => row.id === id); return entry && !blocked(entry); });
  return <section id={`catalog-${group.id}`} className="iux-card overflow-hidden rounded-lg border border-(--iux-border)" aria-label={group.label}>
    <header className="flex flex-wrap items-start gap-3 p-4">
      <div className="min-w-0 flex-1">
        <a href={groupHref("")} className="text-xs text-(--iux-muted-foreground)">← All catalogs</a>
        <h2 className="text-xl font-semibold">{group.label}</h2>
        <p className="text-sm text-(--iux-muted-foreground)">{group.hint}</p>
        <p className="text-sm text-(--iux-muted-foreground)"><span dir="ltr" className="tabular-nums">{inGroup.length} items · {formatBytes(found)} found</span></p>
      </div>
      <button type="button" className="iux-btn" disabled={!canWork} onClick={() => onScan(ids)}><ArrowClockwiseIcon size={14} />Rescan</button>
    </header>
    <div className="flex flex-wrap items-center gap-3 border-t border-(--iux-border) px-4 py-2">
      <label className="flex min-w-48 flex-1 items-center gap-2 rounded-md bg-(--iux-muted) px-2 py-1.5">
        <MagnifyingGlassIcon size={14} aria-hidden="true" />
        <input className="w-full bg-transparent text-sm outline-none" placeholder="Find an item or path" value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <label className="text-sm">Sort <select className="iux-input" value={order} onChange={(event) => setOrder(event.target.value as "size" | "name")}><option value="size">Largest first</option><option value="name">Name</option></select></label>
      <button type="button" className="iux-btn" data-variant="ghost" onClick={() => setSelected([...new Set([...selected, ...shown.filter((entry) => !blocked(entry)).map((entry) => entry.id)])])}>Select visible</button>
      <span className="text-xs text-(--iux-muted-foreground)">{shown.length} of {inGroup.length} shown</span>
    </div>
    <ul className="divide-y divide-(--iux-border) border-t border-(--iux-border)">
      {shown.map((entry) => {
        const size = sizes.get(entry.id);
        const path = entry.paths.find((row) => row.path)?.path;
        return <li key={entry.id} className="flex items-center gap-3 px-4 py-2.5">
          <input type="checkbox" className="size-4 accent-[#f36c21]" aria-label={`Select ${entry.name}`} checked={selected.includes(entry.id)} disabled={busy}
            onChange={(event) => setSelected(event.target.checked ? [...selected, entry.id] : selected.filter((id) => id !== entry.id))} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{entry.name}</p>
            <p className="truncate text-xs text-(--iux-muted-foreground)" dir="ltr" translate="no" title={path ?? undefined}>{blocked(entry) ? "Measured only · " : ""}{path ?? entry.id}</p>
          </div>
          <Badge tone={riskTone(entry.risk)}>{entry.risk}</Badge>
          {!isPublic && <BookmarkToggle entryId={entry.id} bookmarked={bookmarkedIds.has(entry.id)} busy={busy} onToggle={onBookmark} />}
          <span dir="ltr" className="w-20 text-end text-sm font-semibold tabular-nums">{size != null ? formatBytes(size) : "—"}</span>
        </li>;
      })}
      {!shown.length && <li className="px-4 py-6 text-center text-sm text-(--iux-muted-foreground)">Nothing matches.</li>}
    </ul>
    <footer className="sticky bottom-0 flex flex-wrap items-center gap-3 border-t border-(--iux-border) bg-(--iux-card) px-4 py-3">
      <span className="text-sm"><b>{picked.length}</b> selected · <span dir="ltr" className="tabular-nums">{formatBytes(pickedBytes)}</span></span>
      <span className="text-xs text-(--iux-muted-foreground)">Cleanup moves files to Trash unless you choose permanent delete.</span>
      <span className="ms-auto flex gap-2">
        <button type="button" className="iux-btn" data-variant="ghost" disabled={!picked.length} onClick={() => setSelected(selected.filter((id) => !ids.includes(id)))}>Clear selection</button>
        <button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !reviewable.length} onClick={() => onReview(reviewable)}><TrashIcon size={14} />Review removal</button>
      </span>
    </footer>
  </section>;
}
