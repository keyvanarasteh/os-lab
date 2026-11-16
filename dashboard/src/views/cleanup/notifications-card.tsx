/**
 * CLN-30: the notifications card on the cleanup Settings tab.
 *
 * The card edits the typed config through POST /api/cleanup/notifications/config
 * (the whole config is sent; the engine validates it), shows the desktop
 * app's delivery report (the runtime file the Tauri shell rewrites — absent
 * when the console runs alone, which means in-app toasts only), opens the
 * platform's fixed notification-settings pane through the same console
 * round-trip the permissions grant uses, and lists the recent outbox
 * events. The outbox itself is polled by the shared store, so this card
 * never starts a second poller and the toast stack stays in sync.
 */
import { useEffect, useState } from "react";
import { BellRingingIcon } from "@phosphor-icons/react";
import { Badge, Section, Status } from "../../components/ui";
import {
  api,
  ago,
  message,
  notificationsStore,
  type CleanupNotificationsStatus
} from "../../lib/api";

const CATEGORIES: { id: string; label: string }[] = [
  { id: "job-done", label: "Job completions" },
  { id: "job-failed", label: "Job failures" },
  { id: "auto-clean", label: "Automated hook cleans" },
  { id: "monitor-warning", label: "Monitor warnings" },
  { id: "monitor-recovered", label: "Monitor recoveries" },
  { id: "monitor-error", label: "Monitor errors" }
];

function RuntimeStatus({ runtime }: { runtime: CleanupNotificationsStatus["runtime"] }) {
  if (!runtime) {
    return <Status value={{ ok: true, text: "Desktop app not detected — in-app notifications only." }} />;
  }
  const delivery = runtime.lastDeliveryOk === undefined
    ? "No OS delivery attempt yet."
    : runtime.lastDeliveryOk ? "The last OS notification was delivered." : `The last OS notification failed: ${runtime.lastError || "unknown error"}`;
  return <Status value={{ ok: runtime.lastDeliveryOk !== false, text: `Desktop app connected${runtime.appVersion ? ` (v${runtime.appVersion})` : ""} — ${delivery}` }} />;
}

export function NotificationsCard() {
  const store = notificationsStore.use();
  const status = store.data ?? null;
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // The grant round-trip ends in the OS settings, so re-read the store when
  // the window regains focus — a finished grant flips the chips without a reload.
  useEffect(() => {
    const reread = () => { if (document.hasFocus() || document.visibilityState === "visible") void store.refresh(); };
    window.addEventListener("focus", reread);
    document.addEventListener("visibilitychange", reread);
    return () => {
      window.removeEventListener("focus", reread);
      document.removeEventListener("visibilitychange", reread);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(mutate: (current: CleanupNotificationsStatus) => CleanupNotificationsStatus) {
    if (!status) return;
    setBusy(true); setError("");
    try {
      await api.cleanupNotificationsConfig({
        enabled: mutate(status).enabled,
        categories: mutate(status).categories
      });
      await store.refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const [openError, setOpenError] = useState("");

  return (
    <Section
      id="cleanup-notifications"
      icon={<BellRingingIcon />}
      title="Notifications"
      description="What the lab announces while it works: job completions, automated hook cleans and monitor events, as in-app toasts and desktop notifications."
    >
      {!status ? null : <>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="iux-touch-target size-4" disabled={busy}
            checked={status.enabled}
            onChange={(event) => void save((current) => ({ ...current, enabled: event.target.checked }))} />
          Notifications enabled
        </label>
        <div className="mt-3 grid gap-2 sm:grid-cols-2" role="group" aria-label="Notification categories">
          {CATEGORIES.map((category) => (
            <label key={category.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="iux-touch-target size-4" disabled={busy || !status.enabled}
                checked={!!status.categories[category.id]}
                onChange={(event) => void save((current) => ({
                  ...current,
                  categories: { ...current.categories, [category.id]: event.target.checked }
                }))} />
              {category.label}
            </label>
          ))}
        </div>
        <div className="mt-4 rounded-md border border-(--iux-border) p-3 text-sm">
          <p className="font-medium">Desktop notifications</p>
          <div className="mt-2"><RuntimeStatus runtime={status.runtime} /></div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button type="button" className="iux-btn" disabled={busy}
              onClick={() => {
                setOpenError("");
                void api.cleanupNotificationsOpenSettings().catch((e) => setOpenError(message(e)));
              }}>Open System Settings</button>
            <Badge>{status.runtime?.platform ? <span translate="no">{status.runtime.platform}</span> : "in-app only"}</Badge>
          </div>
          {openError && <div className="mt-2"><Status value={{ ok: false, text: openError }} /></div>}
        </div>
        {status.configError && <div className="mt-3"><Status value={{ ok: false, text: status.configError }} /></div>}
        {error && <div className="mt-3"><Status value={{ ok: false, text: error }} /></div>}
        {status.events.length > 0 && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer">Recent notifications ({status.events.length})</summary>
            <ul className="mt-2 space-y-1">
              {[...status.events].reverse().slice(0, 8).map((event) => (
                <li key={event.id} className="flex items-baseline gap-2 rounded-md border border-(--iux-border) p-2">
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{event.title}</span>{" "}
                    <span className="text-xs text-(--iux-muted-foreground)">{event.body}</span>
                  </span>
                  <span className="shrink-0 text-xs text-(--iux-muted-foreground)">{ago(event.at)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </>}
    </Section>
  );
}
