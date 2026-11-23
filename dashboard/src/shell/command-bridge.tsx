/**
 * AGQ-01: the command bridge. The desktop app's `oslab://` bridge hands every
 * command to `window.__oslabCommand`, which lives here in the shell so it
 * exists on every page — not only on Cleanup or the macOS Lab. Routes open the
 * matching dashboard page; `panic-stop` reports the console's own result;
 * `quick-clean` opens Cleanup and leaves the plan → confirm dialog to the page.
 *
 * Nothing here deletes or arms: a command button can stop control mode and open
 * a cleanup plan, and the user still confirms that plan in the dashboard.
 *
 * Every failure shows the console's text unchanged — a command that did not
 * work must never look like one that did.
 */
import { useEffect, useState } from "react";

// @lat: [[cleanup-lab#Command bridge (AGQ-01)]]
import { XIcon } from "@phosphor-icons/react";

/** What the Rust bridge serialises (`bridge::Directive`). */
export type CommandDirective = {
  command: "navigate" | "quick-clean" | "panic-stop" | "refused";
  route?: string;
  ok?: boolean;
  detail?: string;
  url?: string;
};

type Banner = { tone: "busy" | "ok" | "error"; text: string; detail?: string };

/** Widget routes the island router resolves in place (it knows these ids). */
const CLEANUP_TARGETS = new Set([
  "dashboard", "scan", "results", "leftovers", "history", "space",
  "cleanup-bookmarks", "cleanup-monitor", "cleanup-permissions", "cleanup-widgets",
]);

/** Every other route is a page the sidebar already links to. */
const ROUTE_TO_SECTION: Record<string, string> = {
  host: "host",
  jobs: "jobs",
  health: "health",
  contribute: "contribute",
  content: "content",
  feedback: "feedback",
  "how-to-use": "how-to-use",
  firewall: "firewall",
  "web-lab": "web-lab",
  "labs/android": "lab-android",
  "labs/windows": "lab-windows",
  "labs/winapps": "lab-winapps",
  "labs/linux": "lab-linux",
  "labs/ios": "lab-ios",
  "labs/macos": "lab-macos",
  "labs/source": "lab-source",
  "labs/web": "lab-web",
};

/**
 * `resolveHref` maps a dashboard section id to its localized href. The shell
 * passes its own `sectionHref` in, because importing it here would make the
 * two modules import each other — a cycle whose evaluation order depends on
 * module load order and can leave the page blank.
 */
export function CommandBridgeBanner({ resolveHref }: { resolveHref: (id: string) => string }) {
  const [banner, setBanner] = useState<Banner | null>(null);

  useEffect(() => {
    const show = (tone: Banner["tone"], text: string, detail?: string) => setBanner({ tone, text, detail });

    /** Open a widget route: the island router in place, otherwise the page. */
    const open = (route: string) => {
      const inPlace = (window as unknown as { __oslabNavigate?: (r: string) => void }).__oslabNavigate;
      if (inPlace && CLEANUP_TARGETS.has(route)) {
        inPlace(route);
        return;
      }
      window.location.assign(resolveHref(ROUTE_TO_SECTION[route] ?? "cleanup-dashboard"));
    };

    const handle = (directive: CommandDirective | null) => {
      if (!directive || typeof directive !== "object") return;
      switch (directive.command) {
        case "navigate":
          if (directive.route) open(directive.route);
          return;
        case "quick-clean": {
          // The Cleanup page owns the plan → confirm dialog; ask it for the
          // quick-clean flow exactly as the bookmarks button does.
          const quickClean = (window as unknown as { __oslabQuickClean?: () => void }).__oslabQuickClean;
          if (quickClean) {
            quickClean();
            return;
          }
          open("dashboard");
          show("busy", "Opening Cleanup Lab…");
          window.setTimeout(() => {
            (window as unknown as { __oslabQuickClean?: () => void }).__oslabQuickClean?.();
          }, 400);
          return;
        }
        case "panic-stop": {
          if (directive.ok) {
            const closed = directive.detail ? Number(directive.detail) : 0;
            show("ok", closed > 0
              ? `macOS control stopped · ${closed} session${closed === 1 ? "" : "s"} closed`
              : "macOS control stopped");
          } else {
            show("error", "Could not stop macOS control", directive.detail || "The console did not answer.");
          }
          return;
        }
        case "refused":
          show("error", "That command is not available", directive.url || "");
          return;
        default:
          return;
      }
    };

    (window as unknown as { __oslabCommand?: (d: CommandDirective | null) => void }).__oslabCommand = handle;
    return () => {
      delete (window as unknown as { __oslabCommand?: unknown }).__oslabCommand;
    };
  }, [resolveHref]);

  if (!banner) return null;
  const error = banner.tone === "error";
  return (
    <div
      role={error ? "alert" : "status"}
      aria-live={error ? "assertive" : "polite"}
      data-command-bridge={banner.tone}
      className={`fixed bottom-4 left-4 right-4 z-50 flex items-start gap-3 rounded-lg border bg-(--iux-card) p-3 text-sm shadow-lg sm:left-auto sm:max-w-md ${
        error ? "border-(--iux-danger)" : "border-(--iux-border)"
      }`}
    >
      <div className="min-w-0 flex-1">
        <p className={error ? "text-(--iux-danger)" : undefined}>{banner.text}</p>
        {banner.detail ? (
          <p data-no-translate className="mt-1 break-words text-xs text-(--iux-muted-foreground)">
            {banner.detail}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        className="iux-btn shrink-0"
        data-variant="ghost"
        data-size="icon"
        aria-label="Dismiss"
        onClick={() => setBanner(null)}
      >
        <XIcon size={16} />
      </button>
    </div>
  );
}
