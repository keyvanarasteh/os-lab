import { useEffect, useMemo, useRef, useState } from "react";
import { BroomIcon } from "@phosphor-icons/react";
import { AppShell } from "../../shell/app-shell";
import { TopBar } from "../../shell/top-bar";
import { Badge, Empty, PageHead, Section, Status } from "../../components/ui";
import { api, usePoll, type CleanupEntry, type CleanupHistory, type CleanupJob, type CleanupMonitorStatus, type CleanupPermissions, type CleanupPermission, type CleanupPlan, type CleanupResult, type CleanupScan, type CleanupStatus } from "../../lib/api";
import { localeFromPath, localePath } from "../../i18n/paths";
import { keepModalFocus } from "../modal-focus";
import { InfoPopover } from "./info-popover";
import { CategoryIcon, PrivilegeMarker, StatusIcon } from "./icons";
import { bytes, itemStatusLabel, riskLabel, riskTone, sortEntries, totalsByRisk, type SortOrder } from "./format";
import { CleanupExtraTools } from "./extra-tools";
import { CrossPlatformLeftovers } from "./cross-leftovers";
import { MonitorBanner, MonitorCard, MonitorStatsCard } from "./monitor-card";
import { BookmarkToggle, BookmarksSection } from "./bookmarks-card";
import { OverviewCards, StorageHero, type OverviewCard } from "./overview";
import { SpaceExplorer } from "./space-explorer";
import { RelocationCard } from "./relocation-card";
import { WidgetsCard } from "./widgets-card";
import type { BookmarksPayload, CleanupVolume, CleanupWidgetSnapshot } from "../../lib/api";

/**
 * CLW-03: overview sections the desktop app's deep links may target, and the
 * tab that hosts each one since the settings split moved the cards (the
 * section ids stay stable for the desktop app and the widgets).
 */
const WIDGET_SECTIONS: Record<string, CleanupPageId> = {
  "cleanup-widgets": "settings",
  "cleanup-monitor": "",
  "cleanup-permissions": "settings",
  "cleanup-bookmarks": "settings",
  "overview-review": "",
  "overview-storage": ""
};

export type CleanupPageId = "" | "settings" | "scan" | "results" | "leftovers" | "history" | "space" | "relocation";
export const CLEANUP_PAGES: CleanupPageId[] = ["", "settings", "scan", "results", "leftovers", "history", "space", "relocation"];
/** Any `/cleanup` route for any locale or base path, at the end of a pathname. */
const CLEANUP_ROUTE = /\/cleanup(?:\/(settings|scan|results|leftovers|history|space|relocation))?\/?$/;

/**
 * CLNP-06: the cleanup route a pathname names, or null when it is not one.
 * Works for `/cleanup/scan/`, `/fa/cleanup/results/` and Public Pages base
 * paths alike — only the tail decides.
 */
export function parseCleanupPath(pathname: string): CleanupPageId | null {
  const match = CLEANUP_ROUTE.exec(pathname.replace(/\/+$/, "") + "/");
  if (!match) return null;
  const suffix = (match[1] ?? "") as CleanupPageId;
  return (CLEANUP_PAGES as string[]).includes(suffix) ? suffix : null;
}
const PUBLIC = import.meta.env.PUBLIC_SITE_MODE === "pages";
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const isScan = (job: CleanupJob): job is CleanupJob & { result: CleanupScan } => job.kind === "scan" && !!job.result;
const isPlan = (job: CleanupJob): job is CleanupJob & { result: CleanupPlan } => job.kind === "plan" && !!job.result;
const isClean = (job: CleanupJob): job is CleanupJob & { result: CleanupResult } => job.kind === "clean" && !!job.result;
const PathSource = ({ source }: { source?: string }) => <span className="text-(--iux-muted-foreground)">Source: <code translate="no">{source || "catalog"}</code></span>;

const CATEGORY_LABEL: Record<string, string> = { system: "System", browser: "Browsers", developer: "Developer" };
const CATEGORY_ORDER = ["system", "browser", "developer"];
const RISK_BAR: Record<string, string> = {
  low: "bg-(--iux-success)", medium: "bg-(--iux-warning)", high: "bg-(--iux-danger)",
  credentials: "bg-(--iux-violet)", privacy: "bg-(--iux-violet)"
};

/** Thin relative-size bar; the exact size is always shown as text next to it. */
function SizeBar({ value, max }: { value: number; max: number }) {
  if (max <= 0 || value <= 0) return null;
  return <span aria-hidden="true" className="block h-1 overflow-hidden rounded-full bg-(--iux-muted)">
    <span className="block h-full rounded-full bg-[#f36c21]" style={{ width: `${Math.round((value / max) * 100)}%` }} />
  </span>;
}

/** Catalog entry details: what it is, what cleaning changes, where paths resolve. */
function EntryDetails({ entry }: { entry: CleanupEntry }) {
  const resolvable = entry.paths.some((path) => path.path);
  return <>
    <p>{entry.hint}</p>
    {entry.impact && <>
      <p className="mt-2 text-xs font-medium text-(--iux-muted-foreground)">After cleaning</p>
      <p>{entry.impact}</p>
    </>}
    <p className="mt-2 text-xs font-medium text-(--iux-muted-foreground)">Paths</p>
    {resolvable ? entry.paths.map((path, index) => path.path
      ? <p key={index} className="break-all text-xs" translate="no">{path.path}</p>
      : <p key={index} className="text-xs text-(--iux-muted-foreground)">{path.reason}</p>)
      : <p className="text-xs text-(--iux-muted-foreground)">Unavailable on this system</p>}
    {entry.needsPrivilege && <p className="mt-2 text-xs">Requires administrator privileges</p>}
  </>;
}

/** Scan result details: counts and every measured path with its source. */
function ScanDetails({ item }: { item: CleanupScan["entries"][number] }) {
  return <>
    <p className="text-xs text-(--iux-muted-foreground)">{item.files} <span>files</span> · {item.folders} <span>folders</span></p>
    {item.unreadable.length > 0 && <p className="mt-1 text-xs text-(--iux-warning)">{item.unreadable.length} <span>unreadable paths</span></p>}
    <p className="mt-2 text-xs font-medium text-(--iux-muted-foreground)">Paths</p>
    {item.paths.map((path, index) => <div key={index} className="mt-1">
      <p className="break-all text-xs" translate="no">{path.path || path.reason}</p>
      <p className="text-xs"><PathSource source={path.source} /></p>
      {path.error && <p className="text-xs text-(--iux-danger)">{path.error}</p>}
    </div>)}
  </>;
}

/** CLNP-04: state chip wording and tone for one permission record. */
function permissionTone(granted: boolean | null): { label: string; tone: "success" | "danger" | undefined } {
  if (granted === true) return { label: "Granted", tone: "success" };
  if (granted === false) return { label: "Not granted", tone: "danger" };
  return { label: "No evidence yet", tone: undefined };
}

