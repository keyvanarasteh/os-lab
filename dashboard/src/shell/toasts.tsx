/**
 * CLN-30: the in-app notification stack.
 *
 * The shell mounts this beside the update modal on every dashboard page. It
 * subscribes to the shared notification store (one poller per browser tab),
 * toasts only events newer than the last-seen cursor in localStorage (a page
 * load never replays history), and renders a small bottom-right stack: icon,
 * title, body, the event's action links, swipe or button to dismiss, and a
 * quiet auto-dismiss timer that pauses while the pointer is over the card.
 * Public Pages never mounts it — the store itself stays unsubscribed there.
 */
import { useEffect, useRef, useState } from "react";
import {
  BellRingingIcon,
  BroomIcon,
  CheckCircleIcon,
  WarningCircleIcon,
  WarningIcon,
  XIcon
} from "@phosphor-icons/react";
import { localeFromPath, localePath } from "../i18n/paths";
import { notificationsStore, type NotificationEvent } from "../lib/api";

const PUBLIC_PAGES = import.meta.env.PUBLIC_SITE_MODE === "pages";
const SEEN_KEY = "oslab.notif.seen";
const MAX_VISIBLE = 3;
const MAX_ACTIVE = 12;
const PLAIN_LIFETIME = 6500;
const ACTION_LIFETIME = 15000;
const TICK = 250;
const SWIPE_DISMISS = 80;
const SWIPE_RANGE = 120;

/** Section routes live on the Settings tab; tabs are plain cleanup paths. */
const ROUTE_PATH: Record<string, string> = {
  dashboard: "/cleanup/",
  scan: "/cleanup/scan/",
  results: "/cleanup/results/",
  leftovers: "/cleanup/leftovers/",
  history: "/cleanup/history/",
  space: "/cleanup/space/",
  "cleanup-bookmarks": "/cleanup/settings/",
  "cleanup-monitor": "/cleanup/settings/",
  "cleanup-permissions": "/cleanup/settings/",
  "cleanup-widgets": "/cleanup/settings/",
  "cleanup-notifications": "/cleanup/settings/"
};

function routeHref(route: string | null): string | null {
  if (!route) return null;
  const path = ROUTE_PATH[route];
  return path ? localePath(path, typeof window === "undefined" ? "en" : localeFromPath(window.location.pathname)) : null;
}

function Icon({ event }: { event: NotificationEvent }) {
  const size = 16;
  if (event.category === "job-failed" || event.category === "monitor-error") return <WarningCircleIcon size={size} />;
  if (event.category === "monitor-warning") return <WarningIcon size={size} />;
  if (event.category === "auto-clean") return <BroomIcon size={size} />;
  return <CheckCircleIcon size={size} />;
}

function tone(event: NotificationEvent): { border: string; background: string } {
  if (event.category === "job-failed" || event.category === "monitor-error") {
    return { border: "border-(--iux-danger)/50", background: "bg-(--iux-danger)/10" };
  }
  if (event.category === "monitor-warning") {
    return { border: "border-(--iux-warning)/50", background: "bg-(--iux-warning)/10" };
  }
  return { border: "border-(--iux-border)", background: "bg-(--iux-card)" };
}

function readSeen(): number {
  try {
    const value = window.localStorage.getItem(SEEN_KEY);
    const parsed = value ? Number.parseInt(value, 10) : 0;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  } catch {
    return 0;
  }
}

function writeSeen(id: number) {
  try {
    window.localStorage.setItem(SEEN_KEY, String(id));
  } catch {
    /* private mode: toasts still work, they just replay after a reload */
  }
}

