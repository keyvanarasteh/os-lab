/**
 * Windows Apps Lab mirror: a draggable, resizable view of one real desktop window.
 * Input is opt-in, previewed, confirmed, and guarded by the backend arm lock.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowClockwiseIcon, CircleNotchIcon, CrosshairIcon, EyeIcon, HandIcon, PushPinIcon, XIcon
} from "@phosphor-icons/react";
import { Badge, Empty, Field, Modal, Skeleton, Status } from "../components/ui";
import {
  api, message, usePoll, type WinApp, type WinAppsInfo, type WinAuditRow, type WinControlState,
  type WinElement, type WinInputKey
} from "../lib/api";

const MIRROR_INTERVAL = 1500;
const INVENTORY_INTERVAL = 5000;
const ELEMENTS_INTERVAL = 5000;
const MIN_WIDTH = 280;
const MIN_HEIGHT = 240;
const FPS_HOVER = 5;
const FPS_IDLE = 1.2;
const INPUT_KEYS: WinInputKey[] = ["tab", "escape", "backspace", "delete", "up", "down", "left", "right", "enter"];
const MOUSE_ACTIONS = ["click", "double_click", "right_click", "scroll_up", "scroll_down"] as const;
type MouseAction = typeof MOUSE_ACTIONS[number];
const MOUSE_ACTION_LABELS: Record<MouseAction, string> = {
  click: "Click",
  double_click: "Double-click",
  right_click: "Right-click",
  scroll_up: "Scroll up",
  scroll_down: "Scroll down"
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

function hotspotStyle(element: WinElement, bounds: { width: number; height: number }) {
  return {
    left: `${(element.x / bounds.width) * 100}%`,
    top: `${(element.y / bounds.height) * 100}%`,
    width: `${(element.w / bounds.width) * 100}%`,
    height: `${(element.h / bounds.height) * 100}%`
  };
}

type PendingAction =
  | { kind: "click"; windowId: number; x: number; y: number; element?: WinElement }
  | { kind: "double_click"; windowId: number; x: number; y: number; element?: WinElement }
  | { kind: "right_click"; windowId: number; x: number; y: number; element?: WinElement }
  | { kind: "scroll"; windowId: number; x: number; y: number; deltaX: number; deltaY: number; element?: WinElement }
  | { kind: "type"; windowId: number; text: string }
  | { kind: "key"; windowId: number; key: WinInputKey };

const HEADER_END = new TextEncoder().encode("\r\n\r\n");
const LENGTH_KEY = new TextEncoder().encode("Content-Length: ");
const CRLF = new TextEncoder().encode("\r\n");

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from: number): number {
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const result = new Uint8Array(a.length + b.length);
  result.set(a);
  result.set(b, a.length);
  return result;
}

async function pumpPngStream(response: Response, onFrame: (png: Uint8Array) => void): Promise<void> {
  if (!response.body) throw new Error("The mirror stream ended");
  const reader = response.body.getReader();
  let buffer: Uint8Array<ArrayBufferLike> = new Uint8Array(0);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer = concatBytes(buffer, value);
    for (;;) {
      const lengthAt = indexOfBytes(buffer, LENGTH_KEY, 0);
      if (lengthAt < 0) break;
      const lineEnd = indexOfBytes(buffer, CRLF, lengthAt);
      const headerEnd = indexOfBytes(buffer, HEADER_END, lengthAt);
      if (lineEnd < 0 || headerEnd < 0) break;
      const length = Number(new TextDecoder().decode(buffer.slice(lengthAt + LENGTH_KEY.length, lineEnd)));
      const payloadAt = headerEnd + HEADER_END.length;
      if (!Number.isSafeInteger(length) || length < 0 || buffer.length < payloadAt + length) break;
      onFrame(buffer.slice(payloadAt, payloadAt + length));
      buffer = buffer.slice(payloadAt + length + 2);
    }
    if (buffer.length > 16_000_000) throw new Error("The mirror stream stalled");
  }
}

function labelFor(app: WinApp): string {
  const title = app.title ? ` — ${app.title.slice(0, 40)}` : "";
  return `${app.app}${title}`;
}

function auditLabel(row: WinAuditRow): string {
  const action = row.action ?? row.kind;
  const labels: Record<string, string> = {
    arm: "Arm control",
    disarm: "Disarm control",
    "panic-stop": "Panic stop",
    click: "Click",
    double_click: "Double-click",
    right_click: "Right-click",
    scroll: "Scroll",
    type: "Type text",
    key: "Press key"
  };
  return labels[action] ?? "Action";
}

export function WinAppsPanel() {
  const { data, error, reload } = usePoll<WinAppsInfo>(
    () => api.winappsApps(), INVENTORY_INTERVAL
  );
  const control = usePoll<WinControlState>(() => api.winappsControl(), 15000);
  const [windowId, setWindowId] = useState(0);
  const [float, setFloat] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [pos, setPos] = useState({ left: 0, top: 0, width: 440, height: 420 });
  const [showElements, setShowElements] = useState(false);
  const [query, setQuery] = useState("");
  const [mouseAction, setMouseAction] = useState<MouseAction>("click");
  const [searchResult, setSearchResult] = useState<{ windowId: number; query: string; hits: WinElement[] } | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [inputText, setInputText] = useState("");
  const [inputKey, setInputKey] = useState<WinInputKey>("tab");
  const [actionError, setActionError] = useState<string | null>(null);
  const [controlBusy, setControlBusy] = useState(false);
  const [shot, setShot] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  const [visible, setVisible] = useState(typeof document === "undefined" || !document.hidden);
  const [hovering, setHovering] = useState(false);
  const [streamState, setStreamState] = useState<"on" | "failed">("on");
  const shotRef = useRef<string | null>(null);
  const grabSeq = useRef(0);
  const revisionRef = useRef<string | undefined>(undefined);
  const revisionWindowRef = useRef<number | null>(null);
  const ownerRef = useRef<string>(typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID() : `winapps-${Date.now()}`);

  const windows = data?.windows ?? [];
  const selected = windows.find((window) => window.windowId === windowId) ?? windows[0] ?? null;
  const { data: elementsData, error: elementsError, reload: reloadElements } = usePoll(
    () => {
      if (!showElements || !selected) return Promise.resolve(null);
      if (revisionWindowRef.current !== selected.windowId) {
        revisionWindowRef.current = selected.windowId;
        revisionRef.current = undefined;
      }
      return api.winappsElements(selected.windowId, revisionRef.current).then((result) => {
        revisionRef.current = result.revision;
        return result;
      });
    },
    showElements && !hidden ? ELEMENTS_INTERVAL : 0,
    [showElements, hidden, selected?.windowId]
  );
  const fps = hovering ? FPS_HOVER : FPS_IDLE;
  const controlState = control.data;
  const armed = controlState?.armed === true;
  const armedByThisPanel = armed && controlState?.owner === ownerRef.current;
  const lockedByOther = armed && !armedByThisPanel;
  const elements = selected && elementsData?.windowId === selected.windowId
    ? elementsData?.elements ?? [] : [];
  const activeSearch = selected && searchResult && searchResult.windowId === selected.windowId
    && searchResult.query === query.trim() ? searchResult : null;
  const hitIds = activeSearch ? new Set(activeSearch.hits.map((element) => element.elementId)) : null;
  const visibleElements = hitIds ? elements.filter((element) => hitIds.has(element.elementId)) : elements;
  const recentActions = controlState?.recentActions ?? [];

  useEffect(() => {
    setPending(null);
    setSearchResult(null);
    setSearchError(null);
    revisionRef.current = undefined;
    revisionWindowRef.current = selected?.windowId ?? null;
  }, [selected?.windowId]);

  useEffect(() => {
    setPos((current) => current.left === 0 && current.top === 0 && typeof window !== "undefined"
      ? { ...current, left: Math.max(16, window.innerWidth - 480), top: 220 }
      : current);
  }, []);

  useEffect(() => {
    if (selected && selected.windowId !== windowId) setWindowId(selected.windowId);
  }, [selected, windowId]);

  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  useEffect(() => {
    if (!armedByThisPanel) return;
    const disarm = () => {
      void fetch("/api/labs/winapps/control", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-OSLab": "1" },
        body: JSON.stringify({ armed: false, owner: ownerRef.current }),
        keepalive: true
      }).catch(() => undefined);
    };
    window.addEventListener("pagehide", disarm);
    return () => window.removeEventListener("pagehide", disarm);
  }, [armedByThisPanel]);

  const setShotFromBytes = useCallback((png: Uint8Array) => {
    grabSeq.current += 1;
    const url = URL.createObjectURL(new Blob([png.slice().buffer as ArrayBuffer], { type: "image/png" }));
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
    shotRef.current = url;
    setShot(url);
    setShotError(null);
  }, []);

  const grab = useCallback(async () => {
    if (!selected || hidden) return;
    const sequence = ++grabSeq.current;
    try {
      const response = await fetch(api.winappsAppScreenshotUrl(selected.windowId), { cache: "no-store" });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error || `${response.status} ${response.statusText}`);
      }
      const png = new Uint8Array(await response.arrayBuffer());
      if (sequence !== grabSeq.current) return;
      setShotFromBytes(png);
    } catch (e) {
      if (sequence !== grabSeq.current) return;
      setShot(null);
      setShotError(message(e));
    }
  }, [hidden, selected?.windowId, setShotFromBytes]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
  }, []);

  useEffect(() => {
    if (!selected || hidden) return;
    setStreamState("on");
    void grab();
  }, [selected?.windowId, hidden, grab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected || hidden || streamState !== "failed") return;
    const timer = setInterval(() => {
      if (!document.hidden) void grab();
    }, MIRROR_INTERVAL);
    return () => clearInterval(timer);
  }, [selected?.windowId, hidden, streamState, grab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selected || hidden || streamState !== "on" || !visible) return;
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(api.winappsAppStreamUrl(selected.windowId, fps), {
          signal: controller.signal,
          cache: "no-store"
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { error?: string };
          throw new Error(body.error || `${response.status} ${response.statusText}`);
        }
        await pumpPngStream(response, setShotFromBytes);
        throw new Error("The mirror stream ended");
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setShot(null);
        setShotError(message(e));
        setStreamState("failed");
      }
    })();
    return () => controller.abort();
  }, [selected?.windowId, hidden, streamState, visible, fps, setShotFromBytes]);

  const searchElements = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setShowElements(true);
    setSearchError(null);
    try {
      const result = await api.winappsSearch(selected.windowId, query);
      setSearchResult({ windowId: result.windowId, query: result.query, hits: result.hits });
    } catch (e) {
      setSearchResult(null);
      setSearchError(message(e));
    }
  };

  const toggleControl = async () => {
    if (controlBusy || lockedByOther) return;
    setControlBusy(true);
    setActionError(null);
    try {
      await api.winappsControlArm(!armedByThisPanel, ownerRef.current);
      control.reload();
    } catch (e) {
      setActionError(message(e));
    } finally {
      setControlBusy(false);
    }
  };

  const panicStop = async () => {
    setControlBusy(true);
    setActionError(null);
    try {
      await api.winappsStop();
      setPending(null);
      control.reload();
    } catch (e) {
      setActionError(message(e));
    } finally {
      setControlBusy(false);
    }
  };

  const previewClick = (x: number, y: number, element?: WinElement) => {
    if (!selected || !shot) return;
    setActionError(null);
    const target = { windowId: selected.windowId, x: Math.round(x), y: Math.round(y), element };
    if (mouseAction === "scroll_up" || mouseAction === "scroll_down") {
      setPending({
        kind: "scroll", ...target, deltaX: 0, deltaY: mouseAction === "scroll_up" ? 120 : -120
      });
    } else {
      setPending({ kind: mouseAction, ...target });
    }
  };

  const confirmPending = async () => {
    if (!pending || !armedByThisPanel || controlBusy) return;
    setControlBusy(true);
    setActionError(null);
    try {
      if (pending.kind === "click") {
        await api.winappsClick({
          windowId: pending.windowId, x: pending.x, y: pending.y,
          owner: ownerRef.current, confirm: true
        });
      } else if (pending.kind === "double_click" || pending.kind === "right_click") {
        await api.winappsInput({
          windowId: pending.windowId, kind: pending.kind, x: pending.x, y: pending.y,
          owner: ownerRef.current, confirm: true
        });
      } else if (pending.kind === "scroll") {
        await api.winappsInput({
          windowId: pending.windowId, kind: "scroll", x: pending.x, y: pending.y,
          deltaX: pending.deltaX, deltaY: pending.deltaY, owner: ownerRef.current, confirm: true
        });
      } else if (pending.kind === "type") {
        await api.winappsInput({
          windowId: pending.windowId, kind: "type", text: pending.text,
          owner: ownerRef.current, confirm: true
        });
      } else {
        await api.winappsInput({
          windowId: pending.windowId, kind: "key", key: pending.key,
          owner: ownerRef.current, confirm: true
        });
      }
      setPending(null);
      control.reload();
      if (showElements) reloadElements();
    } catch (e) {
      setActionError(message(e));
      control.reload();
    } finally {
      setControlBusy(false);
    }
  };

  const hideMirror = async () => {
    if (armedByThisPanel) {
      setControlBusy(true);
      try {
        await api.winappsControlArm(false, ownerRef.current);
        control.reload();
      } catch (e) {
        setActionError(message(e));
        setControlBusy(false);
        return;
      }
      setControlBusy(false);
    }
    setPending(null);
    setHidden(true);
  };

  const startDrag = (event: React.PointerEvent) => {
    if (!float || (event.target instanceof Element && event.target.closest("button"))) return;
    event.preventDefault();
    const origin = { x: event.clientX, y: event.clientY, left: pos.left, top: pos.top };
    const move = (pointer: PointerEvent) => {
      setPos((current) => ({
        ...current,
        left: clamp(origin.left + pointer.clientX - origin.x, 0, window.innerWidth - MIN_WIDTH),
        top: clamp(origin.top + pointer.clientY - origin.y, 0, window.innerHeight - 120)
      }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const startResize = (event: React.PointerEvent) => {
    if (!float) return;
    event.preventDefault();
    event.stopPropagation();
    const origin = { x: event.clientX, y: event.clientY, width: pos.width, height: pos.height };
    const move = (pointer: PointerEvent) => {
      setPos((current) => ({
        ...current,
        width: clamp(origin.width + pointer.clientX - origin.x, MIN_WIDTH, window.innerWidth - 24),
        height: clamp(origin.height + pointer.clientY - origin.y, MIN_HEIGHT, window.innerHeight - 24)
      }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const header = (
    <div
      className={`flex items-center gap-2 border-b border-(--iux-border) px-4 py-2.5 ${float ? "cursor-move touch-none select-none" : ""}`}
      onPointerDown={startDrag}
    >
      <EyeIcon size={15} className="text-[#f36c21]" aria-hidden />
      <span className="text-sm font-semibold">App mirror</span>
      <span className="ml-auto flex items-center gap-1">
        <button
          type="button"
          className="iux-btn"
          data-variant="ghost"
          title={float ? "Dock the panel" : "Float the panel"}
          aria-label={float ? "Dock the panel" : "Float the panel"}
          onClick={() => setFloat((current) => !current)}
        >
          <PushPinIcon size={14} />
        </button>
        <button
          type="button"
          className="iux-btn"
          data-variant="ghost"
          title="Hide the app mirror"
          aria-label="Hide the app mirror"
          onClick={() => void hideMirror()}
        >
          <XIcon size={14} />
        </button>
      </span>
    </div>
  );

  const body = (
    <div className="flex flex-col gap-3">
      {error ? <Status value={{ ok: false, text: error }} /> : null}
      {control.error ? <Status value={{ ok: false, text: control.error }} /> : null}
      {actionError ? <Status value={{ ok: false, text: actionError }} /> : null}
      {elementsError ? <Status value={{ ok: false, text: elementsError }} /> : null}
      {searchError ? <Status value={{ ok: false, text: searchError }} /> : null}
      {!data ? (
        <Skeleton rows={2} />
      ) : !data.available ? (
        <Empty>{data.reason ?? "The Windows app mirror is not available here."}</Empty>
      ) : windows.length === 0 ? (
        <Empty>No visible desktop application windows were found.</Empty>
      ) : selected ? (
        <>
          <Field label="Window">
            <select
              className="iux-input"
              value={selected.windowId}
              onChange={(event) => setWindowId(Number(event.target.value))}
              aria-label="Window"
            >
              {windows.map((window) => (
                <option key={window.windowId} value={window.windowId}>{labelFor(window)}</option>
              ))}
            </select>
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="iux-btn" data-variant="outline" onClick={() => {
              reload();
              void grab();
            }}>
              <ArrowClockwiseIcon size={14} /> Refresh
            </button>
            <button type="button" className="iux-btn" data-variant={showElements ? undefined : "outline"}
              aria-pressed={showElements} onClick={() => setShowElements((current) => !current)}>
              <EyeIcon size={14} /> Elements
            </button>
            <button type="button" className={armedByThisPanel ? "iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" : "iux-btn"}
              data-variant={armedByThisPanel ? undefined : "outline"} aria-pressed={armedByThisPanel}
              disabled={controlBusy || lockedByOther} onClick={() => void toggleControl()}>
              <HandIcon size={14} /> {lockedByOther ? "Control locked" : armedByThisPanel ? "Disarm control" : "Arm control"}
            </button>
            <button type="button" className="iux-btn" data-variant="outline" disabled={controlBusy}
              title="Panic stop disarms input and ends active mirror streams"
              onClick={() => void panicStop()}>
              Panic stop
            </button>
            <Badge tone={selected.width > 0 && selected.height > 0 ? "success" : "warning"}>
              {`${selected.width}×${selected.height}`}
            </Badge>
            {selected.elevated ? <Badge tone="warning">Elevated</Badge> : null}
          </div>
          {lockedByOther ? (
            <Status value={{ ok: false, text: "Another dashboard owns the Windows app control lock." }} />
          ) : armedByThisPanel ? (
            <Status value={{ ok: true, text: "Control is armed. Actions still require preview confirmation." }} />
          ) : null}
          {showElements ? (
            <>
              <form className="flex gap-2" onSubmit={(event) => void searchElements(event)}>
                <input className="iux-input min-w-0 flex-1" value={query} maxLength={120}
                  aria-label="Search elements" placeholder="Search elements"
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setSearchResult(null);
                    setSearchError(null);
                  }} />
                <button type="submit" className="iux-btn" data-variant="outline">Search</button>
              </form>
              <p className="text-xs text-(--iux-muted-foreground)">
                {activeSearch ? <>{activeSearch.hits.length} <span>matches</span></> : <>{elements.length} <span>UI Automation elements</span></>}
                {elementsData?.trimmed ? <> · <span>UI Automation list trimmed</span></> : ""}
              </p>
            </>
          ) : null}
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Mouse action">
              <select className="iux-input" value={mouseAction} aria-label="Mouse action"
                onChange={(event) => setMouseAction(event.target.value as MouseAction)}>
                {MOUSE_ACTIONS.map((action) => (
                  <option key={action} value={action}>{MOUSE_ACTION_LABELS[action]}</option>
                ))}
              </select>
            </Field>
            <div className="flex items-end gap-2">
              <Field label="Text to type">
                <input className="iux-input" value={inputText} maxLength={200} aria-label="Text to type"
                  onChange={(event) => setInputText(event.target.value)} />
              </Field>
              <button type="button" className="iux-btn shrink-0" data-variant="outline"
                disabled={!inputText.length} onClick={() => selected && setPending({
                  kind: "type", windowId: selected.windowId, text: inputText
                })}>
                Preview text
              </button>
            </div>
            <div className="flex items-end gap-2">
              <Field label="Key to press">
                <select className="iux-input" value={inputKey} aria-label="Key to press"
                  onChange={(event) => setInputKey(event.target.value as WinInputKey)}>
                  {INPUT_KEYS.map((key) => <option key={key} value={key}>{key}</option>)}
                </select>
              </Field>
              <button type="button" className="iux-btn shrink-0" data-variant="outline"
                onClick={() => selected && setPending({ kind: "key", windowId: selected.windowId, key: inputKey })}>
                Preview key
              </button>
            </div>
          </div>
          <section aria-label="Recent actions" className="rounded-lg border border-(--iux-border) px-3 py-2">
            <p className="mb-1 text-xs font-semibold">Recent actions</p>
            {recentActions.length ? (
              <ol className="flex flex-col gap-1">
                {recentActions.slice(-6).reverse().map((row, index) => (
                  <li key={`${row.time}-${row.kind}-${index}`} className="flex items-center gap-2 text-xs">
                    <span className="min-w-0 flex-1 truncate">
                      {auditLabel(row)}{row.key ? ` · ${row.key}` : ""}{row.app ? ` · ${row.app}` : ""}
                    </span>
                    <span className={row.ok === false ? "text-(--iux-danger)" : "text-(--iux-muted-foreground)"}>
                      {row.ok === false ? "Blocked" : "Sent"}
                    </span>
                    <time dateTime={new Date(row.time * 1000).toISOString()}>
                      {new Date(row.time * 1000).toLocaleTimeString()}
                    </time>
                  </li>
                ))}
              </ol>
            ) : <p className="text-xs text-(--iux-muted-foreground)">No actions yet.</p>}
          </section>
          <div
            className="relative w-full cursor-crosshair overflow-hidden rounded-xl border border-(--iux-border) bg-black"
            style={{
              aspectRatio: `${selected.width || 4} / ${selected.height || 3}`,
              maxWidth: `calc(70vh * ${selected.width || 4} / ${selected.height || 3})`,
              marginInline: "auto"
            }}
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              if (!rect.width || !rect.height) return;
              previewClick(
                (event.clientX - rect.left) * selected.width / rect.width,
                (event.clientY - rect.top) * selected.height / rect.height
              );
            }}
            onPointerEnter={() => setHovering(true)}
            onPointerLeave={() => setHovering(false)}
          >
            {shot ? (
              <img
                src={shot}
                alt={`Mirror of ${selected.app}`}
                className="absolute inset-0 h-full w-full object-fill"
                draggable={false}
              />
            ) : shotError ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center">
                <p className="text-xs text-zinc-400">{shotError}</p>
                <button
                  type="button"
                  className="iux-btn"
                  data-variant="outline"
                  onClick={() => {
                    setStreamState("on");
                    void grab();
                  }}
                >
                  Retry
                </button>
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center" aria-busy="true">
                <CircleNotchIcon size={22} className="animate-spin text-zinc-500" aria-hidden />
              </div>
            )}
            {showElements && shot ? visibleElements.map((element, index) => (
              <button
                key={element.elementId}
                type="button"
                className={`absolute rounded-md border text-[10px] font-semibold ${
                  element.focused
                    ? "border-violet-400/80 bg-violet-400/20 text-violet-100"
                    : element.enabled
                      ? "border-[#f36c21]/80 bg-[#f36c21]/20 text-[#ffcfaa] hover:bg-[#f36c21]/40"
                      : "border-zinc-400/70 bg-zinc-400/15 text-zinc-300"
                }`}
                style={hotspotStyle(element, selected)}
                title={`${element.role}${element.label ? `: ${element.label}` : ""}`}
                aria-label={`${element.role}${element.label ? `: ${element.label}` : ""}`}
                onClick={(event) => {
                  event.stopPropagation();
                  previewClick(element.x + element.w / 2, element.y + element.h / 2, element);
                }}
              >
                {element.w > 24 && element.h > 14 ? index + 1 : null}
              </button>
            )) : null}
          </div>
          {showElements && !elements.length && !elementsError ? (
            <Empty>No UI Automation elements were returned for this window.</Empty>
          ) : null}
        </>
      ) : null}
    </div>
  );

  const actionDialog = pending ? (
    <Modal title="Review action" icon={<CrosshairIcon size={16} />}
      description="Review the target before sending input to the selected Windows window."
      onClose={() => setPending(null)}>
      <div className="flex flex-col gap-3 px-6 pb-5">
        <p className="text-sm font-medium">
          {pending.kind === "click"
            ? pending.element
              ? <><span>Click UI element</span>: {pending.element.role}{pending.element.label ? `: ${pending.element.label}` : ""}</>
              : <><span>Click at</span> <code>{pending.x}, {pending.y}</code></>
            : pending.kind === "double_click" || pending.kind === "right_click"
              ? pending.element
                ? <><span>{pending.kind === "double_click" ? "Double-click UI element" : "Right-click UI element"}</span>
                  : {pending.element.role}{pending.element.label ? `: ${pending.element.label}` : ""}</>
                : <><span>{pending.kind === "double_click" ? "Double-click at" : "Right-click at"}</span>
                  <code>{pending.x}, {pending.y}</code></>
              : pending.kind === "scroll"
                ? <><span>Scroll at</span> <code>{pending.x}, {pending.y}</code>
                  <span> ({pending.deltaY > 0 ? "up" : "down"})</span></>
                : pending.kind === "type" ? <span>Type this text into the focused control</span>
                  : <><span>Press key</span> <code>{pending.key}</code></>}
        </p>
        {pending.kind === "type" ? (
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded-md border border-(--iux-border) p-3 text-xs">{pending.text}</pre>
        ) : null}
        {pending.kind === "key" && pending.key === "enter" ? (
          <p className="text-xs text-(--iux-danger)">Enter can submit forms or send messages. Confirm only if that is intended.</p>
        ) : null}
        {!armedByThisPanel ? (
          <Status value={{ ok: false, text: lockedByOther
            ? "Another dashboard owns the Windows app control lock."
            : "Arm control before confirming this action." }} />
        ) : null}
        {actionError ? <Status value={{ ok: false, text: actionError }} /> : null}
        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={() => setPending(null)}>Cancel</button>
          <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]"
            disabled={!armedByThisPanel || controlBusy} onClick={() => void confirmPending()}>
            {controlBusy ? "Sending…" : "Confirm and send"}
          </button>
        </div>
      </div>
    </Modal>
  ) : null;

  if (hidden) {
    return (
      <section className="iux-card items-start gap-3 py-4">
        <div className="flex items-center gap-2 px-4">
          <EyeIcon size={15} className="text-[#f36c21]" aria-hidden />
          <span className="text-sm font-semibold">App mirror</span>
        </div>
        <div className="px-4">
          <button type="button" className="iux-btn" data-variant="outline" onClick={() => setHidden(false)}>
            Show the app mirror
          </button>
        </div>
      </section>
    );
  }

  return float ? (
    <div
      className="iux-card fixed z-40 flex flex-col overflow-hidden shadow-[0_18px_50px_-12px_rgba(0,0,0,0.55)]"
      style={{ left: pos.left, top: pos.top, width: pos.width, height: pos.height }}
    >
      {header}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{body}</div>
      <div
        className="absolute right-0 bottom-0 h-5 w-5 cursor-nwse-resize touch-none"
        onPointerDown={startResize}
        aria-hidden
      />
      {actionDialog}
    </div>
  ) : (
    <section className="iux-card gap-3 py-4">
      {header}
      <div className="px-4">{body}</div>
      {actionDialog}
    </section>
  );
}
