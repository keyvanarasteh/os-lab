/**
 * Windows Apps Lab mirror: a live view of one real desktop window on this Windows host, with
 * a read-only inventory and window capture. No input control is offered in this phase; the
 * structure follows the macOS Lab mirror so later hotspot/input phases can reuse the layout.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon, CircleNotchIcon, TerminalWindowIcon } from "@phosphor-icons/react";
import { Badge, Empty, Section, Skeleton, Status } from "../components/ui";
import { api, message, usePoll, type WinApp, type WinAppsInfo } from "../lib/api";

const MIRROR_INTERVAL = 3000;

function labelFor(app: WinApp): string {
  // A lock instead of a word: option text is not translated, the hint below the picker is.
  if (app.restricted) return `${app.app} \u{1F512}`;
  const title = app.title ? ` — ${app.title.slice(0, 40)}` : "";
  return `${app.app}${title}`;
}

export function WinAppsPanel() {
  const { data, error, reload } = usePoll<WinAppsInfo>(() => api.winappsApps(), MIRROR_INTERVAL);
  const [windowId, setWindowId] = useState(0);
  const [shot, setShot] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  const shotRef = useRef<string | null>(null);
  // Only the newest capture may update the view; slower, older responses are dropped.
  const grabSeq = useRef(0);
  // The seq of the capture still waiting for its response, so a slow capture is not superseded
  // by a newer one on every tick and starved of ever being shown.
  const inFlight = useRef(0);

  const windows = data?.windows ?? [];
  // Restricted windows are listed so people know they exist, but are never selected or captured.
  const usable = windows.filter((window) => !window.restricted);
  const selected = usable.find((window) => window.windowId === windowId) ?? usable[0] ?? null;

  // Pick the first window when the selection disappears (window closed or minimized).
  useEffect(() => {
    if (selected && selected.windowId !== windowId) setWindowId(selected.windowId);
  }, [selected, windowId]);

  const grab = useCallback(async () => {
    if (!selected) return;
    const seq = ++grabSeq.current;
    inFlight.current = seq;
    try {
      const res = await fetch(api.winappsAppScreenshotUrl(selected.windowId), { cache: "no-store" });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error || `${res.status} ${res.statusText}`);
      }
      const blob = await res.blob();
      if (seq !== grabSeq.current) return;
      const url = URL.createObjectURL(blob);
      if (shotRef.current) URL.revokeObjectURL(shotRef.current);
      shotRef.current = url;
      setShot(url);
      setShotError(null);
    } catch (e) {
      if (seq !== grabSeq.current) return;
      setShot(null);
      setShotError(message(e));
    } finally {
      if (inFlight.current === seq) inFlight.current = 0;
    }
  }, [selected?.windowId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => {
    if (shotRef.current) URL.revokeObjectURL(shotRef.current);
  }, []);
  useEffect(() => {
    // A different window (or none) is now selected: whatever was captured or is still in flight
    // belongs to the previous window, which may since have become restricted, so drop both.
    grabSeq.current += 1;
    if (shotRef.current) {
      URL.revokeObjectURL(shotRef.current);
      shotRef.current = null;
    }
    setShot(null);
    setShotError(null);
    if (!selected) return;
    void grab();
    const timer = setInterval(() => {
      if (!document.hidden && inFlight.current !== grabSeq.current) void grab();
    }, MIRROR_INTERVAL);
    return () => clearInterval(timer);
  }, [selected?.windowId, grab]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Section
      icon={<TerminalWindowIcon size={16} />}
      title="Window mirror"
      description="Read-only live view of one visible desktop application window. No input control in this phase."
      action={
        <button type="button" className="iux-btn" data-variant="outline" onClick={reload}>
          <ArrowClockwiseIcon size={14} /> Refresh
        </button>
      }
    >
      {error ? (
        <Status value={{ ok: false, text: error }} />
      ) : !data ? (
        <Skeleton rows={3} />
      ) : !data.available ? (
        <Empty>{data.reason ?? "The Windows app mirror is not available here."}</Empty>
      ) : windows.length === 0 ? (
        <Empty>No visible desktop application windows were found.</Empty>
      ) : usable.length === 0 ? (
        <Empty>Some windows are restricted and cannot be mirrored.</Empty>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="min-w-56 flex-1 text-sm font-medium" htmlFor="winapps-window">
              Window
            </label>
            <select
              id="winapps-window"
              className="iux-input"
              value={selected?.windowId ?? 0}
              onChange={(e) => setWindowId(Number(e.target.value))}
            >
              {windows.map((window) => (
                <option key={window.windowId} value={window.windowId} disabled={window.restricted}>
                  {labelFor(window)}
                </option>
              ))}
            </select>
            {selected ? (
              <Badge tone={selected.width > 0 && selected.height > 0 ? "success" : "warning"}>
                {`${selected.width}×${selected.height}`}
              </Badge>
            ) : null}
            {selected?.elevated ? <Badge tone="warning">Elevated</Badge> : null}
          </div>
          {usable.length < windows.length ? (
            <p className="text-xs text-zinc-500">Some windows are restricted and cannot be mirrored.</p>
          ) : null}

          <div
            className="relative w-full overflow-hidden rounded-xl border border-(--iux-border) bg-black"
            style={{
              aspectRatio: `${selected?.width || 4} / ${selected?.height || 3}`,
              // Keep the window's own shape but never taller than 70% of the viewport.
              maxWidth: `calc(70vh * ${selected?.width || 4} / ${selected?.height || 3})`,
              marginInline: "auto"
            }}
          >
            {shot ? (
              <img
                src={shot}
                alt={`Mirror of ${selected?.app ?? "the selected app"}`}
                className="absolute inset-0 h-full w-full object-fill"
                draggable={false}
              />
            ) : shotError ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-4 text-center">
                <p className="text-xs text-zinc-400">{shotError}</p>
                <button type="button" className="iux-btn" data-variant="outline" onClick={() => void grab()}>
                  Retry
                </button>
              </div>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center" aria-busy="true">
                <CircleNotchIcon size={22} className="animate-spin text-zinc-500" aria-hidden />
              </div>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