function Toast({ event, onDismiss }: { event: NotificationEvent; onDismiss: () => void }) {
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const remaining = useRef(event.actions.length ? ACTION_LIFETIME : PLAIN_LIFETIME);
  const paused = useRef(false);
  const startX = useRef<number | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!paused.current && startX.current === null) {
        remaining.current -= TICK;
        if (remaining.current <= 0) onDismiss();
      }
    }, TICK);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const border = tone(event).border;
  const background = tone(event).background;

  return (
    <div
      role="status"
      className={`pointer-events-auto w-80 overflow-hidden rounded-md border ${border} ${background} p-3 text-sm shadow-lg backdrop-blur`}
      style={{
        transform: `translateX(${dx}px)`,
        opacity: Math.max(0.4, 1 - Math.abs(dx) / SWIPE_RANGE),
        transition: dragging ? "none" : "transform 150ms ease, opacity 150ms ease"
      }}
      onPointerEnter={() => { paused.current = true; }}
      onPointerLeave={() => { paused.current = false; }}
      onPointerDown={(pointer) => {
        startX.current = pointer.clientX;
        setDragging(true);
        pointer.currentTarget.setPointerCapture(pointer.pointerId);
      }}
      onPointerMove={(pointer) => {
        if (startX.current === null) return;
        const delta = pointer.clientX - startX.current;
        if (Math.abs(delta) > 4) setDx(Math.max(-SWIPE_RANGE, Math.min(SWIPE_RANGE, delta)));
      }}
      onPointerUp={(pointer) => {
        const delta = startX.current === null ? 0 : pointer.clientX - startX.current;
        startX.current = null;
        setDragging(false);
        if (Math.abs(delta) >= SWIPE_DISMISS) onDismiss();
        else setDx(0);
      }}
      onPointerCancel={() => { startX.current = null; setDragging(false); setDx(0); }}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0"><Icon event={event} /></span>
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-5">{event.title}</p>
          <p className="mt-0.5 text-xs text-(--iux-muted-foreground)">{event.body}</p>
          {event.actions.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {event.actions.map((action) => {
                const href = routeHref(action.route);
                return href
                  ? <a key={action.id} className="iux-btn h-7 px-2 text-xs" data-variant="outline" href={href}>{action.label}</a>
                  : <button key={action.id} type="button" className="iux-btn h-7 px-2 text-xs" data-variant="outline" onClick={onDismiss}>{action.label}</button>;
              })}
            </div>
          )}
        </div>
        <button
          type="button"
          aria-label="Dismiss notification"
          className="shrink-0 rounded p-1 text-(--iux-muted-foreground) hover:bg-(--iux-muted) hover:text-(--iux-foreground)"
          onClick={onDismiss}
        >
          <XIcon size={12} />
        </button>
      </div>
    </div>
  );
}

export function ToastHost() {
  const store = notificationsStore.use();
  const events = store.data?.events ?? [];
  const [active, setActive] = useState<NotificationEvent[]>([]);
  const seen = useRef(readSeen());
  const mounted = useRef(false);

  useEffect(() => {
    if (PUBLIC_PAGES) return;
    if (!mounted.current) {
      // The host has loaded: adopt the cursor so a page load never replays
      // the stored history. Events that were not in the outbox at load —
      // including an outbox that was empty — toast normally from now on.
      mounted.current = true;
      const newest = events.length ? events[events.length - 1].id : seen.current;
      seen.current = Math.max(seen.current, newest);
      writeSeen(seen.current);
      return;
    }
    const known = new Set(active.map((item) => item.id));
    const fresh = events.filter((item) => item.id > seen.current && !known.has(item.id));
    if (fresh.length) {
      seen.current = Math.max(seen.current, ...fresh.map((item) => item.id));
      writeSeen(seen.current);
      setActive((old) => [...[...fresh].reverse(), ...old].slice(0, MAX_ACTIVE));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  const dismiss = (id: number) => setActive((old) => old.filter((item) => item.id !== id));
  const clearAll = () => setActive([]);
  const visible = active.slice(0, MAX_VISIBLE);
  const overflow = active.length - visible.length;

  if (PUBLIC_PAGES || !active.length) return null;
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
      {overflow > 0 && (
        <button
          type="button"
          className="pointer-events-auto rounded-full border border-(--iux-border) bg-(--iux-card) px-2 py-0.5 text-xs text-(--iux-muted-foreground) hover:text-(--iux-foreground)"
          onClick={clearAll}
        >
          +{overflow}
        </button>
      )}
      {visible.map((event) => <Toast key={event.id} event={event} onDismiss={() => dismiss(event.id)} />)}
      {active.length > 1 && (
        <button
          type="button"
          className="pointer-events-auto text-xs text-(--iux-muted-foreground) underline hover:text-(--iux-foreground)"
          onClick={clearAll}
        >
          Clear all
        </button>
      )}
    </div>
  );
}
