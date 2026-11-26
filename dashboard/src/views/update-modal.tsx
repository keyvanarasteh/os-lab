/**
 * The update center, mounted once in the layout so it works on every page.
 *
 * It checks the desktop app's signed release feed and the content pack on load and opens on its own
 * for something new ("Later" remembers the offered versions). The top bar's update button reopens it
 * at any time and checks again. The app update downloads with progress, is verified, and its
 * installer is opened by the operating system; then os-lab closes itself so the update can finish.
 * If lab or Cleanup Lab work is still running, it waits for that work (and shows it) before closing,
 * unless the user chooses Close now. Nothing closes outside the desktop app.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowsClockwiseIcon, DownloadSimpleIcon, XIcon } from "@phosphor-icons/react";
import { Status } from "../components/ui";
import { api, formatBytes, message, type AppUpdateState, type ContentState } from "../lib/api";
import { keepModalFocus } from "./modal-focus";
import { appOffered, OPEN_UPDATES, setUpdateSnapshot } from "./update-store";

const DISMISSED = "oslab.update.dismissed";
const FRESH_SECONDS = 900;
const CLOSE_COUNTDOWN = 5;
const fresh = (checkedAt: number | null) => Boolean(checkedAt && Date.now() / 1000 - checkedAt < FRESH_SECONDS);

const readDismissed = () => {
  try { return window.localStorage.getItem(DISMISSED) ?? ""; } catch { return ""; }
};
const writeDismissed = (value: string) => {
  try { window.localStorage.setItem(DISMISSED, value); } catch { /* Private mode: the prompt returns next launch. */ }
};

const contentOffered = (s: ContentState | null) =>
  s && !s.offline && s.latest && s.latest.sequence > s.sequence ? s : null;
const offerKey = (app: AppUpdateState | null, content: ContentState | null) =>
  `${appOffered(app) ? `app:${app?.latest}` : ""}|${contentOffered(content) ? `content:${content?.latest?.sequence}` : ""}`;

/** Ask the desktop app to quit; it checks with the console that the installer opened (and work is idle unless forced). */
function quitForUpdate(force: boolean) {
  window.dispatchEvent(new CustomEvent("oslab:quit-for-update", { detail: { force } }));
  window.location.href = `oslab://app/quit-for-update${force ? "?force=1" : ""}`;
}

type Result = { ok: boolean; text: string } | null;
type CloseFlow = "off" | "auto" | "cancelled";

