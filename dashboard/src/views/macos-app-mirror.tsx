/**
 * macOS Lab app mirror: a live, draggable view of one real app window on this Mac, with its
 * accessibility tree as numbered hotspots. Mirror and hotspot clicks preview a macos-click
 * action; arming control mode lets clicks land immediately. Everything stays localhost-only
 * and the underlying endpoints are read-only except the armed actions.
 *
 * Roadmap follow-ups (MIR-01…06): an element action menu (double, right, type, key — typing
 * never sends Return), a diff overlay that rings added and fades removed hotspots, per-display
 * scale honesty, an MJPEG stream that pauses on hidden tabs and falls back to the poll, a
 * mac2 deep-inspect mode routing actions through stable element ids, and a local audit log
 * download. docs/UX_READINESS.md applies: every state is explicit and errors sit next to the
 * control that caused them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwiseIcon, CircleNotchIcon, CrosshairIcon, DownloadSimpleIcon, EyeIcon, HandIcon,
  ListNumbersIcon, PushPinIcon, XIcon
} from "@phosphor-icons/react";
import { Badge, Empty, Field, Modal, Skeleton, Status } from "../components/ui";
import { api, message, usePoll, type LabRequest, type MacElement, type MacInputKind } from "../lib/api";

/** The mirror refreshes faster than the simulator screen; each frame is one screencapture. */
const MIRROR_INTERVAL = 1500;
const ELEMENTS_INTERVAL = 5000;
const DEEP_ELEMENTS_INTERVAL = 8000;
const MIN_WIDTH = 280;
const MIN_HEIGHT = 240;
/** Streaming frame rates: fast while the pointer is over the mirror, slow otherwise. */
const FPS_HOVER = 5;
const FPS_IDLE = 1.2;
/** The allowlisted keys of macos-app.sh input; Enter is its own explicit action. */
const INPUT_KEYS = ["tab", "escape", "delete", "forward-delete", "up", "down", "left", "right", "space", "enter"];

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

function hotspotStyle(element: MacElement, bounds: { width: number; height: number }) {
  return {
    left: `${(element.x / bounds.width) * 100}%`,
    top: `${(element.y / bounds.height) * 100}%`,
    width: `${(element.w / bounds.width) * 100}%`,
    height: `${(element.h / bounds.height) * 100}%`
  };
}

const frameKey = (element: MacElement) =>
  JSON.stringify([element.role, element.label, element.x, element.y, element.w, element.h]);

// ── MJPEG reader (MIR-04): the console writes --frame headers + Content-Length + a PNG ──

const HEADER_END = new TextEncoder().encode("\r\n\r\n");
const LENGTH_KEY = new TextEncoder().encode("Content-Length: ");
const CRLF = new TextEncoder().encode("\r\n");

