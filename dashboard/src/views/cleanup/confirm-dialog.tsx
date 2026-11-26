import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { CheckCircleIcon, PauseCircleIcon, TrashIcon, WarningIcon, XIcon } from "@phosphor-icons/react";
import { Empty, Status, keepModalFocus } from "../../components/ui";
import type { CleanupJob, CleanupPlan, CleanupResult } from "../../lib/api";
import { bytes, itemStatusLabel } from "./format";

export const PathSource = ({ source }: { source?: string }) => <span className="text-(--iux-muted-foreground)">Source: <code translate="no">{source || "catalog"}</code></span>;

type PlanItem = CleanupPlan["items"][number];

/** Skipped items that share a name and a reason collapse into one row with a count. */
function groupSkipped(items: PlanItem[]) {
  const groups = new Map<string, { item: PlanItem; reason: string; count: number }>();
  for (const item of items) {
    const reason = item.reason || itemStatusLabel(item.status);
    const key = `${item.entryName}\u0000${reason}`;
    const group = groups.get(key);
    if (group) group.count += 1;
    else groups.set(key, { item, reason, count: 1 });
  }
  return [...groups.values()];
}

/** One bento tile: a bordered card with an optional heading row. */
function Tile({ className = "", title, aside, children }: { className?: string; title?: string; aside?: ReactNode; children: ReactNode }) {
  return <section className={`flex min-w-0 flex-col rounded-xl border border-(--iux-border) bg-(--iux-card) p-4 ${className}`}>
    {title && <div className="mb-2 flex items-center gap-2">
      <h3 className="min-w-0 flex-1 truncate text-xs font-medium uppercase tracking-wide text-(--iux-muted-foreground)">{title}</h3>
      {aside}
    </div>}
    {children}
  </section>;
}

/**
 * Plan confirmation: a near full-screen dialog with focus containment. A fixed
 * header and action bar frame a scrolling bento grid of the plan summary, the
 * items that will be cleaned and the items that will be left alone. The dialog
 * stays open through verify and clean so a long run has visible progress.
 */