export function UpdateModal() {
  const [app, setApp] = useState<AppUpdateState | null>(null);
  const [content, setContent] = useState<ContentState | null>(null);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [appBusy, setAppBusy] = useState(false);
  const [contentBusy, setContentBusy] = useState(false);
  const [hooks, setHooks] = useState(false);
  const [appResult, setAppResult] = useState<Result>(null);
  const [contentResult, setContentResult] = useState<Result>(null);
  const [closeFlow, setCloseFlow] = useState<CloseFlow>("off");
  const [countdown, setCountdown] = useState<number | null>(null);
  const box = useRef<HTMLDialogElement>(null);
  const started = useRef(false);

  const runChecks = useCallback(async (force: boolean) => {
    setChecking(true);
    const checkApp = async () => {
      const current = await api.appUpdateStatus();
      if (!current.supported || current.offline) return current;
      return !force && fresh(current.checkedAt) ? current : { ...current, ...(await api.appUpdateCheck()) };
    };
    const checkContent = async () => {
      const current = await api.contentStatus();
      if (current.offline) return current;
      return !force && fresh(current.checkedAt) ? current : api.contentCheck();
    };
    // A failed check (offline, no console) just means nothing to offer.
    const [a, c] = await Promise.allSettled([checkApp(), checkContent()]);
    const nextApp = a.status === "fulfilled" ? a.value : null;
    const nextContent = c.status === "fulfilled" ? c.value : null;
    setApp(nextApp);
    setContent(nextContent);
    setChecking(false);
    if (force && a.status === "rejected") setAppResult({ ok: false, text: message(a.reason) });
    return { nextApp, nextContent };
  }, []);

  // First check on load, on whichever page the app opens.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void runChecks(false).then(({ nextApp, nextContent }) => {
      if ((appOffered(nextApp) || contentOffered(nextContent)) && readDismissed() !== offerKey(nextApp, nextContent)) setOpen(true);
    });
  }, [runChecks]);

  // The top bar's update button (or anything else) opens the center and checks again.
  useEffect(() => {
    const onOpen = (event: Event) => {
      setOpen(true);
      setAppResult(null);
      const check = (event as CustomEvent<{ check?: boolean }>).detail?.check !== false;
      if (check) void runChecks(true);
    };
    window.addEventListener(OPEN_UPDATES, onOpen);
    return () => window.removeEventListener(OPEN_UPDATES, onOpen);
  }, [runChecks]);

  useEffect(() => { setUpdateSnapshot({ app, content }); }, [app, content]);

  useEffect(() => {
    const dialog = box.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const phase = app?.install?.phase;
  const busyWork = app?.busy ?? [];

  // Follow the download, then the running work, through the console.
  useEffect(() => {
    if (!app?.installing && !(phase === "done" && closeFlow === "auto")) return;
    const timer = setInterval(async () => {
      try { setApp(await api.appUpdateStatus()); } catch { /* Keep the last state; the next tick retries. */ }
    }, 1000);
    return () => clearInterval(timer);
  }, [app?.installing, phase, closeFlow]);

  // An opened installer starts the close flow and brings the center forward.
  const lastPhase = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (phase === "done" && lastPhase.current && lastPhase.current !== "done") {
      setCloseFlow("auto");
      setOpen(true);
    }
    lastPhase.current = phase;
  }, [phase]);

  // Nothing running: count down, then quit. Work running: wait, and restart the count when it ends.
  useEffect(() => {
    if (closeFlow !== "auto" || phase !== "done" || busyWork.length) { setCountdown(null); return; }
    setCountdown(CLOSE_COUNTDOWN);
    const timer = setInterval(() => {
      setCountdown((value) => {
        if (value === null) return null;
        if (value <= 1) { clearInterval(timer); quitForUpdate(false); return 0; }
        return value - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [closeFlow, phase, busyWork.length]);

  function later() {
    if (appOffered(app) || contentOffered(content)) writeDismissed(offerKey(app, content));
    setOpen(false);
  }

  async function installApp() {
    setAppBusy(true);
    setAppResult(null);
    setCloseFlow("off");
    try {
      const next = await api.appUpdateInstall();
      setApp((old) => ({ ...(old ?? next), ...next }));
    } catch (e) {
      setAppResult({ ok: false, text: message(e) });
    } finally {
      setAppBusy(false);
    }
  }

  async function installContent() {
    setContentBusy(true);
    setContentResult(null);
    try {
      setContent(await api.contentUpdate(hooks));
      setContentResult({ ok: true, text: "Content updated." });
    } catch (e) {
      setContentResult({ ok: false, text: message(e) });
    } finally {
      setContentBusy(false);
    }
  }

  const offeredApp = appOffered(app);
  const offeredContent = contentOffered(content);
  const install = app?.install;
  const appWorking = appBusy || phase === "downloading" || phase === "opening";
  const percent = install?.total ? Math.min(100, Math.round(((install.received ?? 0) / install.total) * 100)) : null;
  const showApp = Boolean(offeredApp || phase);

  return (
    <dialog
      ref={box}
      aria-labelledby="update-title"
      tabIndex={-1}
      className="iux iux-dialog iux-spotlight"
      onClose={() => setOpen(false)}
      onKeyDown={keepModalFocus}
      onMouseDown={(e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) later();
      }}
    >
      <div className="flex flex-col gap-5 p-5">
        <header className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <h2 id="update-title" className="text-base font-semibold">{offeredApp || offeredContent ? "Updates available" : "Updates"}</h2>
            <p className="text-xs text-(--iux-muted-foreground)">
              Both come from signed releases; each download is verified before it is installed.
            </p>
          </div>
          <button type="button" className="iux-btn shrink-0" data-variant="ghost" data-size="icon" aria-label="Remind me later" onClick={later}>
            <XIcon size={16} />
          </button>
        </header>

        {showApp && app ? (
          <section className="flex flex-col gap-3" aria-label="App update">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1 text-sm">
                <p className="flex items-center gap-2 font-medium"><DownloadSimpleIcon size={16} /> <span>App update</span></p>
                <p className="text-xs text-(--iux-muted-foreground)" data-no-translate>{app.installed} → {app.latest}</p>
              </div>
              {phase !== "done" ? (
                <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" disabled={appWorking} onClick={() => void installApp()}>
                  {phase === "downloading" ? "Downloading…" : phase === "opening" ? "Opening installer…" : "Install update"}
                </button>
              ) : null}
            </div>

            {phase === "downloading" ? (
              <div role="status" className="space-y-1">
                {percent !== null
                  ? <progress className="h-2 w-full accent-[#f36c21]" value={install?.received ?? 0} max={install?.total ?? 1} aria-label="Downloading the update" />
                  : <progress className="h-2 w-full accent-[#f36c21]" aria-label="Downloading the update" />}
                <p className="text-xs tabular-nums text-(--iux-muted-foreground)" dir="ltr">
                  {formatBytes(install?.received ?? 0)}{install?.total ? ` / ${formatBytes(install.total)} · ${percent}%` : ""}
                </p>
              </div>
            ) : null}

            {phase === "done" ? (
              <div className="flex flex-col gap-3 rounded-md border border-(--iux-border) p-3 text-sm" role="status">
                <p><span>The installer is open.</span>{install?.path ? <> <span className="text-xs text-(--iux-muted-foreground)" data-no-translate>{install.path}</span></> : null}</p>
                {app.kind === "appimage" ? (
                  <p className="text-xs text-(--iux-muted-foreground)">
                    The new AppImage was saved beside your current one. Replace the running file with it, then start os-lab again.
                  </p>
                ) : null}
                {closeFlow === "auto" && !busyWork.length ? (
                  <p className="font-medium"><span>os-lab closes so the update can finish in</span> <span className="tabular-nums" dir="ltr">{countdown ?? CLOSE_COUNTDOWN} s</span></p>
                ) : null}
                {closeFlow === "auto" && busyWork.length ? (
                  <div className="flex flex-col gap-2">
                    <p className="font-medium">
                      <span>Waiting for running work to finish before closing</span> <span className="tabular-nums" dir="ltr">({busyWork.length})</span>
                    </p>
                    <ul className="flex flex-col gap-2">
                      {busyWork.map((work) => (
                        <li key={`${work.kind}-${work.id}`} className="text-xs">
                          <span className="block truncate">{work.label}</span>
                          {work.progress !== null
                            ? <progress className="mt-1 h-1.5 w-full accent-[#f36c21]" value={work.progress} max={1} aria-label={work.label} />
                            : <progress className="mt-1 h-1.5 w-full accent-[#f36c21]" aria-label={work.label} />}
                        </li>
                      ))}
                    </ul>
                    <p className="text-xs text-(--iux-muted-foreground)">Close now stops the running work.</p>
                  </div>
                ) : null}
                {closeFlow !== "auto" ? (
                  <p className="text-xs text-(--iux-muted-foreground)">Quit os-lab when you are ready, so the installer can replace it.</p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" onClick={() => quitForUpdate(true)}>Close now</button>
                  {closeFlow === "auto"
                    ? <button type="button" className="iux-btn" data-variant="outline" onClick={() => setCloseFlow("cancelled")}>Don't close</button>
                    : <button type="button" className="iux-btn" data-variant="outline" onClick={() => setCloseFlow("auto")}>Close when idle</button>}
                </div>
              </div>
            ) : null}

            {phase === "error" || appResult ? <Status value={{ ok: false, text: install?.error || appResult?.text || "The update could not be installed." }} /> : null}
            {app.releaseUrl ? <a className="text-xs underline" href={app.releaseUrl} target="_blank" rel="noreferrer">Release notes</a> : null}
          </section>
        ) : null}

        {!showApp && !offeredContent ? (
          <section className="flex flex-col gap-2 text-sm" aria-label="App update">
            {checking ? <p role="status">Checking for updates…</p>
              : app?.supported && !app.offline ? <p><span>os-lab is up to date.</span> <span className="text-(--iux-muted-foreground)" data-no-translate>{app.installed}</span></p>
              : app?.offline ? <p className="text-(--iux-muted-foreground)">Update checks are switched off on this computer.</p>
              : <p className="text-(--iux-muted-foreground)">App updates install from the os-lab desktop app.</p>}
            {appResult ? <Status value={appResult} /> : null}
          </section>
        ) : null}

        {offeredContent ? (
          <section className="flex flex-col gap-3" aria-label="Content update">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="space-y-1 text-sm">
                <p className="flex items-center gap-2 font-medium"><ArrowsClockwiseIcon size={16} /> <span>Content update</span></p>
                <p className="text-xs text-(--iux-muted-foreground)" data-no-translate>{offeredContent.version} → {offeredContent.latest?.version}</p>
              </div>
              <button type="button" className="iux-btn bg-[#f36c21] text-white hover:bg-[#fa7b32]" disabled={contentBusy} onClick={() => void installContent()}>
                {contentBusy ? "Installing…" : "Install update"}
              </button>
            </div>
            {contentBusy ? <progress className="h-2 w-full accent-[#f36c21]" aria-label="Installing the content pack" /> : null}
            {offeredContent.hooks ? (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={hooks} onChange={(e) => setHooks(e.target.checked)} disabled={contentBusy} />
                <span>
                  <span className="font-medium">Include Frida hooks</span>
                  <span className="block text-xs text-(--iux-muted-foreground)">Hooks are installed on this computer. They update only when you tick this box.</span>
                </span>
              </label>
            ) : null}
            {contentResult && !contentResult.ok ? <Status value={contentResult} /> : null}
          </section>
        ) : contentResult?.ok ? <Status value={contentResult} /> : null}

        <footer className="flex justify-end gap-2">
          {!checking ? <button type="button" className="iux-btn" data-variant="ghost" onClick={() => void runChecks(true)}>Check again</button> : null}
          <button type="button" className="iux-btn" data-variant="outline" onClick={later}>Later</button>
        </footer>
      </div>
    </dialog>
  );
}
