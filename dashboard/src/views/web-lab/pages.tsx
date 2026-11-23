import { useEffect, useRef, useState } from "react";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowsClockwiseIcon,
  CornersInIcon,
  CornersOutIcon,
  GlobeIcon,
  PlusIcon,
  XIcon
} from "@phosphor-icons/react";
import { AppShell, labHref } from "../../shell/app-shell";
import { TopBar } from "../../shell/top-bar";
import { Badge, Empty, IconButton, PageHead, Section, Status } from "../../components/ui";
import { api, usePoll, type WebEvent, type WebOverview, type WebStatus, type WebWindowState } from "../../lib/api";

const VIEWPORTS = ["responsive", "mobile", "tablet", "desktop"] as const;
type Viewport = (typeof VIEWPORTS)[number];
const MAX_LOG_ENTRIES = 200;
const PREVIEW_INTERVAL = 1500;
const errorText = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** The workbench drives the local engine: windows, injections, eval and the event log. */
export default function WebLabPage() {
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("https://example.com");
  const [profile, setProfile] = useState("default");
  const [viewport, setViewport] = useState<Viewport>("responsive");
  const [userAgent, setUserAgent] = useState("");
  const [injectionName, setInjectionName] = useState("");
  const [injectionCode, setInjectionCode] = useState("");
  const [evalTarget, setEvalTarget] = useState("");
  const [evalCode, setEvalCode] = useState("return document.title;");
  const [events, setEvents] = useState<WebEvent[]>([]);
  const cursor = useRef(0);
  // The live-preview panel: a docked right pane showing polled snapshots of one
  // engine window, with the device-size toggle that resizes it. Open by default.
  const [panelOpen, setPanelOpen] = useState(true);
  const [panelExpanded, setPanelExpanded] = useState(false);
  const [panelTarget, setPanelTarget] = useState("");

  const { data, error: loadError, reload } = usePoll<
    { status: WebStatus; overview: WebOverview | null } | null
  >(async () => {
    const status = await api.webStatus();
    const overview = status.state === "ready" ? await api.webOverview() : null;
    return { status, overview };
  }, 3000);

  const ready = data?.status.state === "ready";
  const overview = data?.overview ?? null;

  // Follow the engine's event log while it runs; the engine keeps the last 5000.
  useEffect(() => {
    if (!ready) return;
    let live = true;
    const tick = async () => {
      try {
        const page = await api.webEvents(cursor.current);
        if (!live) return;
        if (page.events.length) {
          cursor.current = page.events[page.events.length - 1].seq;
          setEvents((old) => [...old, ...page.events].slice(-MAX_LOG_ENTRIES));
        }
      } catch {
        // The readiness line and the next poll surface engine problems.
      }
    };
    void tick();
    const timer = window.setInterval(() => {
      if (!document.hidden) void tick();
    }, 1500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [ready]);

  async function run(action: () => Promise<unknown>) {
    setActionError("");
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy(false);
      reload();
    }
  }

  const windows = overview?.windows ?? [];
  const injections = overview?.injections ?? [];
  const profiles = overview?.profiles ?? [];

  return <AppShell activeId="web-lab">
    <TopBar title="Web Lab" icon={<GlobeIcon size={20} />} />
    <div className="flex w-full items-start">
      <main className={panelOpen && ready ? (panelExpanded ? "hidden" : "min-w-0 flex-1 p-4 sm:p-6") : "mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6"}>
        <PageHead toolbarOnly icon={<GlobeIcon size={22} />} title="Web Lab" description="Drive a real embedded browser window, inject JavaScript before page scripts and on demand, and read what pages expose."
          actions={ready ? <button type="button" className="iux-btn" aria-pressed={panelOpen} onClick={() => setPanelOpen((open) => !open)}>Preview panel</button> : undefined} />
        {loadError && <Status value={{ ok: false, text: loadError }} />}
        {!data ? <p role="status">Loading Web Lab readiness…</p> : data.status.state !== "ready" ? <div className="mt-5"><ReadinessGate state={data.status.state} busy={busy} onStart={() => void run(() => api.webEngineStart())} /></div> : <>
          <div className="mt-5 flex flex-col gap-5">
            <Section title="Engine" description="The engine runs on this computer and listens on 127.0.0.1 only.">
              <p className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="success">Running</Badge>
                <span dir="ltr">{`v${overview?.version ?? "?"} · 127.0.0.1:${overview?.port ?? "?"}`}</span>
              </p>
              <button type="button" className="iux-btn mt-3" disabled={busy} onClick={() => void run(() => api.webEngineStop())}>Stop engine</button>
            </Section>
            {actionError && <Status value={{ ok: false, text: actionError }} />}
            <Section title="Open a window" description="The window opens on this computer and loads the address in the lab's embedded browser.">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block text-sm">
                  <span className="font-medium">Address</span>
                  <input type="text" dir="ltr" className="iux-input mt-1 w-full" value={url} spellCheck={false}
                    onChange={(event) => setUrl(event.target.value)} />
                </label>
                <label className="block text-sm">
                  <span className="font-medium">Profile</span>
                  <select className="iux-input mt-1 w-full" value={profile} onChange={(event) => setProfile(event.target.value)}>
                    {profiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                <label className="block text-sm">
                  <span className="font-medium">Viewport</span>
                  <select className="iux-input mt-1 w-full" value={viewport} onChange={(event) => setViewport(event.target.value as Viewport)}>
                    {VIEWPORTS.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                <details className="text-sm sm:col-span-2">
                  <summary className="cursor-pointer font-medium">Advanced</summary>
                  <label className="mt-2 block">
                    <span className="font-medium">User agent</span>
                    <input type="text" dir="ltr" className="iux-input mt-1 w-full" value={userAgent} spellCheck={false}
                      aria-label="User agent override, empty for the browser default" onChange={(event) => setUserAgent(event.target.value)} />
                  </label>
                </details>
              </div>
              <button type="button" className="iux-btn mt-4" data-variant="primary" disabled={busy || !url.trim()}
                onClick={() => void run(() => api.webOpenWindow({ url, profile, viewport, user_agent: userAgent || null }))}>Open window</button>
            </Section>
            <Section title="Windows" description="Every window shares the engine; closing it ends that session.">
              {windows.length ? <ul className="flex flex-col gap-2">
                {windows.map((item) => <WindowRow key={item.id} id={item.id} url={item.url} profile={item.profile} viewport={item.viewport} busy={busy}
                  onClose={() => void run(() => api.webCloseWindow(item.id))}
                  onReload={() => void run(() => api.webReload(item.id))}
                  onNavigate={(target) => void run(() => api.webNavigate(item.id, target))}
                  onCookies={() => void run(() => api.webCookies(item.id))}
                  onStorage={() => void run(() => api.webStorage(item.id))}
                  onPreview={() => { setPanelTarget(String(item.id)); setPanelOpen(true); }} />)}
              </ul> : <Empty>No windows are open.</Empty>}
            </Section>
            <Section title="Injections" description="Registered scripts run before page scripts on every navigation in windows opened afterwards.">
              {injections.length ? <ul className="flex flex-col gap-2">
                {injections.map((item) => <li key={item.id} className="rounded-md border border-(--iux-border) p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium" translate="no">{item.name}</span>
                    <Badge>{item.enabled ? "enabled" : "disabled"}</Badge>
                    <button type="button" className="iux-btn ms-auto" data-variant="ghost" disabled={busy}
                      onClick={() => void run(() => api.webDeleteInjection(item.id))}>Delete</button>
                  </div>
                  <pre className="iux-scroll mt-2 max-h-32 overflow-auto rounded bg-(--iux-muted) p-2 text-xs" translate="no">{item.code}</pre>
                </li>)}
              </ul> : <Empty>No injections are registered.</Empty>}
              <div className="mt-4 grid gap-3">
                <label className="block text-sm">
                  <span className="font-medium">Name</span>
                  <input type="text" className="iux-input mt-1 w-full" value={injectionName} onChange={(event) => setInjectionName(event.target.value)} />
                </label>
                <div className="block text-sm">
                  <span className="font-medium">Code</span>
                  <textarea className="iux-input mt-1 w-full font-mono text-xs" rows={4} spellCheck={false} dir="ltr"
                    aria-label="Code" value={injectionCode} onChange={(event) => setInjectionCode(event.target.value)} />
                </div>
                <button type="button" className="iux-btn" disabled={busy || !injectionName.trim() || !injectionCode.trim()}
                  onClick={() => void run(async () => {
                    await api.webAddInjection(injectionName.trim(), injectionCode);
                    setInjectionName("");
                    setInjectionCode("");
                  })}>Register injection</button>
              </div>
            </Section>
            <Section title="Run JavaScript" description="The code runs in the selected window; its result arrives in the event log.">
              {windows.length ? <div className="grid gap-3">
                <div className="block text-sm">
                  <span className="font-medium">Window</span>
                  <select className="iux-input mt-1 w-full" aria-label="Window" value={evalTarget} onChange={(event) => setEvalTarget(event.target.value)}>
                    <option value="">Choose a window</option>
                    {windows.map((item) => <option key={item.id} value={String(item.id)}>#{item.id} — {item.url}</option>)}
                  </select>
                </div>
                <div className="block text-sm">
                  <span className="font-medium">JavaScript code</span>
                  <textarea className="iux-input mt-1 w-full font-mono text-xs" rows={4} spellCheck={false} dir="ltr"
                    aria-label="JavaScript code" value={evalCode} onChange={(event) => setEvalCode(event.target.value)} />
                </div>
                <button type="button" className="iux-btn" data-variant="primary" disabled={busy || !evalTarget || !evalCode.trim()}
                  onClick={() => void run(() => api.webEval(Number(evalTarget), evalCode))}>Run</button>
              </div> : <Empty>Open a window to run JavaScript in it.</Empty>}
            </Section>
            <Section title="Event log" description="Captured page activity: console, errors, network, navigation and eval results. Events stay in engine memory.">
              {events.length ? <ol aria-live="polite" className="iux-scroll flex max-h-96 flex-col gap-1 overflow-auto rounded-md border border-(--iux-border) p-2 text-xs">
                {events.map((event) => <li key={event.seq} className="flex gap-2">
                  <span dir="ltr" className="w-14 shrink-0 tabular-nums text-(--iux-muted-foreground)">{event.seq}</span>
                  <Badge>{event.kind}</Badge>
                  <span className="min-w-0 flex-1 break-all" translate="no">{eventText(event)}</span>
                </li>)}
              </ol> : <Empty>No events captured yet.</Empty>}
            </Section>
          </div>
        </>}
        </main>
        {panelOpen && ready ? (
          <PreviewPanel
            windows={windows}
            targetId={panelTarget}
            onTarget={setPanelTarget}
            busy={busy}
            run={run}
            onClose={() => setPanelOpen(false)}
            expanded={panelExpanded}
            onToggleExpand={() => setPanelExpanded((v) => !v)}
          />
        ) : null}
      </div>
    </AppShell>;
}

/** Readiness gate: the backend decides what is possible; setup links to the lab page. */
function ReadinessGate({ state, busy, onStart }: { state: WebStatus["state"]; busy: boolean; onStart: () => void }) {
  if (state === "stopped") {
    return <Section title="Engine" description="The engine is built but not running on this computer.">
      <button type="button" className="iux-btn" data-variant="primary" disabled={busy} onClick={onStart}>Start engine</button>
    </Section>;
  }
  return <Section title="Readiness" description={state === "unavailable" ? "Web Lab is unavailable on this system." : "Setup is needed before use."}>
    <a className="iux-btn" href={labHref("web")}>Readiness & setup</a>
  </Section>;
}

/** One open window: identity, an inline address field and its per-window actions. */
function WindowRow({ id, url, profile, viewport, busy, onClose, onReload, onNavigate, onCookies, onStorage, onPreview }: {
  id: number; url: string; profile: string; viewport: string; busy: boolean;
  onClose: () => void; onReload: () => void; onNavigate: (url: string) => void;
  onCookies: () => void; onStorage: () => void; onPreview: () => void;
}) {
  const [target, setTarget] = useState(url);
  return <li className="rounded-md border border-(--iux-border) p-3 text-sm">
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-medium tabular-nums" dir="ltr">#{id}</span>
      <Badge>{profile}</Badge>
      <Badge>{viewport}</Badge>
      <span className="min-w-0 flex-1 break-all text-xs" dir="ltr" translate="no">{url}</span>
    </div>
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <form className="flex flex-1 gap-2" onSubmit={(event) => { event.preventDefault(); if (target.trim()) onNavigate(target); }}>
        <input type="text" dir="ltr" className="iux-input min-w-0 flex-1" value={target} spellCheck={false}
          aria-label={`Address for window ${id}`} onChange={(event) => setTarget(event.target.value)} />
        <button type="submit" className="iux-btn" disabled={busy}>Go</button>
      </form>
      <button type="button" className="iux-btn" disabled={busy} onClick={onReload}>Reload</button>
      <button type="button" className="iux-btn" disabled={busy} onClick={onCookies}>Cookies</button>
      <button type="button" className="iux-btn" disabled={busy} onClick={onStorage}>Storage</button>
      <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} onClick={onPreview}>Preview</button>
      <button type="button" className="iux-btn" data-variant="ghost" disabled={busy} onClick={onClose}>Close</button>
    </div>
  </li>;
}

const SNAPSHOT_WIDTH_CAP = 1440;

/**
 * The live preview: a docked right pane polling JPEG snapshots of one engine
 * window (view-only — interactions happen in the real window). The device
 * toggle resizes the actual engine window, so captured pages reflow to the
 * chosen size; "Fit to window" scales the image, turning it off shows the
 * pixels 1:1 with scrolling.
 */
function PreviewPanel({ windows, targetId, onTarget, busy, run, onClose, expanded, onToggleExpand }: {
  windows: WebWindowState[]; targetId: string; onTarget: (id: string) => void;
  busy: boolean; run: (action: () => Promise<unknown>) => Promise<void>; onClose: () => void;
  expanded?: boolean; onToggleExpand?: () => void;
}) {
  const [preset, setPreset] = useState<Viewport | "custom">("responsive");
  const [customWidth, setCustomWidth] = useState("");
  const [customHeight, setCustomHeight] = useState("");
  const [fit, setFit] = useState(true);
  const [shotUrl, setShotUrl] = useState<string | null>(null);
  const [shotError, setShotError] = useState("");
  const [addressInput, setAddressInput] = useState("");
  const shotRef = useRef<string | null>(null);
  const target = windows.find((item) => String(item.id) === targetId) ?? null;
  const id = target?.id ?? Number(targetId);

  useEffect(() => {
    if (!windows.length) return;
    if (!windows.some((item) => String(item.id) === targetId)) onTarget(String(windows[0].id));
  }, [windows, targetId, onTarget]);

  useEffect(() => {
    if (target?.url) setAddressInput(target.url);
  }, [target?.url, target?.id]);

  const hasTarget = Boolean(target);
  useEffect(() => {
    if (!hasTarget) return;
    let live = true;
    const grab = async () => {
      try {
        const snapshot = await api.webScreenshot(id);
        const binary = atob(snapshot.dataBase64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
        const url = URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" }));
        if (!live) {
          URL.revokeObjectURL(url);
          return;
        }
        if (shotRef.current) URL.revokeObjectURL(shotRef.current);
        shotRef.current = url;
        setShotUrl(url);
        setShotError("");
      } catch (error) {
        if (live) setShotError(errorText(error));
      }
    };
    void grab();
    const timer = window.setInterval(() => {
      if (!document.hidden) void grab();
    }, PREVIEW_INTERVAL);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [id, hasTarget]);

  useEffect(() => () => {
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
  }, []);

  const applyPreset = (next: Viewport | "custom") => {
    setPreset(next);
    if (next !== "custom") void run(() => api.webViewport(id, { viewport: next }));
  };
  const applyCustom = () => {
    const width = Number(customWidth);
    const height = Number(customHeight);
    if (width > 0 && height > 0) void run(() => api.webViewport(id, { width, height }));
  };
  const reloadPreview = () => {
    if (!target) return;
    void api.webScreenshot(target.id).then(() => undefined).catch(() => undefined);
  };

  const size = target?.size ?? null;
  return (
    <aside
      aria-label="Live preview"
      className={
        expanded
          ? "flex h-screen w-full min-w-0 flex-1 flex-col bg-(--iux-background)"
          : "sticky top-0 flex h-screen w-[28rem] xl:w-[32rem] shrink-0 flex-col border-l border-(--iux-border) bg-(--iux-background)"
      }
    >
      <header className="flex items-center gap-1 border-b border-(--iux-border) bg-(--iux-muted)/30 px-2 py-1.5 text-xs">
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {windows.map((item) => {
            const active = String(item.id) === targetId;
            let host = item.url;
            try {
              const u = new URL(item.url);
              host = u.hostname || item.url;
            } catch {}
            return (
              <div
                key={item.id}
                className={`group flex items-center gap-1.5 rounded-t border-t-2 px-2.5 py-1 transition-colors ${
                  active
                    ? "border-primary bg-(--iux-background) font-medium text-(--iux-foreground) shadow-xs"
                    : "border-transparent bg-transparent text-(--iux-muted-foreground) hover:bg-(--iux-muted)/60 hover:text-(--iux-foreground)"
                }`}
              >
                <button
                  type="button"
                  className="flex min-w-0 items-center gap-1 truncate text-left text-xs"
                  onClick={() => onTarget(String(item.id))}
                  title={item.url}
                >
                  <GlobeIcon size={12} className="shrink-0" />
                  <span className="max-w-[120px] truncate">{host}</span>
                </button>
                <button
                  type="button"
                  className="rounded p-0.5 text-(--iux-muted-foreground) hover:bg-(--iux-muted) hover:text-(--iux-foreground)"
                  title="Close"
                  aria-label="Close"
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation();
                    void run(() => api.webCloseWindow(item.id));
                  }}
                >
                  <XIcon size={10} weight="bold" />
                </button>
              </div>
            );
          })}
          <button
            type="button"
            className="inline-flex items-center justify-center rounded p-1 text-(--iux-muted-foreground) hover:bg-(--iux-muted) hover:text-(--iux-foreground)"
            title="Open window"
            aria-label="Open window"
            disabled={busy}
            onClick={() => void run(() => api.webOpenWindow({ url: "https://example.com" }))}
          >
            <PlusIcon size={13} weight="bold" />
          </button>
        </div>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          {onToggleExpand ? (
            <IconButton
              label={expanded ? "Restore panel" : "Expand panel"}
              onClick={onToggleExpand}
            >
              {expanded ? <CornersInIcon size={14} weight="bold" /> : <CornersOutIcon size={14} weight="bold" />}
            </IconButton>
          ) : null}
          <IconButton label="Close preview" onClick={onClose}>
            <XIcon size={14} weight="bold" />
          </IconButton>
        </div>
      </header>
      <div className="flex flex-col gap-2.5 border-b border-(--iux-border) p-3 text-sm">
        <div className="flex items-center gap-1.5">
          <IconButton label="Back" disabled={busy || !target} onClick={() => void run(() => api.webBack(id))}>
            <ArrowLeftIcon size={14} weight="bold" />
          </IconButton>
          <IconButton label="Forward" disabled={busy || !target} onClick={() => void run(() => api.webForward(id))}>
            <ArrowRightIcon size={14} weight="bold" />
          </IconButton>
          <IconButton label="Reload preview" disabled={busy || !target} onClick={() => { reloadPreview(); void run(() => api.webReload(id)); }}>
            <ArrowsClockwiseIcon size={14} weight="bold" />
          </IconButton>
          <form
            className="flex min-w-0 flex-1 items-center gap-1.5"
            onSubmit={(event) => {
              event.preventDefault();
              if (target && addressInput.trim()) {
                void run(() => api.webNavigate(target.id, addressInput.trim()));
              }
            }}
          >
            <input
              type="text"
              dir="ltr"
              className="iux-input min-w-0 flex-1 text-xs"
              value={addressInput}
              spellCheck={false}
              aria-label="Address"
              onChange={(event) => setAddressInput(event.target.value)}
            />
            <button type="submit" className="iux-btn px-2.5 py-1 text-xs" disabled={busy || !target}>
              Go
            </button>
          </form>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            className="iux-input py-1 text-xs"
            aria-label="Device size"
            value={preset}
            onChange={(event) => applyPreset(event.target.value as Viewport)}
          >
            {VIEWPORTS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
            <option value="custom">custom</option>
          </select>
          {preset === "custom" ? (
            <>
              <input
                type="number"
                dir="ltr"
                className="iux-input w-16 py-1 text-xs"
                aria-label="Viewport width"
                placeholder="Width"
                min={200}
                max={4000}
                value={customWidth}
                onChange={(event) => setCustomWidth(event.target.value)}
              />
              <input
                type="number"
                dir="ltr"
                className="iux-input w-16 py-1 text-xs"
                aria-label="Viewport height"
                placeholder="Height"
                min={200}
                max={4000}
                value={customHeight}
                onChange={(event) => setCustomHeight(event.target.value)}
              />
              <button
                type="button"
                className="iux-btn px-2 py-1 text-xs"
                disabled={busy || !Number(customWidth) || !Number(customHeight)}
                onClick={applyCustom}
              >
                Apply
              </button>
            </>
          ) : null}
          <label className="ms-auto flex items-center gap-1 text-xs text-(--iux-muted-foreground)">
            <input type="checkbox" checked={fit} onChange={(event) => setFit(event.target.checked)} />
            Fit to window
          </label>
        </div>
      </div>
      <div className="iux-scroll min-h-0 flex-1 overflow-auto p-4">
        {target && shotUrl ? (
          <img
            src={shotUrl}
            alt={`Live snapshot of window ${id}`}
            className={fit ? "mx-auto max-w-full" : ""}
            style={fit ? undefined : { width: Math.min(size?.[0] ?? SNAPSHOT_WIDTH_CAP, SNAPSHOT_WIDTH_CAP) }}
          />
        ) : null}
        {target && !shotUrl && !shotError ? <p role="status" className="text-xs text-(--iux-muted-foreground)">Capturing…</p> : null}
        {shotError ? <Status value={{ ok: false, text: shotError }} /> : null}
        {!target ? <Empty>Open a window to preview it here.</Empty> : null}
      </div>
      <footer className="flex items-center justify-between border-t border-(--iux-border) px-3 py-1.5 text-[11px] text-(--iux-muted-foreground)">
        <span className="max-w-[70%] truncate" dir="ltr">
          {target ? target.url : "No active window"}
        </span>
        {size ? (
          <span dir="ltr" className="tabular-nums">
            {size[0]} × {size[1]}
          </span>
        ) : null}
      </footer>
    </aside>
  );
}

/** One line per event; payloads are JSON, kept short by the engine's capture cap. */
function eventText(event: WebEvent): string {
  const payload = event.payload;
  if (payload == null) return "";
  if (typeof payload === "string") return payload;
  try {
    return JSON.stringify(payload);
  } catch {
    return String(payload);
  }
}