export function ConfirmDialog({
  plan, planUsed, now, busy, error, job, result, onRun, onClose, onCancel, onChangeMode
}: {
  plan: CleanupPlan; planUsed: boolean; now: number; busy: boolean; error: string;
  job?: CleanupJob | null; result?: CleanupResult | null;
  onRun: () => void; onClose: () => void; onCancel?: () => void;
  onChangeMode?: (mode: "trash" | "delete") => void;
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
  const ready = useMemo(() => plan.items.filter((item) => item.status === "ready").sort((a, b) => b.sizeBytes - a.sizeBytes), [plan]);
  const skipped = useMemo(() => groupSkipped(plan.items.filter((item) => item.status !== "ready")), [plan]);
  const skippedCount = plan.items.length - ready.length;
  const largest = ready[0]?.sizeBytes ?? 0;
  const expired = plan.expiresAt <= now;
  const running = job?.state === "running";
  const planning = running && job?.kind === "plan";
  const cleaning = running && job?.kind === "clean";
  const failed = job?.state === "failed" && (job.kind === "clean" || job.kind === "plan");
  const done = !!result && result.planId === plan.planId && (job?.kind === "clean" ? job.state !== "running" : true);
  const blocked = expired || planUsed || !ready.length || busy || running || done;
  // A plan that failed, ran or timed out can never run again, so offer its replacement.
  const stale = !done && !running && (failed || expired || planUsed);
  const trash = plan.mode === "trash";
  const phase = String(job?.progress?.phase ?? (planning ? "planning" : "verifying"));
  const doneCount = Number(job?.progress?.itemsDone ?? job?.progress?.pathsDone ?? 0);
  const totalCount = Number(job?.progress?.itemsTotal ?? job?.progress?.pathsTotal ?? 0);
  const percent = totalCount > 0 ? Math.min(100, Math.round((doneCount / totalCount) * 100)) : 0;
  const currentPath = String(job?.progress?.currentPath ?? "");
  const working = planning || cleaning;

  return <dialog ref={box} tabIndex={-1} aria-labelledby="cleanup-confirm-title"
    className="iux-dialog m-auto h-dvh w-full flex-col overflow-y-auto open:flex sm:h-[calc(100dvh-3rem)] sm:w-[calc(100%-3rem)] sm:max-w-6xl sm:rounded-2xl"
    onCancel={(event) => { if (working) event.preventDefault(); }}
    onClose={() => { if (!working) onClose(); }} onKeyDown={keepModalFocus}
    onMouseDown={(event) => {
      if (working) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
        event.preventDefault();
        onClose();
      }
    }}>
    <header className="flex shrink-0 items-start gap-3 border-b border-(--iux-border) px-5 py-4">
      <div className="min-w-0 flex-1">
        <h2 id="cleanup-confirm-title" className="text-base font-semibold">Confirm cleanup</h2>
        <p className="mt-0.5 text-xs text-(--iux-muted-foreground)">Review what will be removed before running.</p>
      </div>
      <button type="button" className="iux-btn" data-variant="ghost" aria-label="Close" title="Close" onClick={onClose} disabled={working}>
        <XIcon size={16} aria-hidden="true" />
      </button>
    </header>

    <div className="iux-scroll min-h-32 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile className="col-span-2 justify-between md:row-span-2">
          <p className="text-xs font-medium uppercase tracking-wide text-(--iux-muted-foreground)">{trash ? "Size to move to Trash" : "Space to free"}</p>
          <p dir="ltr" className="mt-3 text-4xl font-semibold tabular-nums sm:text-5xl">{bytes(plan.totals.bytes)}</p>
          <p className="mt-3 text-sm"><span dir="ltr" className="font-semibold tabular-nums">{plan.totals.ready}</span> <span>items</span></p>
        </Tile>
        <Tile>
          <span className="text-(--iux-success)"><CheckCircleIcon size={20} aria-hidden="true" /></span>
          <p dir="ltr" className="mt-2 text-2xl font-semibold tabular-nums">{ready.length}</p>
          <p className="text-xs text-(--iux-muted-foreground)">Ready</p>
        </Tile>
        <Tile>
          <span className="text-(--iux-muted-foreground)"><PauseCircleIcon size={20} aria-hidden="true" /></span>
          <p dir="ltr" className="mt-2 text-2xl font-semibold tabular-nums">{skippedCount}</p>
          <p className="text-xs text-(--iux-muted-foreground)">Skipped</p>
        </Tile>
        <Tile className={`col-span-2 ${trash ? "" : "border-(--iux-danger)/50 bg-(--iux-danger)/5"}`}>
          <div className="flex items-center gap-3">
            <span className={trash ? "text-[#f36c21]" : "text-(--iux-danger)"}>
              {trash ? <TrashIcon size={22} aria-hidden="true" /> : <WarningIcon size={22} aria-hidden="true" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{trash ? "Move to Trash" : "Delete permanently"}</p>
              {trash ? <p className="text-xs text-(--iux-muted-foreground)">Items can be restored from the Trash.</p>
                : <p className="text-xs text-(--iux-danger)">Deleting permanently cannot be undone.</p>}
              {onChangeMode && !working && !done && <button type="button" className="iux-btn mt-2" data-variant="ghost" disabled={busy}
                onClick={() => onChangeMode(trash ? "delete" : "trash")}>
                {trash ? "Delete permanently instead" : "Use Trash instead"}
              </button>}
            </div>
          </div>
        </Tile>

        {working && <Tile className="col-span-2 md:col-span-4" title={planning ? "Building the plan" : phase === "verifying" ? "Checking the plan" : trash ? "Moving to Trash" : "Deleting permanently"}>
          <div className="h-1.5 overflow-hidden rounded-full bg-(--iux-muted)" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Cleanup progress">
            <span className="block h-full rounded-full bg-[#f36c21] transition-[width]" style={{ width: `${percent}%` }} />
          </div>
          <p className="mt-2 text-sm" role="status" aria-live="polite">
            <span dir="ltr" className="tabular-nums">{totalCount ? `${percent}% · ${doneCount} / ${totalCount}` : "Starting…"}</span>
            {phase === "verifying" && <span className="text-(--iux-muted-foreground)"> · nothing has been moved yet</span>}
          </p>
          {currentPath && <p className="mt-1 truncate text-xs text-(--iux-muted-foreground)" dir="ltr" translate="no" title={currentPath}>{currentPath}</p>}
        </Tile>}

        {done && result && <Tile className="col-span-2 md:col-span-4" title="Clean finished">
          <p className="text-sm">
            <span dir="ltr" className="font-semibold tabular-nums">{bytes(result.totals.bytes)}</span>
            {result.mode === "trash" ? " moved to Trash, not yet freed." : " deleted permanently."}
          </p>
          <p className="mt-1 text-xs text-(--iux-muted-foreground)">
            {result.totals.trashed ? `${result.totals.trashed} trashed` : ""}{result.totals.deleted ? `${result.totals.trashed ? " · " : ""}${result.totals.deleted} deleted` : ""}
            {result.totals.skipped ? ` · ${result.totals.skipped} skipped` : ""}{result.totals.failed ? ` · ${result.totals.failed} failed` : ""}
          </p>
        </Tile>}

        <Tile title="Ready to clean" className={`col-span-2 ${skipped.length ? "" : "md:col-span-4"}`}
          aside={<span dir="ltr" className="text-xs tabular-nums text-(--iux-muted-foreground)">{bytes(plan.totals.bytes)}</span>}>
          {ready.length ? <ul className="-mx-1 divide-y divide-(--iux-border)">
            {ready.map((item, index) => <li key={`${item.entryId}-${index}`} className="px-1 py-2.5 text-sm">
              <div className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate font-medium">{item.entryName}</span>
                <span dir="ltr" className="shrink-0 tabular-nums">{bytes(item.sizeBytes)}</span>
              </div>
              {largest > 0 && item.sizeBytes > 0 && <span aria-hidden="true" className="mt-1.5 block h-1 overflow-hidden rounded-full bg-(--iux-muted)">
                <span className="block h-full rounded-full bg-[#f36c21]" style={{ width: `${Math.max(2, Math.round((item.sizeBytes / largest) * 100))}%` }} />
              </span>}
              <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no" dir="ltr">{item.path}</p>
              <p className="text-xs"><PathSource source={item.source} /></p>
              {item.liveContent && <p className="text-xs text-(--iux-muted-foreground)">Apps keep writing here. Whatever is inside when the clean runs is removed.</p>}
            </li>)}
          </ul> : <Empty>Nothing is ready to clean.</Empty>}
        </Tile>

        {skipped.length > 0 && <Tile title="Skipped" className="col-span-2"
          aside={<span dir="ltr" className="text-xs tabular-nums text-(--iux-muted-foreground)">{skippedCount}</span>}>
          <ul className="-mx-1 divide-y divide-(--iux-border)">
            {skipped.map(({ item, reason, count }, index) => <li key={`${item.entryId}-${index}`} className="flex items-start gap-2 px-1 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{item.entryName}</p>
                <p className="break-words text-xs text-(--iux-muted-foreground)">{reason}</p>
              </div>
              {count > 1 && <span dir="ltr" className="iux-badge shrink-0 tabular-nums" data-variant="secondary">×{count}</span>}
            </li>)}
          </ul>
        </Tile>}
      </div>
    </div>

    <footer className="flex shrink-0 flex-wrap items-center gap-3 border-t border-(--iux-border) px-5 py-3">
      <div className="min-w-0 flex-1 text-sm">
        {error || (failed && job?.error) ? <Status value={{ ok: false, text: error || job?.error || "The cleanup job failed." }} />
          : working ? <p className="text-xs text-(--iux-muted-foreground)">{phase === "verifying" ? "Re-checking every path. Finder Trash stays empty until this finishes." : "Working through the plan."}</p>
          : done ? <p className="text-xs text-(--iux-muted-foreground)">Items on other volumes go to that volume's Trash, not always the Dock one.</p>
          : planUsed ? <p>This plan was already run. Build a new plan.</p>
          : expired ? <p>This plan expired. Build a new plan.</p>
          : <p className="text-xs text-(--iux-muted-foreground)">expires in {Math.max(0, Math.ceil(plan.expiresAt - now))} seconds</p>}
      </div>
      {working ? <button type="button" className="iux-btn" onClick={onCancel} disabled={!onCancel}>Stop</button>
        : <button type="button" className="iux-btn" onClick={onClose}>{done || failed ? "Close" : "Back"}</button>}
      {stale && onChangeMode ? <button type="button" className="iux-btn" data-variant="primary" disabled={busy} onClick={() => onChangeMode(plan.mode)}>Build a new plan</button>
        : !done && <button type="button" className="iux-btn" data-variant="primary" disabled={blocked} onClick={onRun}>Run clean</button>}
    </footer>
  </dialog>;
}