/**
 * The grant round-trip (the qLar lesson): the in-app page cannot open a
 * custom-scheme link — the webview swallows that navigation — so the button
 * names the permission and the console opens its fixed System Settings panes
 * (modern privacy extension first, legacy pane as fallback). Failures stay
 * inline on the record instead of disappearing.
 */
function GrantLink({ record }: { record: { id: string; grantUrl: string | null } }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const open = async () => {
    setBusy(true);
    setError("");
    try {
      await api.cleanupPermissionsOpen(record.id);
    } catch (openError) {
      setError(errorText(openError));
    } finally {
      setBusy(false);
    }
  };
  if (!record.grantUrl) return null;
  return <span className="ms-auto flex items-center gap-2">
    {error && <span className="text-xs text-(--iux-danger)" role="alert">{error}</span>}
    <button type="button" className="iux-btn text-xs" disabled={busy} onClick={() => void open()}>
      {busy ? "Opening…" : "Open System Settings"}
    </button>
  </span>;
}

/**
 * CLNP-04: the read-only permission card. Every record the engine reports as
 * applicable shows its state, probe results, grant guidance and the grant
 * button that hands the deep link to the console.
 */
function PermissionsCard({ permissions }: { permissions: CleanupPermissions | null }) {
  if (!permissions || !Array.isArray(permissions.permissions)) return null;
  const applicable = permissions.permissions.filter((record) => record && record.applicable);
  if (!applicable.length) return null;
  const classified = permissions.classification?.classified ?? [];
  return <Section id="cleanup-permissions" title="Permissions" description="What this computer lets the cleaner read, and how to grant more.">
    <div className="divide-y divide-(--iux-border)">
      {applicable.map((record) => <div key={record.id} className="py-3 first:pt-0 last:pb-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{record.name}</span>
          <Badge tone={permissionTone(record.granted).tone}>{permissionTone(record.granted).label}</Badge>
          <GrantLink record={record} />
        </div>
        {record.results.length > 0 && <div className="mt-1 space-y-0.5">
          {record.results.map((result, index) => <p key={index} className="break-all text-xs" translate="no">
            {result.path} <span className="text-(--iux-muted-foreground)">· {result.readable === false ? result.reason || "unreadable" : result.readable ? "readable" : result.reason}</span>
          </p>)}
        </div>}
        {record.guidance && <p className="mt-1 text-xs text-(--iux-muted-foreground)">{record.guidance}</p>}
      </div>)}
    </div>
    {classified.length > 0 && <div className="mt-3 rounded-md border border-(--iux-warning)/40 bg-(--iux-warning)/5 p-3 text-sm">
      <p className="font-medium">Items the latest scan could not read</p>
      {classified.map((item, index) => <p key={index} className="mt-1 break-all text-xs" translate="no">
        {item.path} <span className="text-(--iux-muted-foreground)">· needs {permissionName(item.permissionId, permissions)}</span>
      </p>)}
    </div>}
  </Section>;
}

function permissionName(id: string, permissions: CleanupPermissions): string {
  return permissions.permissions.find((record) => record.id === id)?.name ?? id;
}

/** Plan confirmation: a real dialog with focus containment, listing what will and will not be cleaned. */
function ConfirmDialog({
  plan, planUsed, now, busy, error, onRun, onClose
}: {
  plan: CleanupPlan; planUsed: boolean; now: number; busy: boolean; error: string;
  onRun: () => void; onClose: () => void;
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
  const ready = plan.items.filter((item) => item.status === "ready");
  const skipped = plan.items.filter((item) => item.status !== "ready");
  const expired = plan.expiresAt <= now;
  const blocked = expired || planUsed || !ready.length || busy;
  return <dialog ref={box} tabIndex={-1} aria-labelledby="cleanup-confirm-title"
    className="iux-dialog m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl p-5"
    onClose={onClose} onKeyDown={keepModalFocus}
    onMouseDown={(event) => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
        event.preventDefault();
        onClose();
      }
    }}>
    <h2 id="cleanup-confirm-title" className="text-sm font-semibold">Confirm cleanup</h2>
    <p className="mt-2 text-sm"><span dir="ltr" className="font-semibold tabular-nums">{plan.totals.ready}</span> <span>items</span> · <span dir="ltr" className="tabular-nums">{bytes(plan.totals.bytes)}</span></p>
    <p className="mt-1 text-sm font-medium">{plan.mode === "trash" ? "Move to Trash" : "Delete permanently"}</p>
    {plan.mode === "delete" && <p className="mt-1 text-xs text-(--iux-danger)">Deleting permanently cannot be undone.</p>}
    {ready.length ? <div className="iux-scroll mt-3 max-h-56 divide-y divide-(--iux-border) overflow-auto rounded-md border border-(--iux-border)">
      {ready.map((item, index) => <div key={`${item.entryId}-${index}`} className="px-3 py-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate font-medium">{item.entryName}</span>
          <span dir="ltr" className="tabular-nums">{bytes(item.sizeBytes)}</span>
        </div>
        <p className="break-all text-xs text-(--iux-muted-foreground)" translate="no">{item.path}</p>
        <PathSource source={item.source} />
      </div>)}
    </div> : <div className="mt-3"><Empty>Nothing is ready to clean.</Empty></div>}
    {skipped.length > 0 && <div className="mt-3 text-sm">
      <p className="text-xs font-medium text-(--iux-muted-foreground)">Skipped</p>
      {skipped.map((item, index) => <div key={`${item.entryId}-${index}`} className="mt-1 flex gap-2">
        <span className="mt-0.5"><StatusIcon status={item.status} /></span>
        <div className="min-w-0">
          <p className="truncate font-medium">{item.entryName}</p>
          <p className="text-xs text-(--iux-muted-foreground)">{item.reason || itemStatusLabel(item.status)}</p>
        </div>
      </div>)}
    </div>}
    {planUsed ? <p className="mt-3 text-sm">This plan was already run. Build a new plan.</p>
      : expired ? <p className="mt-3 text-sm">This plan expired. Build a new plan.</p>
      : <p className="mt-3 text-xs text-(--iux-muted-foreground)">expires in {Math.max(0, Math.ceil(plan.expiresAt - now))} seconds</p>}
    {error && <Status value={{ ok: false, text: error }} />}
    <div className="mt-4 flex gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={blocked} onClick={onRun}>Run clean</button>
      <button type="button" className="iux-btn" onClick={onClose}>Back</button>
    </div>
  </dialog>;
}

/**
 * The main dashboard's Quick clean card: the bookmarks flagged for quick
 * cleanup, one confirmed Trash run over them. Bookmarks are managed on the
 * Settings tab; without any quick-clean bookmark the card says so instead of
 * pretending the button would do something.
 */
