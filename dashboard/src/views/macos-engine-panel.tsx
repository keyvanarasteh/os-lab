/**
 * macOS Lab engine panel: the QcU-parity endpoints in one card. What the console can do right
 * now (capabilities), which app each permission belongs to with a consent request, the
 * displays, an element search over a window, and the live audit feed (SSE). Everything here is
 * read-only except "Request access", which only fires the system dialog or opens a Privacy
 * pane; input stays in the mirror panel behind armed control.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { CircleNotchIcon, MagnifyingGlassIcon, PulseIcon, ShieldCheckIcon } from "@phosphor-icons/react";
import { Badge, Empty, Field, Status } from "../components/ui";
import { api, message, usePoll, type MacAuditRow, type MacElement, type MacPane, type MacPermission } from "../lib/api";

const MAX_EVENTS = 8;

function PermissionRow({ label, permission, pane, onRequest, busy }: {
  label: string; permission?: MacPermission; pane: MacPane; onRequest: (pane: MacPane) => void; busy: boolean;
}) {
  // An older console may leave a permission out; show it as unknown instead of crashing the page.
  const granted = permission?.granted;
  const state = granted === true ? "Granted" : granted === false ? "Not granted" : "Unknown";
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-medium">{label}</span>
      <Badge tone={granted === true ? "success" : granted === false ? "warning" : undefined}>{state}</Badge>
      <span className="text-xs text-(--iux-muted-foreground)">{permission?.grantTo}</span>
      {granted === true ? null : (
        <button type="button" className="iux-btn ml-auto" data-variant="outline" disabled={busy} onClick={() => onRequest(pane)}>
          Request access
        </button>
      )}
    </li>
  );
}

export function MacEnginePanel() {
  const caps = usePoll(() => api.macosCapabilities(), 30000);
  const perms = usePoll(() => api.macosPermissions(), 15000);
  const displays = usePoll(() => api.macosDisplays(), 60000);
  const apps = usePoll(() => api.macosApps(), 10000);
  const [requesting, setRequesting] = useState(false);
  const [requestNote, setRequestNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [windowId, setWindowId] = useState(0);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<MacElement[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [events, setEvents] = useState<MacAuditRow[]>([]);
  const [liveError, setLiveError] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);

  const windows = apps.data?.windows ?? [];
  const selected = windows.find((w) => w.windowId === windowId) ?? windows[0] ?? null;

  const request = useCallback(async (pane: MacPane) => {
    setRequesting(true);
    setRequestNote(null);
    try {
      const result = await api.macosRequestAccess(pane);
      setRequestNote({
        ok: result.ok,
        text: result.ok
          ? `System Settings opened. Enable ${result.grantTo ?? "the app that launched the console"} in the list.`
          : "System Settings did not open."
      });
      perms.reload();
    } catch (e) {
      setRequestNote({ ok: false, text: message(e) });
    } finally {
      setRequesting(false);
    }
  }, [perms]);

  const search = async () => {
    if (!selected || !query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      setHits((await api.macosSearch(selected.windowId, query.trim())).hits);
    } catch (e) {
      setHits(null);
      setSearchError(message(e));
    } finally {
      setSearching(false);
    }
  };

  // The live feed is opt-in and closes when switched off, hidden or unmounted, so the console's
  // handler thread never outlives the panel (it also ends itself on the panic stop).
  useEffect(() => {
    if (!live) return;
    const stream = new EventSource(api.macosEventsUrl);
    source.current = stream;
    setLiveError(null);
    stream.onmessage = (event) => {
      try {
        const row = JSON.parse(event.data) as MacAuditRow;
        setEvents((rows) => [row, ...rows].slice(0, MAX_EVENTS));
      } catch {
        /* a malformed row is skipped, not fatal */
      }
    };
    stream.onerror = () => {
      setLiveError("The live feed stopped; switch it on again to reconnect.");
      stream.close();
      setLive(false);
    };
    const onHide = () => {
      if (document.hidden) setLive(false);
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      stream.close();
      source.current = null;
    };
  }, [live]);

  const info = caps.data;
  return (
    <section className="iux-card items-start gap-3 py-4" aria-label="macOS Lab engine">
      <div className="flex items-center gap-2 px-4">
        <ShieldCheckIcon size={15} className="text-[#f36c21]" aria-hidden />
        <span className="text-sm font-semibold">Engine</span>
        {info ? <Badge>{info.engine === "ax-helper" ? "Native AX helper" : info.engine === "osascript" ? "osascript fallback" : "No engine"}</Badge> : null}
        {info?.control?.armed ? <Badge tone="warning">Armed</Badge> : null}
      </div>

      <div className="flex w-full flex-col gap-4 px-4">
        {caps.error ? <Status value={{ ok: false, text: caps.error }} /> : null}
        {info && !info.helperBuilt ? (
          <p className="text-sm text-(--iux-muted-foreground)">
            The native AX helper is not built; element reads use the slower osascript path. Run make mac-setup to build it.
          </p>
        ) : null}
        {info?.safety ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
            <dt className="text-(--iux-muted-foreground)">Control timeout</dt>
            <dd>{Math.round(info.safety.controlTimeoutSec / 60)} min</dd>
            <dt className="text-(--iux-muted-foreground)">Audit rows kept</dt>
            <dd>{info.safety.auditMax}</dd>
            <dt className="text-(--iux-muted-foreground)">Stream limit</dt>
            <dd>{Math.round(info.safety.streamCapSec / 60)} min</dd>
            <dt className="text-(--iux-muted-foreground)">Submit-class keys</dt>
            <dd>Confirmation required even when armed</dd>
          </dl>
        ) : null}

        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-(--iux-muted-foreground)">Permissions</h3>
          {perms.error ? <Status value={{ ok: false, text: perms.error }} /> : null}
          {perms.data ? (
            <ul className="flex flex-col gap-2">
              <PermissionRow label="Accessibility" permission={perms.data.accessibility} pane="accessibility" onRequest={(p) => void request(p)} busy={requesting} />
              <PermissionRow label="Screen Recording" permission={perms.data.screenRecording} pane="screen-recording" onRequest={(p) => void request(p)} busy={requesting} />
            </ul>
          ) : null}
          <Status value={requestNote} />
        </div>

        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-(--iux-muted-foreground)">Displays</h3>
          {displays.data?.displays?.length ? (
            <ul className="flex flex-col gap-1 text-sm">
              {displays.data.displays.map((d, i) => (
                <li key={`${d.x}-${d.y}-${i}`}>{`${d.width}×${d.height} pt · ${d.x},${d.y} · ${d.scale}×`}</li>
              ))}
            </ul>
          ) : (
            <Empty>{displays.data?.reason ?? "No display information yet."}</Empty>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-(--iux-muted-foreground)">Find an element</h3>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Window">
              <select className="iux-input" value={selected?.windowId ?? 0} onChange={(e) => { setWindowId(Number(e.target.value)); setHits(null); }} aria-label="Window to search">
                {windows.map((w) => (
                  <option key={w.windowId} value={w.windowId}>{w.app}{w.title ? ` — ${w.title}` : ""}</option>
                ))}
              </select>
            </Field>
            <Field label="Label, value or placeholder">
              <input className="iux-input" value={query} maxLength={120} onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") void search(); }} />
            </Field>
            <button type="button" className="iux-btn" data-variant="outline" disabled={!selected || !query.trim() || searching} onClick={() => void search()}>
              {searching ? <CircleNotchIcon size={14} className="animate-spin" aria-hidden /> : <MagnifyingGlassIcon size={14} aria-hidden />}
              Search
            </button>
          </div>
          {searchError ? <Status value={{ ok: false, text: searchError }} /> : null}
          {hits ? (
            hits.length ? (
              <ul className="flex flex-col gap-1 text-sm">
                {hits.map((h) => (
                  <li key={`${h.path}-${h.identity}`} className="flex flex-wrap items-center gap-2">
                    <Badge>{h.role}</Badge>
                    <span>{h.label || h.value || h.placeholder}</span>
                    <code className="text-xs text-(--iux-muted-foreground)">{h.path || "root"}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No element matches.</Empty>
            )
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-(--iux-muted-foreground)">Live audit feed</h3>
            <button type="button" className="iux-btn ml-auto" data-variant="outline" aria-pressed={live} onClick={() => setLive((v) => !v)}>
              <PulseIcon size={14} aria-hidden />
              {live ? "Stop feed" : "Start feed"}
            </button>
          </div>
          {liveError ? <Status value={{ ok: false, text: liveError }} /> : null}
          {events.length ? (
            <ul className="flex flex-col gap-1 text-xs">
              {events.map((row, i) => (
                <li key={`${row.time}-${i}`} className="flex flex-wrap gap-2">
                  <span className="text-(--iux-muted-foreground)">{new Date(row.time * 1000).toLocaleTimeString()}</span>
                  <Badge>{row.kind}</Badge>
                  {row.app ? <span>{row.app}</span> : null}
                </li>
              ))}
            </ul>
          ) : live ? (
            <Empty>Waiting for the next action…</Empty>
          ) : null}
        </div>
      </div>
    </section>
  );
}