function indexOfBytes(hay: Uint8Array, needle: Uint8Array, from: number): number {
  outer: for (let i = from; i <= hay.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (hay[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
}

async function pumpMjpeg(res: Response, onFrame: (png: Uint8Array) => void): Promise<void> {
  const reader = res.body!.getReader();
  let buf: Uint8Array = new Uint8Array(0);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buf = concatBytes(buf, value);
    for (;;) {
      const keyAt = indexOfBytes(buf, LENGTH_KEY, 0);
      if (keyAt < 0) break;
      const lineEnd = indexOfBytes(buf, CRLF, keyAt);
      const headAt = indexOfBytes(buf, HEADER_END, keyAt);
      if (lineEnd < 0 || headAt < 0) break;
      const length = Number(new TextDecoder().decode(buf.slice(keyAt + LENGTH_KEY.length, lineEnd)));
      const payloadAt = headAt + HEADER_END.length;
      if (!Number.isFinite(length) || buf.length < payloadAt + length) break;
      onFrame(buf.slice(payloadAt, payloadAt + length));
      buf = buf.slice(payloadAt + length + 2); // the trailing \r\n
    }
    if (buf.length > 16_000_000) throw new Error("The mirror stream stalled");
  }
}

type MenuState = { x: number; y: number; pid: number; gx: number; gy: number; element?: MacElement };
type DeepSession = { bundleId: string; sessionId: string; app: string };

export function MacAppPanel({ onPreview, onHide }: { onPreview: (action: string, extra?: Partial<LabRequest>) => void; onHide: () => void }) {
  const { data, error } = usePoll(() => api.macosApps(), 5000);
  const control = usePoll(() => api.macosControl(), 15000);
  const audit = usePoll(() => api.macosAudit(), 15000);
  const [windowId, setWindowId] = useState(0);
  const [float, setFloat] = useState(true);
  const [pos, setPos] = useState({ left: 0, top: 0, width: 440, height: 420 });
  const [showElements, setShowElements] = useState(false);
  const [shot, setShot] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [dialog, setDialog] = useState<"type" | "key" | "paste" | "value" | null>(null);
  const [visible, setVisible] = useState(typeof document === "undefined" || !document.hidden);
  const [hovering, setHovering] = useState(false);
  const [streamState, setStreamState] = useState<"on" | "failed">("on");
  const [deep, setDeep] = useState<DeepSession | null>(null);
  const [deepBusy, setDeepBusy] = useState(false);
  const [deepError, setDeepError] = useState<string | null>(null);
  const mirrorRef = useRef<HTMLDivElement | null>(null);
  const shotRef = useRef<string | null>(null);
  const revisionRef = useRef<string | undefined>(undefined);
  const pressTimer = useRef<number | null>(null);
  const menuOpened = useRef(false);
  // This panel's identity for the single-owner input lock (MIR-11).
  const ownerRef = useRef<string>(typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `panel-${Date.now()}`);

  const windows = data?.windows ?? [];
  const selected = windows.find((w) => w.windowId === windowId) ?? windows[0] ?? null;
  const armed = control.data?.armed ?? false;
  const fps = hovering ? FPS_HOVER : FPS_IDLE;

  useEffect(() => {
    // First placement: near the panel's corner without covering the page head.
    setPos((p) => (p.left === 0 && p.top === 0 && typeof window !== "undefined"
      ? { ...p, left: Math.max(16, window.innerWidth - 480), top: 220 } : p));
  }, []);

  // Pick the first window when the selection disappears (app quit, window closed).
  useEffect(() => {
    if (selected && selected.windowId !== windowId) setWindowId(selected.windowId);
  }, [selected, windowId]);

  // Tab visibility pauses the stream (MIR-04); the poll already skips hidden tabs.
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  const setShotFromBytes = useCallback((png: Uint8Array) => {
    const url = URL.createObjectURL(new Blob([png.slice().buffer as ArrayBuffer], { type: "image/png" }));
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
    shotRef.current = url;
    setShot(url);
    setShotError(null);
  }, []);

  /** The one-shot capture: the stream's fallback (MIR-04) and the Refresh button. */
  const grab = useCallback(async () => {
    if (!selected) return;
    try {
      const res = await fetch(api.macosAppScreenshotUrl(selected.windowId), { cache: "no-store" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error || `${res.status} ${res.statusText}`);
      }
      setShotFromBytes(new Uint8Array(await res.arrayBuffer()));
    } catch (e) {
      setShot(null);
      setShotError(message(e));
    }
  }, [selected?.windowId, setShotFromBytes]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
  }, []);
  useEffect(() => {
    if (!selected) {
      setShot(null);
      setShotError(null);
      setStreamState("on");
      return;
    }
    revisionRef.current = undefined;
    void grab();
    // The fallback poll (MIR-04): the 1.5 s screenshot cadence when the stream failed.
    const timer = streamState === "failed"
      ? setInterval(() => {
          if (!document.hidden) void grab();
        }, MIRROR_INTERVAL)
      : undefined;
    return () => clearInterval(timer);
  }, [selected?.windowId, streamState, grab]); // eslint-disable-line react-hooks/exhaustive-deps

  // The streaming mirror (MIR-04): one multipart MJPEG response; the fetch is aborted on
  // hidden tabs, fps changes or panel close, and falls back to the poll on stream errors.
  useEffect(() => {
    if (!selected || streamState !== "on" || !visible) return;
    const controller = new AbortController();
    (async () => {
      try {
        const res = await fetch(api.macosAppStreamUrl(selected.windowId, fps), { signal: controller.signal, cache: "no-store" });
        if (!res.ok || !res.body) {
          const body = (await res.json().catch(() => ({}))) as { error?: string };
          throw new Error(body.error || `${res.status} ${res.statusText}`);
        }
        await pumpMjpeg(res, setShotFromBytes);
        throw new Error("The mirror stream ended");
      } catch (e) {
        if ((e as Error).name === "AbortError") return; // paused or switched; the next run resumes
        setShot(null);
        setShotError(message(e));
        setStreamState("failed");
      }
    })();
    return () => controller.abort();
  }, [selected?.windowId, streamState, visible, fps, setShotFromBytes]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Deep inspect (MIR-05): one mac2 session for the selected app, closed on every exit ──
  const closeDeep = useCallback((bundle?: string) => {
    setDeep((current) => {
      if (current && (!bundle || current.bundleId === bundle)) {
        void api.macosSessionClose(current.bundleId).catch(() => undefined);
        return null;
      }
      return current;
    });
  }, []);
  useEffect(() => {
    if (!armed && deep) closeDeep(); // disarming (or its ten-minute expiry) closes the session
  }, [armed, deep, closeDeep]);
  useEffect(() => {
    if (deep && selected && deep.app !== selected.app) closeDeep(deep.bundleId);
  }, [selected?.app, deep, closeDeep]);
  useEffect(() => {
    // Tab unload must not leave the session dangling; keepalive is best effort.
    const close = () => {
      if (deep) void fetch(`/api/labs/macos/session/${encodeURIComponent(deep.bundleId)}`,
        { method: "DELETE", headers: { "X-OSLab": "1" }, keepalive: true }).catch(() => undefined);
    };
    window.addEventListener("pagehide", close);
    return () => window.removeEventListener("pagehide", close);
  }, [deep?.bundleId]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: deepData, error: deepError2 } = usePoll(
    () => (deep && armed ? api.macosSessionElements(deep.bundleId) : Promise.resolve(null)),
    deep && armed ? DEEP_ELEMENTS_INTERVAL : 0,
    [deep?.bundleId, armed]
  );

  // Accessibility elements carrying the previous revision, so the console returns a diff (MIR-02).
  const { data: elementsData } = usePoll(
    () => (showElements && selected && !deep
      ? api.macosElements(selected.windowId, revisionRef.current).then((r) => {
          revisionRef.current = r.revision;
          return r;
        })
      : Promise.resolve(null)),
    showElements && !deep ? ELEMENTS_INTERVAL : 0,
    [showElements, selected?.windowId, !!deep]
  );
  const elements = deepData?.elements ?? elementsData?.elements ?? [];
  // Deep-inspect elements are window-relative, so the mirror box stays the window's own bounds.
  const bounds = deep
    ? (selected ? { x: selected.x, y: selected.y, width: selected.width, height: selected.height } : null)
    : elementsData?.bounds ?? (selected ? { x: selected.x, y: selected.y, width: selected.width, height: selected.height } : null);
  const diff = elementsData?.diff;
  const deepReadError = deepError ?? deepError2;

  const clickAt = (pid: number, gx: number, gy: number, elementId?: string) => {
    setActionError(null);
    if (deep && elementId && armed) {
      void api.macosSessionAction(deep.bundleId, { kind: "click", elementId })
        .catch((e) => {
          setActionError(message(e));
          void control.reload();
        });
    } else if (armed) {
      void api.macosClick(pid, Math.round(gx), Math.round(gy))
        .catch((e) => {
          setActionError(message(e));
          void control.reload();
        });
    } else if (deep && elementId) {
      onPreview("macos-element", { elementSession: deep.sessionId, elementId, elementKind: "click", elementBundle: deep.bundleId });
    } else {
      onPreview("macos-click", { clickPid: pid, clickX: Math.round(gx), clickY: Math.round(gy) });
    }
  };

  /** One advertised AX action on a menu element (MIR-07): previewed, or armed-immediate. */
  const runElementAction = (m: MenuState, action: string) => {
    const element = m.element;
    if (!selected || !element?.path) return;
    setActionError(null);
    if (armed) {
      void api.macosAxPerform({ pid: m.pid, path: element.path, identity: element.identity, action, windowId: selected.windowId })
        .catch((e) => setActionError(message(e)));
    } else {
      onPreview("macos-perform", { elementPid: m.pid, elementWindowId: selected.windowId, elementPath: element.path, elementIdentity: element.identity, axAction: action });
    }
  };

  /** The MIR-01 input family through the same preview → confirm (or armed) pipeline. */
  const runInputAt = (at: { pid: number; gx: number; gy: number }, kind: MacInputKind, payload?: { text?: string; key?: string; confirm?: boolean }) => {
    if (!selected) return;
    setActionError(null);
    if (armed) {
      void api.macosInput({ pid: at.pid, x: Math.round(at.gx), y: Math.round(at.gy), kind, text: payload?.text, key: payload?.key, owner: ownerRef.current, confirm: payload?.confirm })
        .catch((e) => {
          setActionError(message(e));
          void control.reload();
        });
    } else {
      onPreview("macos-input", { clickPid: at.pid, clickX: Math.round(at.gx), clickY: Math.round(at.gy), inputKind: kind, inputText: payload?.text, inputKey: payload?.key });
    }
  };

  const mirrorPoint = (clientX: number, clientY: number) => {
    if (!selected || !mirrorRef.current) return null;
    const rect = mirrorRef.current.getBoundingClientRect();
    const scale = selected.width / rect.width;
    return {
      gx: selected.x + (clientX - rect.left) * scale,
      gy: selected.y + (clientY - rect.top) * scale,
      px: clientX,
      py: clientY
    };
  };

  const openMenu = (clientX: number, clientY: number, element?: MacElement) => {
    const point = mirrorPoint(clientX, clientY);
    if (!point || !selected) return;
    menuOpened.current = true;
    setMenu({ x: point.px, y: point.py, pid: selected.pid, gx: point.gx, gy: point.gy, element });
  };

  // Long-press on a hotspot opens the action menu; a short press stays the plain click.
  const hotspotPressDown = (e: React.PointerEvent) => {
    e.stopPropagation(); // the mirror box must not turn this into a plain click
    if (pressTimer.current) window.clearTimeout(pressTimer.current);
    if (e.pointerType !== "mouse") {
      const start = { x: e.clientX, y: e.clientY };
      const cancel = (ev: PointerEvent) => {
        if (Math.abs(ev.clientX - start.x) > 8 || Math.abs(ev.clientY - start.y) > 8) disarmPress();
      };
      pressTimer.current = window.setTimeout(() => {
        pressTimer.current = null;
        openMenu(e.clientX, e.clientY);
      }, 600);
      window.addEventListener("pointermove", cancel, { once: true });
    }
  };
  const disarmPress = () => {
    if (pressTimer.current) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  };

  const mirrorClick = (e: React.PointerEvent) => {
    if (!selected || !mirrorRef.current) return;
    const point = mirrorPoint(e.clientX, e.clientY);
    if (point) clickAt(selected.pid, point.gx, point.gy);
  };

  const toggleDeep = () => {
    if (deep) {
      closeDeep();
      return;
    }
    if (!selected || !armed) return;
    setDeepBusy(true);
    setDeepError(null);
    void api.macosSessionOpen({ app: selected.app })
      .then((s) => {
        setDeep({ bundleId: s.bundleId, sessionId: s.sessionId, app: selected.app });
        setShowElements(true);
      })
      .catch((e) => setDeepError(message(e)))
      .finally(() => setDeepBusy(false));
  };

  const hidePanel = () => {
    if (deep) void api.macosSessionClose(deep.bundleId).catch(() => undefined);
    onHide();
  };

  const startDrag = (e: React.PointerEvent) => {
    if (!float) return;
    e.preventDefault();
    const origin = { x: e.clientX, y: e.clientY, left: pos.left, top: pos.top };
    const move = (ev: PointerEvent) => {
      setPos((p) => ({
        ...p,
        left: clamp(origin.left + ev.clientX - origin.x, 0, window.innerWidth - MIN_WIDTH),
        top: clamp(origin.top + ev.clientY - origin.y, 0, window.innerHeight - 120)
      }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const startResize = (e: React.PointerEvent) => {
    if (!float) return;
    e.preventDefault();
    e.stopPropagation();
    const origin = { x: e.clientX, y: e.clientY, width: pos.width, height: pos.height };
    const move = (ev: PointerEvent) => {
      setPos((p) => ({
        ...p,
        width: clamp(origin.width + ev.clientX - origin.x, MIN_WIDTH, window.innerWidth - 24),
        height: clamp(origin.height + ev.clientY - origin.y, MIN_HEIGHT, window.innerHeight - 24)
      }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const auditRows = audit.data?.rows ?? [];
  const addedKeys = useMemo(() => new Set((diff?.added ?? []).map(frameKey)), [diff]);
  const changedKeys = useMemo(() => new Set((diff?.changed ?? []).map(frameKey)), [diff]);

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="iux-btn" data-variant="outline" onClick={() => void grab()} disabled={!selected}>
        <ArrowClockwiseIcon size={14} /> Refresh
      </button>
      <button type="button" className="iux-btn" data-variant="outline" aria-pressed={showElements}
        onClick={() => setShowElements((s) => !s)} disabled={!selected}>
        <EyeIcon size={14} /> Elements
      </button>
      <button
        type="button"
        className={deep ? "iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" : "iux-btn"}
        data-variant={deep ? undefined : "outline"}
        aria-pressed={!!deep}
        onClick={toggleDeep}
        disabled={!selected || (!armed && !deep) || deepBusy}
        title={armed ? "Open one mac2 session for this app; hotspot actions then use stable element ids" : "Arm control mode to open a deep-inspect session"}
      >
        <CrosshairIcon size={14} /> {deepBusy ? "Opening…" : "Deep inspect"}
      </button>
      <button
        type="button"
        className={armed ? "iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" : "iux-btn"}
        data-variant={armed ? undefined : "outline"}
        aria-pressed={armed}
        onClick={() => void api.macosControlArm(!armed, ownerRef.current).then(() => control.reload()).catch((e) => setActionError(message(e)))}
      >
        <HandIcon size={14} /> {armed ? "Disarm" : "Arm control"}
      </button>
      <button
        type="button" className="iux-btn" data-variant="outline"
        title="Stop everything now: disarm, close deep-inspect sessions, end streams"
        onClick={() => void api.macosStop().then(() => {
          control.reload();
          setDeep(null);
        }).catch((e) => setActionError(message(e)))}
      >
        Stop
      </button>
      <a
        className="iux-btn ml-auto" data-variant="ghost"
        href={api.macosAuditUrl} download="macos-audit.json"
        title="Download the local audit log: one JSON row per action with frame thumbnails"
      >
        <ListNumbersIcon size={14} /> Audit{auditRows.length ? ` (${auditRows.length})` : ""}
        <DownloadSimpleIcon size={12} />
      </a>
    </div>
  );

  const mirror = bounds ? (
    <div className="flex flex-col gap-2">
      <div
        ref={mirrorRef}
        className="relative w-full cursor-crosshair overflow-hidden rounded-xl border border-(--iux-border) bg-black"
        style={{ aspectRatio: `${bounds.width} / ${bounds.height}` }}
        onPointerDown={mirrorClick}
        onPointerEnter={() => setHovering(true)}
        onPointerLeave={() => setHovering(false)}
        onContextMenu={(e) => {
          e.preventDefault();
          openMenu(e.clientX, e.clientY);
        }}
      >
        {shot ? (
          <img src={shot} alt={`Mirror of ${selected?.app ?? "the app"}`} className="absolute inset-0 h-full w-full object-fill" draggable={false} />
        ) : shotError ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center">
            <p className="text-xs text-zinc-400">{shotError}</p>
            <button type="button" className="iux-btn" data-variant="outline" onClick={() => {
              setStreamState("on");
              void grab();
            }}>Retry</button>
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center" aria-busy="true">
            <CircleNotchIcon size={22} className="animate-spin text-zinc-500" aria-hidden />
          </div>
        )}
        {showElements && shot
          ? elements.map((element, i) => {
              const key = frameKey(element);
              const added = addedKeys.has(key);
              const changed = changedKeys.has(key);
              return (
                <button
                  key={`${element.elementId ?? "ax"}-${key}-${i}`}
                  type="button"
                  className={`absolute flex items-center justify-center rounded-md text-[10px] font-semibold ${
                    added ? "border border-emerald-400/80 bg-emerald-400/15 text-emerald-200 ring-2 ring-emerald-400/60"
                      : changed ? "border border-dashed border-amber-400/80 bg-amber-400/15 text-amber-200"
                        : element.focused ? "border border-violet-400/80 bg-violet-400/15 text-violet-200"
                          : "border border-[#f36c21]/70 bg-[#f36c21]/15 text-[#ffb27a] hover:bg-[#f36c21]/35"}`}
                  style={hotspotStyle(element, bounds)}
                  title={`${element.role}${element.label ? `: ${element.label}` : ""}`
                    + `${element.value ? ` — ${element.value.slice(0, 60)}` : ""}`
                    + `${element.actions?.length ? ` · ${element.actions.slice(0, 3).join(", ")}` : ""}`}
                  aria-label={`${i + 1}${element.label ? `: ${element.label}` : `: ${element.role}`}`}
                  onPointerDown={hotspotPressDown}
                  onPointerUp={disarmPress}
                  onPointerLeave={disarmPress}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    openMenu(e.clientX, e.clientY, element);
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (menuOpened.current) {
                      menuOpened.current = false; // the long-press already opened the menu
                      return;
                    }
                    clickAt(selected?.pid ?? 0, bounds.x + element.x + element.w / 2, bounds.y + element.y + element.h / 2, element.elementId);
                  }}
                >
                  {element.w > 24 && element.h > 14 ? i + 1 : null}
                </button>
              );
            })
          : null}
        {showElements && shot
          ? (diff?.removed ?? []).map((element, i) => (
              <span
                key={`gone-${i}-${frameKey(element)}`}
                className="pointer-events-none absolute rounded-md border border-dashed border-zinc-400/50 opacity-50"
                style={hotspotStyle(element, bounds)}
                aria-hidden
              />
            ))
          : null}
      </div>
      {showElements && diff && (diff.added.length || diff.changed.length || diff.removed.length) ? (
        <p className="text-xs text-(--iux-muted-foreground)">
          {`Last refresh: ${diff.added.length} new · ${diff.changed.length} moved · ${diff.removed.length} gone.`}
        </p>
      ) : null}
      {showElements && elementsData ? (
        <p className="text-xs text-(--iux-muted-foreground)">
          {elementsData.engine === "ax-helper"
            ? `Engine: native AX (values, focus and actions${elementsData.trimmed ? " · list trimmed" : ""}).`
            : "Engine: osascript fallback (run Build AX helper for values and actions)."}
        </p>
      ) : null}
      {showElements && !elements.length ? (
        <p className="text-xs text-(--iux-muted-foreground)">No UI elements found for this window yet.</p>
      ) : null}
      {deep ? (
        <p className="text-xs text-(--iux-muted-foreground)">
          {`${deep.bundleId}${deepData?.elements ? ` · ${deepData.elements.length}` : ""}`}
          <br />
          {"Deep inspect routes hotspot actions through mac2 element ids for this app."}
          <br />
          {"The session closes when the panel hides, the tab unloads, control disarms or the app quits."}
        </p>
      ) : null}
      {deepReadError ? <Status value={{ ok: false, text: deepReadError }} /> : null}
    </div>
  ) : null;

  const actionMenu = menu ? (
    <div className="fixed inset-0 z-50" onPointerDown={() => setMenu(null)} onContextMenu={(e) => e.preventDefault()}>
      <div
        className="iux-card absolute z-50 flex w-44 flex-col gap-0.5 p-1"
        style={{ left: clamp(menu.x, 8, window.innerWidth - 190), top: clamp(menu.y, 8, window.innerHeight - 190) }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <button type="button" className="iux-btn text-left" data-variant="ghost"
          onClick={() => { const m = menu; setMenu(null); runInputAt(m, "double"); }}>
          Double-click
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost"
          onClick={() => { const m = menu; setMenu(null); runInputAt(m, "right"); }}>
          Right-click
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost" onClick={() => setDialog("type")}>
          Type text…
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost" onClick={() => setDialog("key")}>
          Press a key…
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost" onClick={() => setDialog("paste")}>
          Paste text…
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost"
          onClick={() => { const m = menu; setMenu(null); runInputAt(m, "scroll", { text: "up:3" }); }}>
          Scroll up here
        </button>
        <button type="button" className="iux-btn text-left" data-variant="ghost"
          onClick={() => { const m = menu; setMenu(null); runInputAt(m, "scroll", { text: "down:3" }); }}>
          Scroll down here
        </button>
        {menu.element?.path ? (
          <button type="button" className="iux-btn text-left" data-variant="ghost" onClick={() => setDialog("value")}>
            Set value…
          </button>
        ) : null}
        {(menu.element?.actions ?? []).slice(0, 3).map((action) => (
          <button key={action} type="button" className="iux-btn text-left" data-variant="ghost"
            title={`Perform ${action} on this element through the AX helper`}
            onClick={() => { const m = menu; setMenu(null); runElementAction(m, action); }}>
            {action.replace("AX", "")}
          </button>
        ))}
        <p className="px-2 pt-1 text-[10px] text-(--iux-muted-foreground)">
          {armed ? "Runs immediately (armed)." : "Previews a macos-input action first."}
        </p>
      </div>
    </div>
  ) : null;

  const body = (
    <div className="flex flex-col gap-3">
      {error ? <Status value={{ ok: false, text: error }} /> : null}
      {actionError ? <Status value={{ ok: false, text: actionError }} /> : null}
      {data && !data.available ? (
        <Empty>{data.reason ?? "The app mirror is not available here."}</Empty>
      ) : !data ? (
        <Skeleton rows={2} />
      ) : (
        <>
          {data.screenRecording ? null : (
            <p className="text-xs text-(--iux-warning)">
              Window titles and captures need Screen Recording permission for the console
              (System Settings › Privacy & Security).
            </p>
          )}
          {windows.length ? (
            <>
              <Field label="Window">
                <select
                  className="iux-input"
                  value={selected?.windowId ?? 0}
                  onChange={(e) => setWindowId(Number(e.target.value))}
                  aria-label="Window"
                >
                  {windows.map((w) => (
                    <option key={w.windowId} value={w.windowId}>
                      {w.app}{w.title ? ` — ${w.title.slice(0, 40)}` : ""}{w.scale !== 1 ? ` · ${w.scale}×` : ""}
                    </option>
                  ))}
                </select>
              </Field>
              {mirror}
              {toolbar}
              {armed ? (
                <p className="text-xs text-(--iux-warning)">
                  Armed — mirror clicks run immediately on this Mac. Control disarms itself after ten minutes.
                </p>
              ) : (
                <p className="text-xs text-(--iux-muted-foreground)">
                  Clicks on the mirror preview a macos-click action first. Right-click or long-press for the
                  action menu; typed text never sends Return.
                </p>
              )}
            </>
          ) : (
            <Empty>No visible app windows right now.</Empty>
          )}
        </>
      )}
    </div>
  );

  const header = (
    <div
      className={`flex items-center gap-2 border-b border-(--iux-border) px-4 py-2.5 ${float ? "cursor-move touch-none select-none" : ""}`}
      onPointerDown={startDrag}
    >
      <EyeIcon size={15} className="text-[#f36c21]" aria-hidden />
      <span className="text-sm font-semibold">App mirror</span>
      {armed ? <Badge tone="warning">Armed</Badge> : null}
      {deep ? <Badge>mac2</Badge> : null}
      <span className="ml-auto flex items-center gap-1">
        <button
          type="button"
          className="iux-btn" data-variant="ghost"
          title={float ? "Dock the panel" : "Float the panel"}
          aria-label={float ? "Dock the app mirror panel" : "Float the app mirror panel"}
          onClick={() => setFloat((f) => !f)}
        >
          <PushPinIcon size={14} />
        </button>
        <button
          type="button"
          className="iux-btn" data-variant="ghost"
          title="Hide the app mirror"
          aria-label="Hide the app mirror"
          onClick={hidePanel}
        >
          <XIcon size={14} />
        </button>
      </span>
    </div>
  );

  return (
    <>
      {!float ? (
        <section className="iux-card gap-3 py-4">
          {header}
          <div className="px-4">{body}</div>
        </section>
      ) : (
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
        </div>
      )}
      {actionMenu}
      {dialog === "type" ? (
        <TypeDialog armed={armed} onClose={() => setDialog(null)} onRun={(text) => {
          setDialog(null);
          if (menu) runInputAt(menu, "type", { text });
        }} />
      ) : null}
      {dialog === "key" ? (
        <KeyDialog armed={armed} onClose={() => setDialog(null)} onRun={(key, confirm) => {
          setDialog(null);
          if (menu) runInputAt(menu, "key", { key, confirm });
        }} />
      ) : null}
      {dialog === "paste" ? (
        <PasteDialog armed={armed} onClose={() => setDialog(null)} onRun={(text) => {
          setDialog(null);
          if (menu) runInputAt(menu, "paste", { text, confirm: true });
        }} />
      ) : null}
      {dialog === "value" ? (
        <SetValueDialog armed={armed} onClose={() => setDialog(null)} onRun={(value) => {
          setDialog(null);
          const element = menu?.element;
          if (!selected || !element?.path) return;
          setActionError(null);
          if (armed) {
            void api.macosAxSet({ pid: menu!.pid, path: element.path, identity: element.identity, value, windowId: selected.windowId })
              .catch((e) => setActionError(message(e)));
          } else {
            onPreview("macos-set-value", { elementPid: menu!.pid, elementWindowId: selected.windowId, elementPath: element.path, elementIdentity: element.identity, elementValue: value });
          }
        }} />
      ) : null}
    </>
  );
}

/** The MIR-01 type dialog: the text is echoed before it runs and Return is never sent. */
function TypeDialog({ armed, onClose, onRun }: { armed: boolean; onClose: () => void; onRun: (text: string) => void }) {
  const [text, setText] = useState("");
  const valid = text.length > 0 && text.length <= 200 && !/[^\x20-\x7E]/.test(text);
  return (
    <Modal title="Type text" icon={<CrosshairIcon size={16} />}
      description="Typed characters go to the focused element of the app. Return is never sent by a type action — use Press a key… for Enter."
      onClose={onClose}>
      <div className="flex flex-col gap-3 px-6 pb-5">
        <Field label="Text (1–200 printable characters)">
          <input className="iux-input" value={text} maxLength={200} autoFocus
            onChange={(e) => setText(e.target.value)} aria-label="Text to type" />
        </Field>
        <p className="text-xs text-(--iux-muted-foreground)">
          {valid
            ? `Will type ${text.length} character${text.length === 1 ? "" : "s"}: “${text.slice(0, 60)}${text.length > 60 ? "…" : ""}” — no Return.`
            : "The text must be 1–200 printable characters."}
        </p>        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={onClose}>Cancel</button>
          <button type="button" className="iux-btn" disabled={!valid} onClick={() => onRun(text)}>
            {armed ? "Run now (armed)" : "Preview"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** The MIR-01 key dialog: one allowlisted key; Enter is submit-class and confirms explicitly. */
function KeyDialog({ armed, onClose, onRun }: { armed: boolean; onClose: () => void; onRun: (key: string, confirm?: boolean) => void }) {
  const [key, setKey] = useState("tab");
  const submit = key === "enter" || key === "return";
  return (
    <Modal title="Press a key" icon={<CrosshairIcon size={16} />}
      description="One key press from the allowlist goes to the focused element of the app."
      onClose={onClose}>
      <div className="flex flex-col gap-3 px-6 pb-5">
        <Field label="Key">
          <select className="iux-input" value={key} onChange={(e) => setKey(e.target.value)} aria-label="Key to press">
            {INPUT_KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </Field>
        <p className="text-xs text-(--iux-muted-foreground)">
          {`Will press the ${key} key.`}
          {submit ? " Enter can submit forms or send messages — it asks for an explicit confirmation, even while armed." : ""}
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={onClose}>Cancel</button>
          <button type="button" className="iux-btn" onClick={() => onRun(key, submit)}>
            {submit ? "Confirm & press" : armed ? "Run now (armed)" : "Preview"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** The MIR-07 paste dialog: pastes may carry newlines and always confirm (MIR-11). */
function PasteDialog({ armed, onClose, onRun }: { armed: boolean; onClose: () => void; onRun: (text: string) => void }) {
  const [text, setText] = useState("");
  const valid = text.length > 0 && text.length <= 2000;
  return (
    <Modal title="Paste text" icon={<CrosshairIcon size={16} />}
      description="The text goes to the clipboard and is pasted at the chosen point. The clipboard is replaced, and pastes always ask for confirmation."
      onClose={onClose}>
      <div className="flex flex-col gap-3 px-6 pb-5">
        <Field label="Text (1–2000 characters, newlines allowed)">
          <textarea className="iux-input" value={text} maxLength={2000} rows={4} autoFocus
            onChange={(e) => setText(e.target.value)} aria-label="Text to paste" />
        </Field>
        <p className="text-xs text-(--iux-muted-foreground)">
          {valid ? `Will paste ${text.length} characters (the clipboard is replaced).` : "The text must be 1–2000 characters."}
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={onClose}>Cancel</button>
          <button type="button" className="iux-btn" disabled={!valid} onClick={() => onRun(text)}>
            Confirm & paste
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** The MIR-07 set-value dialog: writes straight into a settable AX element. */
function SetValueDialog({ armed, onClose, onRun }: { armed: boolean; onClose: () => void; onRun: (value: string) => void }) {
  const [value, setValue] = useState("");
  const valid = value.length > 0 && value.length <= 2000 && !/[\r\n]/.test(value);
  return (
    <Modal title="Set element value" icon={<CrosshairIcon size={16} />}
      description="Writes the value straight into this element through the AX helper (settable elements only). No Return is sent."
      onClose={onClose}>
      <div className="flex flex-col gap-3 px-6 pb-5">
        <Field label="Value (1–2000 characters, no Return)">
          <input className="iux-input" value={value} maxLength={2000} autoFocus
            onChange={(e) => setValue(e.target.value)} aria-label="Value to set" />
        </Field>
        <p className="text-xs text-(--iux-muted-foreground)">
          {valid ? `Will write ${value.length} characters into the element${armed ? " now (armed)" : " (previewed)"}.`
            : "The value must be 1–2000 characters without Return."}
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" className="iux-btn" data-variant="outline" onClick={onClose}>Cancel</button>
          <button type="button" className="iux-btn" disabled={!valid} onClick={() => onRun(value)}>
            {armed ? "Run now (armed)" : "Preview"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Reopen affordance shown where the floating panel used to sit. */
export function MacAppMirrorTeaser({ onOpen }: { onOpen: () => void }) {
  return (
    <section className="iux-card items-start gap-3 py-4">
      <div className="flex items-center gap-2 px-4">
        <EyeIcon size={15} className="text-[#f36c21]" aria-hidden />
        <span className="text-sm font-semibold">App mirror</span>
      </div>
      <div className="px-4">
        <button type="button" className="iux-btn" data-variant="outline" onClick={onOpen}>
          Show the app mirror
        </button>
      </div>
    </section>
  );
}