function QuickCleanCard({
  bookmarks, busy, canWork, measured, refusals, onQuickClean, settingsHref
}: {
  bookmarks: BookmarksPayload | null; busy: boolean; canWork: boolean;
  measured: Map<string, CleanupScan["entries"][number]>; refusals: string;
  onQuickClean: () => void; settingsHref: string;
}) {
  const items = bookmarks?.bookmarks ?? [];
  const quick = items.filter((item) => item.quickClean);
  const quickBytes = quick.reduce((sum, item) => sum + (measured.get(item.entryId)?.sizeBytes ?? 0), 0);
  const measuredQuick = quick.some((item) => measured.get(item.entryId)?.sizeBytes != null);
  return <Section id="overview-quick-clean" title="Quick clean" description="One confirmed Trash run over the bookmarks marked for quick cleanup.">
    <div className="flex items-baseline gap-2">
      <span dir="ltr" className="text-3xl font-bold tabular-nums">{measuredQuick ? bytes(quickBytes) : "—"}</span>
      <span className="text-sm text-(--iux-muted-foreground)">measured in quick-clean bookmarks</span>
    </div>
    <p className="text-sm text-(--iux-muted-foreground)">{quick.length} of {items.length} bookmarks included</p>
    {refusals && <Status value={{ ok: false, text: refusals }} />}
    <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !quick.length || busy} onClick={onQuickClean}>Quick clean</button>
      <a className="iux-btn" href={settingsHref}>Manage bookmarks</a>
    </div>
    {items.length === 0 ? <p className="mt-2 text-xs text-(--iux-muted-foreground)">No bookmarks yet — bookmark entries on the Advanced scan page or add folders in Settings.</p>
      : quick.length === 0 ? <p className="mt-2 text-xs text-(--iux-muted-foreground)">No bookmarks are marked for quick clean yet — enable quick clean in Settings.</p> : null}
  </Section>;
}

