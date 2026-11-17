/**
 * Windows Apps Lab mirror: a draggable, resizable view of one real desktop window.
 * The inventory and captures are read-only; there is no input control in this phase.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowClockwiseIcon, CircleNotchIcon, EyeIcon, PushPinIcon, XIcon
} from "@phosphor-icons/react";
import { Badge, Empty, Field, Skeleton, Status } from "../components/ui";
import { api, message, usePoll, type WinApp, type WinAppsInfo } from "../lib/api";

const MIRROR_INTERVAL = 1500;
const INVENTORY_INTERVAL = 5000;
const MIN_WIDTH = 280;
const MIN_HEIGHT = 240;
const FPS_HOVER = 5;
const FPS_IDLE = 1.2;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

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

export function WinAppsPanel() {
  const { data, error, reload } = usePoll<WinAppsInfo>(
    () => api.winappsApps(), INVENTORY_INTERVAL
  );
  const [windowId, setWindowId] = useState(0);
  const [float, setFloat] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [pos, setPos] = useState({ left: 0, top: 0, width: 440, height: 420 });
  const [shot, setShot] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  const [visible, setVisible] = useState(typeof document === "undefined" || !document.hidden);
  const [hovering, setHovering] = useState(false);
  const [streamState, setStreamState] = useState<"on" | "failed">("on");
  const shotRef = useRef<string | null>(null);
  const grabSeq = useRef(0);

  const windows = data?.windows ?? [];
  const selected = windows.find((window) => window.windowId === windowId) ?? windows[0] ?? null;
  const fps = hovering ? FPS_HOVER : FPS_IDLE;

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
          onClick={() => setHidden(true)}
        >
          <XIcon size={14} />
        </button>
      </span>
    </div>
  );

  const body = (
    <div className="flex flex-col gap-3">
      {error ? <Status value={{ ok: false, text: error }} /> : null}
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
            <Badge tone={selected.width > 0 && selected.height > 0 ? "success" : "warning"}>
              {`${selected.width}×${selected.height}`}
            </Badge>
            {selected.elevated ? <Badge tone="warning">Elevated</Badge> : null}
          </div>
          <div
            className="relative w-full overflow-hidden rounded-xl border border-(--iux-border) bg-black"
            style={{
              aspectRatio: `${selected.width || 4} / ${selected.height || 3}`,
              maxWidth: `calc(70vh * ${selected.width || 4} / ${selected.height || 3})`,
              marginInline: "auto"
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
          </div>
        </>
      ) : null}
    </div>
  );

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
    </div>
  ) : (
    <section className="iux-card gap-3 py-4">
      {header}
      <div className="px-4">{body}</div>
    </section>
  );
}