export default function CleanupPage({ page: initialPage = "" }: { page?: CleanupPageId }) {
  // CLNP-06: the active page is live state, derived from the URL. The prop
  // stays as the SSR/deep-link seed; navigation updates the state in place.
  const [page, setPage] = useState<CleanupPageId>(initialPage);
  const [status, setStatus] = useState<CleanupStatus | null>(null);
  const [entries, setEntries] = useState<CleanupEntry[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [jobs, setJobs] = useState<CleanupJob[]>([]);
  const [active, setActive] = useState<CleanupJob | null>(null);
  const [history, setHistory] = useState<CleanupHistory | null>(null);
  const [permissions, setPermissions] = useState<CleanupPermissions | null>(null);
  const [bookmarks, setBookmarks] = useState<BookmarksPayload | null>(null);
  const [widget, setWidget] = useState<CleanupWidgetSnapshot | null>(null);
  const [loading, setLoading] = useState(!PUBLIC);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<"trash" | "delete">("trash");
  const [preset, setPreset] = useState<"recommended" | "extended">("recommended");
  const [confirm, setConfirm] = useState(false);
  const [bookmarkConfirm, setBookmarkConfirm] = useState(false);
  const [quickRefusals, setQuickRefusals] = useState("");
  const [order, setOrder] = useState<SortOrder>("size");
  const [now, setNow] = useState(Date.now() / 1000);
  const coreLoaded = useRef(false);
  const locale = typeof window === "undefined" ? "en" : localeFromPath(window.location.pathname);
  const link = (suffix: string) => localePath(`/cleanup/${suffix}`, locale);

  // CLNP-11: the monitor state is shared by the banner and the card. One
  // fetch on mount (PUBLIC resolves to null without any request), then a
  // light 15 s poll only while the runner is enabled — intervalMs 0 means
  // "fetch on mount and on reload", never a timer.
  const { data: monitorOnce, reload: reloadMonitorOnce } = usePoll<CleanupMonitorStatus | null>(
    () => PUBLIC ? Promise.resolve(null) : api.cleanupMonitor(), 0
  );
  const monitorEnabled = monitorOnce?.enabled === true;
  const { data: monitorLive, reload: reloadMonitorLive } = usePoll<CleanupMonitorStatus | null>(
    () => PUBLIC ? Promise.resolve(null) : api.cleanupMonitor(), monitorEnabled ? 15000 : 0
  );
  const monitor = monitorLive ?? monitorOnce ?? null;
  const monitorReload = () => { reloadMonitorOnce(); reloadMonitorLive(); };
  // CLNP-21/22: the storage hero and the monitor card share one volumes fetch.
  const { data: volumeReport, reload: reloadVolumes } = usePoll(
    () => PUBLIC ? Promise.resolve(null) : api.cleanupVolumes(), 0
  );
  const volumes: CleanupVolume[] | null = volumeReport?.volumes ?? null;

  useEffect(() => {
    if (typeof window !== "undefined") setPage(parseCleanupPath(window.location.pathname) ?? initialPage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // CLNP-06: back/forward re-derives the page from the URL the browser shows.
  useEffect(() => {
    const onPop = () => setPage(parseCleanupPath(window.location.pathname) ?? "");
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // CLNP-07: the core fetch runs once per island session, not per tab. The
  // permission probe is an optional capability: its failure degrades to a
  // hidden card instead of failing the whole load.
  useEffect(() => {
    if (PUBLIC || coreLoaded.current) return;
    coreLoaded.current = true;
    let alive = true;
    Promise.all([api.cleanupStatus(), api.cleanupCatalog(), api.cleanupJobs()])
      .then(([ready, catalog, recent]) => {
        if (!alive) return;
        setStatus(ready);
        setEntries(catalog.entries);
        setSelected(catalog.entries.filter((item) => item.defaultSelected && item.risk !== "credentials" && item.risk !== "privacy").map((item) => item.id));
        setJobs(recent.jobs);
      })
      .catch((error) => { if (alive) setLoadError(errorText(error)); })
      .finally(() => { if (alive) setLoading(false); });
    void api.cleanupPermissions()
      .then((grants) => { if (alive) setPermissions(grants); })
      .catch(() => { if (alive) setPermissions(null); });
    void api.cleanupBookmarks()
      .then((payload) => { if (alive) setBookmarks(payload); })
      .catch(() => { if (alive) setBookmarks(null); });
    // CLW-10: the widget snapshot is an optional capability — its failure
    // degrades to an empty card instead of failing the whole load.
    void api.cleanupWidget()
      .then((snapshot) => { if (alive) setWidget(snapshot); })
      .catch(() => { if (alive) setWidget(null); });
    return () => { alive = false; };
  }, []);

  // The grant round-trip ends in System Settings, so re-probe the permission
  // records when this page regains focus — the state chips must flip without
  // a manual reload. The probes stay read-only (the FDA folders deny silently),
  // and a failure keeps the already-loaded card.
  useEffect(() => {
    if (PUBLIC) return;
    const reprobe = () => {
      if (document.visibilityState !== "visible") return;
      void api.cleanupPermissions().then(setPermissions).catch(() => {});
    };
    window.addEventListener("focus", reprobe);
    document.addEventListener("visibilitychange", reprobe);
    return () => {
      window.removeEventListener("focus", reprobe);
      document.removeEventListener("visibilitychange", reprobe);
    };
  }, []);

  const reloadBookmarks = () => { void api.cleanupBookmarks().then(setBookmarks).catch(() => {}); };
  const reloadWidget = () => { void api.cleanupWidget().then(setWidget).catch(() => {}); };
  const bookmarkedIds = new Set((bookmarks?.bookmarks ?? []).map((item) => item.entryId));

  /** Sections that moved with the settings split, and the tab hosting each. */
  const SECTION_PAGE: Record<string, CleanupPageId> = { "cleanup-monitor": "settings", "cleanup-permissions": "settings", "cleanup-widgets": "settings", "cleanup-bookmarks": "settings", "overview-review": "", "overview-storage": "" };

  /** CLNP-21: a capability card navigates a tab or its section, even when the section now lives on another tab. */
  function goCard(card: OverviewCard) {
    if (card.onTab) {
      navigateTo(card.target.replace("/", "") as CleanupPageId);
      return;
    }
    const targetPage = SECTION_PAGE[card.target] ?? page;
    if (targetPage !== page) navigateTo(targetPage);
    requestAnimationFrame(() => document.getElementById(card.target)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  /** CLNP-18: bookmark or unbookmark one catalog entry from any row. */
  function toggleBookmark(entryId: string) {
    if (bookmarkedIds.has(entryId)) {
      void api.cleanupBookmarkRemove(entryId).then(reloadBookmarks).catch((error) => setActionError(errorText(error)));
    } else {
      void api.cleanupBookmarkAdd(entryId).then(reloadBookmarks).catch((error) => setActionError(errorText(error)));
    }
  }

  /**
   * The quick-clean entry point (main card, deep links and the widget intent):
   * the engine plans the quick-clean bookmarks, the shared confirm dialog
   * opens on the returned plan job, and refusals stay visible on the card.
   */
  function runQuickClean() {
    setActionError(""); setQuickRefusals("");
    void api.cleanupBookmarkQuickClean()
      .then((response) => {
        setQuickRefusals(response.refusals.map((item) => item.reason).join(" "));
        setActive(response.job);
        setJobs((old) => [response.job, ...old.filter((row) => row.id !== response.job.id)]);
        setBookmarkConfirm(true);
      })
      .catch((error) => setActionError(errorText(error)));
  }

  // CLNP-07: live fetch per tab entry — jobs where results are shown, the
  // verified audit history on History. No idle polling; the job poller below
  // stays tied to a running job.
  useEffect(() => {
    if (PUBLIC) return;
    let alive = true;
    if (page === "history") {
      void api.cleanupHistory().then((value) => { if (alive) setHistory(value); })
        .catch((error) => { if (alive) setLoadError(errorText(error)); });
      return () => { alive = false; };
    }
    if (page === "" || page === "results" || page === "leftovers") {
      void api.cleanupJobs().then((recent) => { if (alive) setJobs(recent.jobs); })
        .catch(() => { if (alive) { /* keep the session's jobs */ } });
    }
    return () => { alive = false; };
  }, [page]);

  /** CLNP-06: one in-place navigation: URL, page state, scroll, dialog. */
  function navigateTo(next: CleanupPageId, pushUrl = true) {
    if (pushUrl && next !== page) window.history.pushState({}, "", link(next ? `${next}/` : ""));
    setPage(next);
    setConfirm(false);
    setBookmarkConfirm(false);
    window.scrollTo({ top: 0 });
  }

  /** CLNP-06: intercept plain left-clicks on cleanup anchors; others pass through. */
  function onNavClick(event: React.MouseEvent<HTMLElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest("a");
    if (!anchor || !anchor.href || anchor.getAttribute("href")?.startsWith("#")) return;
    const url = new URL(anchor.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const next = parseCleanupPath(url.pathname);
    if (next === null) return;
    event.preventDefault();
    navigateTo(next, url.pathname !== window.location.pathname);
  }

  // CLW-03: the desktop app drives these globals — oslab:// deep links land
  // as __oslabNavigate (a tab id like "scan/" or a section id) and the
  // widget's quick-clean intent lands as __oslabQuickClean, which follows
  // the same plan → confirm flow as the Bookmarks card's button.
  useEffect(() => {
    const host = window as unknown as {
      __oslabNavigate?: (route: string) => void;
      __oslabQuickClean?: () => void;
    };
    host.__oslabNavigate = (route: string) => {
      const id = route.replace(/\/+$/, "");
      const sectionPage = WIDGET_SECTIONS[id];
      if (sectionPage !== undefined) {
        if (page !== sectionPage) navigateTo(sectionPage);
        requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
        return;
      }
      navigateTo(id as CleanupPageId);
    };
    host.__oslabQuickClean = () => runQuickClean();
    // The closures must track the latest navigateTo/page state, so this runs
    // after every render instead of declaring dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

  useEffect(() => {
    if (!active || active.state !== "running") return;
    let alive = true;
    const timer = window.setInterval(() => {
      void api.cleanupJob(active.id).then((job) => {
        if (!alive) return;
        setActive(job);
        if (job.state !== "running") setJobs((old) => [job, ...old.filter((row) => row.id !== job.id)]);
      }).catch((error) => { if (alive) { setActionError(errorText(error)); setActive(null); } });
    }, 650);
    return () => { alive = false; window.clearInterval(timer); };
  }, [active?.id, active?.state]);

  // A freshly built plan opens its confirmation dialog right away.
  useEffect(() => {
    if (active?.kind === "plan" && active.state === "done" && isPlan(active)) setConfirm(true);
  }, [active?.id, active?.kind, active?.state]);

  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000); return () => window.clearInterval(timer); }, []);

  const latestScan = (active && isScan(active) ? active : jobs.find(isScan))?.result as CleanupScan | undefined;
  const planJob = active && isPlan(active) ? active : jobs.find(isPlan);
  const latestPlan = planJob?.result as CleanupPlan | undefined;
  const latestClean = (active && isClean(active) ? active : jobs.find(isClean))?.result as CleanupResult | undefined;
  const planUsed = !!latestPlan && jobs.some((job) => isClean(job) && job.request.planId === latestPlan.planId);
  const busy = submitting || active?.state === "running";
  const canWork = status?.state === "ready" && !busy;

  // Quick-cleanup suggestions: measured, safe, non-privileged entries.
  const measured = useMemo(() => new Map(latestScan?.entries.map((item) => [item.id, item]) ?? []), [latestScan]);
  const safeEntries = entries.filter((item) => measured.get(item.id)?.sizeBytes && !["high", "privacy", "credentials"].includes(item.risk) && !item.needsPrivilege);
  const suggested = safeEntries.filter((item) => preset === "extended" || item.defaultSelected);
  const suggestedIds = suggested.map((item) => item.id);
  const suggestedBytes = suggested.reduce((sum, item) => sum + (measured.get(item.id)?.sizeBytes ?? 0), 0);
  const planFollowsScan = !!planJob && jobs.findIndex((job) => job.id === planJob.id) <= jobs.findIndex(isScan);
  const planMatches = !!latestPlan && planFollowsScan && latestPlan.mode === "trash" && JSON.stringify([...(planJob?.request.entryIds ?? [])].sort()) === JSON.stringify([...suggestedIds].sort());
  const canConfirmSuggested = canWork && !!latestPlan && planMatches && !planUsed && latestPlan.expiresAt > now && latestPlan.totals.ready > 0;

  // Advanced-scan card grid: sizes, sort order and cleanability ranking.
  const sizes = useMemo(() => new Map((latestScan?.entries ?? []).map((item) => [item.id, item.sizeBytes])), [latestScan]);
  const maxSize = useMemo(() => Math.max(0, ...sizes.values()), [sizes]);
  const sortedEntries = useMemo(() => sortEntries(entries, sizes, order), [entries, sizes, order]);
  const riskTotals = useMemo(() => totalsByRisk(entries, sizes), [entries, sizes]);
  const resultGroups = useMemo(() => {
    if (!latestScan) return [];
    const sorted = sortEntries(latestScan.entries, sizes, "size");
    const present = [...new Set(sorted.map((item) => item.category))];
    const ordered = [...CATEGORY_ORDER.filter((category) => present.includes(category)), ...present.filter((category) => !CATEGORY_ORDER.includes(category))];
    return ordered.map((category) => [category, sorted.filter((item) => item.category === category)] as const);
  }, [latestScan, sizes]);

  const defaults = entries.filter((item) => item.defaultSelected && item.risk !== "credentials" && item.risk !== "privacy").map((item) => item.id);
  const planEntryIds = planJob?.request.entryIds ?? [];
  const planCurrent = !!latestPlan && !planUsed && latestPlan.expiresAt > now
    && latestPlan.mode === mode
    && [...planEntryIds].sort().join("\u0000") === [...selected].sort().join("\u0000");

  async function start(action: () => Promise<CleanupJob>) {
    setActionError(""); setSubmitting(true); setConfirm(false);
    try { const job = await action(); setActive(job); setJobs((old) => [job, ...old]); }
    catch (error) { setActionError(errorText(error)); }
    finally { setSubmitting(false); }
  }
  async function cancel() {
    if (!active) return;
    setActionError("");
    try { await api.cleanupCancel(active.id); }
    catch (error) { setActionError(errorText(error)); }
  }
  function reviewAndClean() {
    setActionError("");
    if (planCurrent) setConfirm(true);
    else void start(() => api.cleanupPlan(selected, mode));
  }

  const tabs: { id: CleanupPageId; label: string; path: string }[] = [
    { id: "", label: "Dashboard", path: "" }, { id: "settings", label: "Settings", path: "settings/" }, { id: "space", label: "Space Explorer", path: "space/" }, { id: "scan", label: "Advanced scan", path: "scan/" }, { id: "results", label: "Results", path: "results/" },
    { id: "leftovers", label: "Leftovers", path: "leftovers/" }, { id: "history", label: "History", path: "history/" }, { id: "relocation", label: "Relocation", path: "relocation/" }
  ];
  return <AppShell activeId={`cleanup-${page || "scan"}`}>
    <TopBar title="Cleanup Lab" icon={<BroomIcon size={20} />} />
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6" onClick={onNavClick}>
      <PageHead toolbarOnly icon={<BroomIcon size={22} />} title="Cleanup Lab" description="Measure reclaimable space, review a plan, then confirm each clean."
        actions={<>
          {page === "" && !PUBLIC && <a className="iux-btn" href={link("settings/")}>Settings</a>}
          {!PUBLIC && status && <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${status.state === "ready" ? "bg-(--iux-success)/10 text-(--iux-success)" : "bg-(--iux-warning)/10 text-(--iux-warning)"}`}>
            {status.state === "ready" ? "Ready" : status.state === "needs-setup" ? "Setup needed" : "Unavailable"}
          </span>}
          {!PUBLIC && <span className="text-xs text-(--iux-muted-foreground)">
            {latestScan ? `Last scan measured ${bytes(latestScan.totals.sizeBytes)}` : "No scan run yet"}
          </span>}
        </>} />
      {!PUBLIC && <MonitorBanner monitor={monitor} scanHref={link("scan/")} />}
      {(page !== "" || PUBLIC) && <nav aria-label="Cleanup pages" className="flex flex-wrap gap-2">{tabs.map((tab) =>
        <a key={tab.id} href={link(tab.path)} aria-current={page === tab.id ? "page" : undefined} className="iux-btn" data-variant={page === tab.id ? "primary" : "outline"}>{tab.label}</a>)}</nav>}
      {PUBLIC ? <Section title="Local app required"><p>The Cleanup Lab runs in the local app. Install and open os-lab on your computer to scan and clean.</p></Section> :
        loading ? <p role="status">Loading cleanup readiness…</p> : loadError ? <Status value={{ ok: false, text: loadError }} /> : <>
          {status?.state !== "ready" && <Section title="Readiness" description={status?.state === "needs-setup" ? "Setup needed before scanning" : "Unavailable on this system"}>
            {status?.reasons.map((reason) => <p key={reason}>{reason}</p>)}
            {status?.requirements.filter((item) => !item.found).map((item) => <p key={item.id}>{item.label}: {item.hint}</p>)}
            <button type="button" className="iux-btn mt-3" onClick={() => { setLoading(true); void api.cleanupStatus().then(setStatus).catch((error) => setLoadError(errorText(error))).finally(() => setLoading(false)); }}>Re-check</button>
          </Section>}
          {page === "" && <>
            {!PUBLIC && status?.state === "ready" && <StorageHero volumes={volumes} onRefresh={reloadVolumes} />}
            {!PUBLIC && status?.state === "ready" && <div className="grid items-start gap-5 lg:grid-cols-2">
              <QuickCleanCard bookmarks={bookmarks} busy={busy} canWork={canWork} measured={measured} refusals={quickRefusals}
                onQuickClean={runQuickClean} settingsHref={link("settings/")} />
              <Section id="overview-review" title="Clean" description="Scan the safe categories, review the plan, then confirm. Nothing is removed during a scan.">
                <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-(--iux-muted-foreground)">{status?.state === "ready" ? "Ready to scan" : "Scan unavailable until setup is complete"} · {entries.length} categories available</p><button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !entries.length} onClick={() => void start(() => api.cleanupScan(entries.map((item) => item.id)))}>{latestScan ? "Scan again" : "Scan now"}</button></div>
                {active?.state === "running" && <div className="mt-4" role="status"><p>{active.kind} in progress · <span dir="ltr">{String(active.progress?.pathsDone ?? active.progress?.itemsDone ?? 0)} / {String(active.progress?.pathsTotal ?? active.progress?.itemsTotal ?? "…")}</span></p><progress className="mt-2 w-full" max={Number(active.progress?.pathsTotal ?? active.progress?.itemsTotal ?? 1)} value={Number(active.progress?.pathsDone ?? active.progress?.itemsDone ?? 0)} /><p className="break-all text-xs text-(--iux-muted-foreground)" translate="no">{active.progress?.currentPath}</p><button type="button" className="iux-btn mt-2" onClick={() => void cancel()}>Cancel</button></div>}
                {active?.state === "failed" && <Status value={{ ok: false, text: active.error || "The cleanup job failed." }} />}{actionError && <Status value={{ ok: false, text: actionError }} />}
                {latestScan && <>
                  <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Cleanup preset"><button type="button" className="iux-btn" data-variant={preset === "recommended" ? "primary" : "outline"} aria-pressed={preset === "recommended"} disabled={busy} onClick={() => { setPreset("recommended"); setConfirm(false); }}>Recommended</button><button type="button" className="iux-btn" data-variant={preset === "extended" ? "primary" : "outline"} aria-pressed={preset === "extended"} disabled={busy} onClick={() => { setPreset("extended"); setConfirm(false); }}>More safe options</button></div>
                  <p className="mt-3 text-sm">{suggested.length} <span>categories · </span><span dir="ltr" className="tabular-nums">{bytes(suggestedBytes)}</span><span> measured · Move to Trash</span></p><p className="text-sm text-(--iux-muted-foreground)">High risk, privacy, credentials and privileged items require separate review.</p>
                  {suggested.length ? <details className="mt-3 text-sm"><summary className="cursor-pointer">Included categories</summary><ul className="mt-2 space-y-1">{suggested.map((item) => <li key={item.id}>{item.name} · <span dir="ltr" className="tabular-nums">{bytes(measured.get(item.id)?.sizeBytes ?? 0)}</span></li>)}</ul></details> : <Empty>No safe cleanup suggestions in this scan.</Empty>}
                  <div className="mt-4 flex flex-wrap gap-2"><button type="button" className="iux-btn" disabled={!canWork || latestScan.cancelled || !suggested.length} onClick={() => void start(() => api.cleanupPlan(suggestedIds, "trash"))}>Review plan</button><a className="iux-btn" href={link("results/")}>Full scan report</a><a className="iux-btn" href={link("scan/")}>Choose individual items</a></div>
                  {latestPlan && planMatches && <div className="mt-4 rounded-md border border-(--iux-border) p-3 text-sm"><p><span className="font-semibold tabular-nums">{latestPlan.totals.ready}</span> items ready · <span dir="ltr" className="tabular-nums">{bytes(latestPlan.totals.bytes)}</span> · {latestPlan.totals.skipped} skipped</p><p>Plan expires in {Math.max(0, Math.ceil(latestPlan.expiresAt - now))} seconds. Cleaning moves items to Trash; it does not free disk space until Trash is emptied.</p><details className="mt-2"><summary className="cursor-pointer">Plan details</summary>{latestPlan.items.map((item, index) => <p key={`${item.entryId}-${index}`} className="mt-2 break-all"><span dir="ltr" className="tabular-nums">{bytes(item.sizeBytes)}</span> · {item.status} · {item.entryName} · <span translate="no">{item.path}</span>{item.reason && ` · ${item.reason}`}</p>)}</details>{planUsed && <p>This plan was already run. Review a new plan.</p>}<button type="button" className="iux-btn mt-3" data-variant="primary" disabled={!canConfirmSuggested} onClick={() => setConfirm(true)}>Confirm clean</button></div>}
                  {confirm && latestPlan && planMatches && <ConfirmDialog plan={latestPlan} planUsed={planUsed} now={now} busy={!!busy} error={actionError}
                    onRun={() => void start(() => api.cleanupClean(latestPlan.planId))} onClose={() => setConfirm(false)} />}
                </>}
              </Section>
            </div>}
            {!PUBLIC && status?.state === "ready" && <MonitorStatsCard monitor={monitor} volumes={volumes} settingsHref={link("settings/")} />}
            {latestClean && <Section title="Latest clean report" description={`${latestClean.totals.trashed} moved to Trash · ${latestClean.totals.skipped} skipped · ${latestClean.totals.failed} failed`}>
              <div className="flex flex-wrap gap-2">
                <Badge tone={latestClean.totals.trashed ? "success" : undefined}>{itemStatusLabel("trashed")} {latestClean.totals.trashed}</Badge>
                <Badge>{itemStatusLabel("deleted")} {latestClean.totals.deleted}</Badge>
                <Badge>{itemStatusLabel("skipped")} {latestClean.totals.skipped}</Badge>
                <Badge tone={latestClean.totals.failed ? "danger" : undefined}>{itemStatusLabel("failed")} {latestClean.totals.failed}</Badge>
              </div>
              <p className="mt-3 text-sm"><span dir="ltr" className="tabular-nums">{bytes(latestClean.totals.bytes)}</span> moved to Trash, not yet freed.</p>
              <div className="mt-3 flex gap-2"><a className="iux-btn" href={link("results/")}>View report</a><a className="iux-btn" href={link("leftovers/")}>View leftovers</a><a className="iux-btn" href={link("history/")}>History</a></div>
            </Section>}
          </>}
          {page === "settings" && !PUBLIC && status?.state === "ready" && <>
            <BookmarksSection bookmarks={bookmarks} reload={reloadBookmarks}
              onQuickClean={(job) => { setActive(job); setJobs((old) => [job, ...old.filter((row) => row.id !== job.id)]); setBookmarkConfirm(true); }}
              onCatalogChanged={() => { void api.cleanupCatalog().then((catalog) => setEntries(catalog.entries)).catch(() => {}); }} />
            <PermissionsCard permissions={permissions} />
            <MonitorCard monitor={monitor} volumes={volumes} reload={monitorReload} />
            <WidgetsCard snapshot={widget} reload={reloadWidget} />
            <Section title="Tools & advanced" description="The detailed cleanup tools, one click away.">
              <OverviewCards go={goCard} />
            </Section>
          </>}
          {!PUBLIC && bookmarkConfirm && active && isPlan(active) &&
            <ConfirmDialog plan={active.result} planUsed={planUsed} now={now} busy={!!busy} error={actionError}
              onRun={() => void start(() => api.cleanupClean(active.result.planId))}
              onClose={() => { setBookmarkConfirm(false); }} />}
          {page === "scan" && <>
            <Section title="Scan" description="Choose catalog entries. Scanning only measures files; it does not remove them.">
              {!entries.length ? <Empty>No cleanup entries are available on this system.</Empty> : <>
                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} title="Select default entries"
                    onClick={() => { setSelected(defaults); setConfirm(false); }}>Defaults</button>
                  <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} title="Select all entries"
                    onClick={() => { setSelected(entries.map((item) => item.id)); setConfirm(false); }}>All</button>
                  <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} title="Clear selection"
                    onClick={() => { setSelected([]); setConfirm(false); }}>None</button>
                  <span className="text-sm text-(--iux-muted-foreground)">
                    <span className="font-medium text-(--iux-foreground)">{selected.length}</span> / {entries.length} <span>selected</span>
                  </span>
                  <div role="group" aria-label="Sort entries" className="ms-auto flex gap-1">
                    <button type="button" className="iux-btn" data-variant={order === "size" ? "outline" : "ghost"} aria-pressed={order === "size"}
                      onClick={() => setOrder("size")}>Largest first</button>
                    <button type="button" className="iux-btn" data-variant={order === "cleanable" ? "outline" : "ghost"} aria-pressed={order === "cleanable"}
                      onClick={() => setOrder("cleanable")}>Safest first</button>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">{sortedEntries.map((item) => {
                  const size = sizes.get(item.id);
                  const on = selected.includes(item.id);
                  return <label key={item.id}
                    className={`flex cursor-pointer flex-col gap-2 rounded-md border p-3 text-sm transition-colors ${on ? "border-[#f36c21]/70 bg-[#f36c21]/5" : "border-(--iux-border)"}`}>
                    <span className="flex items-center gap-2">
                      <input type="checkbox" className="iux-touch-target size-4 shrink-0 accent-[#f36c21]" checked={on} disabled={busy}
                        onChange={(event) => { setSelected((old) => event.target.checked ? [...old, item.id] : old.filter((id) => id !== item.id)); setConfirm(false); }} />
                      <CategoryIcon category={item.category} />
                      <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
                      {item.needsPrivilege && <PrivilegeMarker />}
                      {!PUBLIC && <BookmarkToggle entryId={item.id} bookmarked={bookmarkedIds.has(item.id)} busy={busy} onToggle={toggleBookmark} />}
                      <InfoPopover><EntryDetails entry={item} /></InfoPopover>
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge tone={riskTone(item.risk)}>{riskLabel(item.risk)}</Badge>
                      <span dir="ltr" className="ms-auto tabular-nums">
                        {size != null ? bytes(size) : item.paths.some((path) => path.path) ? "Not measured" : "Unavailable"}
                      </span>
                    </span>
                    {size != null && <SizeBar value={size} max={maxSize} />}
                  </label>;
                })}</div>
              </>}
              <div className="mt-3 flex flex-wrap gap-2"><button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !selected.length} onClick={() => void start(() => api.cleanupScan(selected))}>Scan selected</button>
                {active?.state === "running" && <button type="button" className="iux-btn" onClick={() => void cancel()}>Cancel</button>}</div>
              {active?.state === "running" && <div className="mt-3 space-y-2">
                <div className="iux-progress h-1 rounded-full" aria-hidden="true" />
                <p role="status">{active.kind} in progress · <span dir="ltr">{String(active.progress?.pathsDone ?? active.progress?.itemsDone ?? 0)} / {String(active.progress?.pathsTotal ?? active.progress?.itemsTotal ?? 0)}</span><span translate="no" className="block break-all">{active.progress?.currentPath}</span></p>
              </div>}
              {active?.state === "failed" && <Status value={{ ok: false, text: active.error || "The cleanup job failed." }} />}
              {actionError && <Status value={{ ok: false, text: actionError }} />}
            </Section>
            {latestScan && <Section title="Measured space" action={<a className="iux-btn" href={link("results/")}>View results</a>}
              description={<span dir="ltr">{`${bytes(latestScan.totals.sizeBytes)} across ${latestScan.entries.length} entries`}</span>}>
              {latestScan.cancelled && <p>Scan cancelled. Results are partial.</p>}
              {latestScan.totals.sizeBytes > 0 && <>
                <div className="flex h-2 overflow-hidden rounded-full bg-(--iux-muted)">
                  {riskTotals.map(({ risk, sizeBytes }) => <span key={risk} aria-hidden="true"
                    className={RISK_BAR[risk] ?? "bg-(--iux-muted-foreground)"} style={{ width: `${(sizeBytes / latestScan.totals.sizeBytes) * 100}%` }} />)}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  {riskTotals.map(({ risk, sizeBytes }) => <span key={risk} className="flex items-center gap-1.5">
                    <span aria-hidden="true" className={`size-2 rounded-full ${RISK_BAR[risk] ?? "bg-(--iux-muted-foreground)"}`} />
                    {riskLabel(risk)}
                    <span dir="ltr" className="tabular-nums text-(--iux-muted-foreground)">{bytes(sizeBytes)}</span>
                  </span>)}
                </div>
              </>}
              {latestScan.totals.files > 0 && <p className="mt-2 text-xs text-(--iux-muted-foreground)">{latestScan.totals.files} <span>files</span> · {latestScan.totals.folders} <span>folders</span></p>}
              {latestScan.totals.unreadable > 0 && <p className="text-xs text-(--iux-warning)">{latestScan.totals.unreadable} <span>unreadable paths</span></p>}
              {(permissions?.classification?.classified ?? []).length > 0 && <p className="mt-1 text-xs text-(--iux-muted-foreground)">
                {permissions!.classification!.classified.length} <span>need a grant:</span>{" "}
                {[...new Set(permissions!.classification!.classified.map((item) => permissionName(item.permissionId, permissions!)))].join(", ")}
              </p>}
            </Section>}
            <Section title="Plan & confirm" description="A plan checks every path again. Trash is the default; permanent deletion requires an explicit choice.">
              <label className="text-sm">Mode <select value={mode} disabled={busy} onChange={(event) => { setMode(event.target.value as "trash" | "delete"); setConfirm(false); }} className="iux-input ml-2"><option value="trash">Trash (default)</option><option value="delete">Delete permanently</option></select></label>
              {mode === "delete" && <p className="mt-2 text-sm">Deleting permanently cannot be undone.</p>}
              <div className="mt-3"><button type="button" className="iux-btn" data-variant="primary" disabled={!canWork || !selected.length} onClick={reviewAndClean}>Review & clean</button></div>
              {confirm && latestPlan && <ConfirmDialog plan={latestPlan} planUsed={planUsed} now={now} busy={!!busy} error={actionError}
                onRun={() => void start(() => api.cleanupClean(latestPlan.planId))} onClose={() => setConfirm(false)} />}
            </Section>
            {latestClean && <Section title="Clean result" description={<span dir="ltr">{`${bytes(latestClean.totals.bytes)} ${latestClean.mode === "trash" ? "moved to Trash, not freed" : "deleted permanently"}`}</span>}>
              <div className="flex flex-wrap gap-2">
                <Badge tone={latestClean.totals.trashed ? "success" : undefined}>{itemStatusLabel("trashed")} {latestClean.totals.trashed}</Badge>
                <Badge>{itemStatusLabel("deleted")} {latestClean.totals.deleted}</Badge>
                <Badge>{itemStatusLabel("skipped")} {latestClean.totals.skipped}</Badge>
                <Badge tone={latestClean.totals.failed ? "danger" : undefined}>{itemStatusLabel("failed")} {latestClean.totals.failed}</Badge>
              </div>
              <a className="iux-btn mt-3" href={link("leftovers/")}>View leftovers</a>
            </Section>}
            <CleanupExtraTools now={now} />
          </>}
          {page === "results" && <>
            <Section title="Results by category" description="Measurements from the latest scan in this console session.">
              {!latestScan ? <Empty>No scan results yet. Run a scan first.</Empty> : <>
                {latestScan.cancelled && <p>Scan cancelled. Results are partial.</p>}
                {resultGroups.map(([category, group]) => <div key={category} className="mt-4 first:mt-0">
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold"><CategoryIcon category={category} size={13} />{CATEGORY_LABEL[category] ?? category}</h3>
                  <div className="mt-1 divide-y divide-(--iux-border)">{group.map((item) =>
                    <div key={item.id} className="py-2 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
                        <span dir="ltr" className="tabular-nums">{bytes(item.sizeBytes)}</span>
                        {!PUBLIC && <BookmarkToggle entryId={item.id} bookmarked={bookmarkedIds.has(item.id)} onToggle={toggleBookmark} />}
                        <InfoPopover><ScanDetails item={item} /></InfoPopover>
                      </div>
                      <SizeBar value={item.sizeBytes} max={maxSize} />
                    </div>)}</div>
                </div>)}
                {!latestScan.entries.length && <Empty>No measured results yet.</Empty>}
              </>}
            </Section>
            <Section title="Clean result" description={latestClean ? <span dir="ltr">{`${bytes(latestClean.totals.bytes)} ${latestClean.mode === "trash" ? "moved to Trash, not freed" : "deleted permanently"}`}</span> : undefined}>
              {!latestClean ? <Empty>No clean results yet.</Empty> : <>
                <div className="flex flex-wrap gap-2">
                  <Badge tone={latestClean.totals.trashed ? "success" : undefined}>{itemStatusLabel("trashed")} {latestClean.totals.trashed}</Badge>
                  <Badge>{itemStatusLabel("deleted")} {latestClean.totals.deleted}</Badge>
                  <Badge>{itemStatusLabel("skipped")} {latestClean.totals.skipped}</Badge>
                  <Badge tone={latestClean.totals.failed ? "danger" : undefined}>{itemStatusLabel("failed")} {latestClean.totals.failed}</Badge>
                </div>
                {latestClean.results.map((item, index) => <div key={index} className="flex gap-2 border-b border-(--iux-border) py-2 text-sm">
                  <span className="mt-0.5"><StatusIcon status={item.status} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 truncate font-medium">{item.entryName}</span>
                      <Badge tone={item.status === "failed" ? "danger" : item.status === "trashed" ? "success" : undefined}>{itemStatusLabel(item.status)}</Badge>
                    </div>
                    <p className="break-all text-xs" translate="no">{item.path}</p>
                    <PathSource source={item.source} />
                    <p className="text-xs text-(--iux-muted-foreground)">{item.reason || item.error}</p>
                    {item.trashPath && <p translate="no" className="break-all text-xs text-(--iux-muted-foreground)">{item.trashPath}</p>}
                  </div>
                </div>)}
              </>}
            </Section>
          </>}
          {page === "leftovers" && <><Section title="Leftovers" description="Items that were skipped, failed, or could not be read.">
            {!latestClean && !latestScan ? <Empty>No results yet. Run a scan first.</Empty> : <>
              {latestClean?.results.filter((item) => item.status === "skipped" || item.status === "failed").map((item, index) =>
                <div key={index} className="flex gap-2 border-b border-(--iux-border) py-3 text-sm">
                  <span className="mt-0.5"><StatusIcon status={item.status} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 truncate font-medium">{item.entryName}</span>
                      <Badge tone={item.status === "failed" ? "danger" : undefined}>{itemStatusLabel(item.status)}</Badge>
                    </div>
                    <p className="break-all text-xs" translate="no">{item.path}</p>
                    <p className="text-xs text-(--iux-muted-foreground)">{item.reason || item.error}</p>
                  </div>
                </div>)}
              {latestScan?.entries.filter((item) => item.unreadable.length).map((item) =>
                <div key={item.id} className="flex items-center gap-2 border-b border-(--iux-border) py-3 text-sm">
                  <span className="min-w-0 truncate font-medium">{item.name}</span>
                  <span className="ms-auto text-xs text-(--iux-muted-foreground)">{item.unreadable.length} <span>unreadable paths</span></span>
                </div>)}
              {!latestClean?.results.some((item) => item.status === "skipped" || item.status === "failed") && !latestScan?.entries.some((item) => item.unreadable.length) && <Empty>No leftovers were reported.</Empty>}
            </>}
          </Section>
          {(status?.platform?.id === "linux" || status?.platform?.id === "windows") && <CrossPlatformLeftovers />}
          </>}
          {page === "space" && <SpaceExplorer scanHref={link("scan/")} />}
          {page === "relocation" && <RelocationCard now={now} />}
          {page === "history" && <Section title="Audit history" description="Verified cleanup runs stored on this computer.">
            {!history?.entries.length ? <Empty>No cleanup runs recorded yet.</Empty> : history.entries.map((entry) =>
              "totals" in entry.result ?
              <div key={entry.id} className="border-b border-(--iux-border) py-3 text-sm">
                <div className="flex items-center gap-2">
                  <strong>Run #{entry.id}</strong>
                  <Badge>{entry.result.mode === "trash" ? "Trash" : "Delete"}</Badge>
                  <span dir="ltr" className="ms-auto tabular-nums">{bytes(entry.result.totals.bytes)}</span>
                </div>
                <p className="mt-1 text-xs text-(--iux-muted-foreground)">{entry.result.totals.items} <span>items</span> · {entry.result.cancelled ? "cancelled" : "finished"}</p>
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-(--iux-muted-foreground)">Items</summary>
                  <div className="iux-scroll mt-1 max-h-56 overflow-auto">
                    {entry.result.results.map((item, index) => <div key={index} className="flex items-start gap-1 py-0.5 text-xs">
                      {!PUBLIC && <BookmarkToggle entryId={item.entryId} bookmarked={bookmarkedIds.has(item.entryId)} onToggle={toggleBookmark} title="Bookmark this item" />}
                      <p className="min-w-0 flex-1 break-all"><span translate="no">{item.path}</span> · {item.status} · {bytes(item.bytes)}</p>
                    </div>)}
                  </div>
                </details>
              </div> :
              <div key={entry.id} className="border-b border-(--iux-border) py-3 text-sm">
                <div className="flex items-center gap-2">
                  <strong>Run #{entry.id}</strong>
                  <Badge>Relocation</Badge>
                  <span dir="ltr" className="ms-auto tabular-nums">{bytes(entry.result.bytesRelocated)}</span>
                </div>
                <p className="mt-1 break-all text-xs text-(--iux-muted-foreground)" translate="no">{entry.result.entryId} · {entry.result.action} · {entry.result.cancelled ? "cancelled" : entry.result.status === "completed" ? "completed" : "failed"}</p>
                <p className="break-all text-xs text-(--iux-muted-foreground)" translate="no">{entry.result.storePath || entry.result.error}</p>
              </div>)}
          </Section>}
        </>}
    </main>
  </AppShell>;
}
